#!/usr/bin/env python
"""harvest-box.py - build one KHS-1 harvest bundle from a Bot-OS box (HARVEST-STANDARD.md).

Runs ON the box. Stdlib only (Python 3.11+); the registry is a small YAML subset parsed here so
PyYAML is not required.

    python harvest-box.py --site s-0dc1 --registry boxes.yaml
        # dry run: manifest + scrub report to stdout
    python harvest-box.py --site s-0dc1 --registry boxes.yaml --ship
        # write bundle dir + .tar.gz + receipt
    python harvest-box.py --list --registry boxes.yaml
    python harvest-box.py --site s-pcl --registry boxes.yaml --full --ship \\
        --out E:\\Local-AI\\botos-harvest\\inbox

Incremental: a file is included only if its sha changed since harvest/<site>/.last-manifest.json.
Everything copied is scrubbed with the same patterns as botos2jsonl.py (imported when it sits next
to this script; otherwise a built-in copy of the patterns is used).
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

TOOL = "harvest-box.py 1.0"
KHS = 1
TYPES = ("episodic", "semantic", "procedural", "transcripts", "telemetry")

# --------------------------------------------------------------------------- scrubber
try:  # reuse the single source of truth when available
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from botos2jsonl import Scrubber, load_deny_list  # type: ignore
except Exception:  # pragma: no cover - fallback when shipped alone
    _PATTERNS = [
        (
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            "[REDACTED_KEY]",
        ),
        (r"\b(?:sk|rk|pk)-[A-Za-z0-9_\-]{16,}\b", "[REDACTED_TOKEN]"),
        (r"\bgh[pousr]_[A-Za-z0-9]{20,}\b", "[REDACTED_TOKEN]"),
        (r"\bAKIA[0-9A-Z]{16}\b", "[REDACTED_AWS_KEY]"),
        (r"\bhf_[A-Za-z0-9]{20,}\b", "[REDACTED_TOKEN]"),
        (r"(?i)\b(bearer)\s+[A-Za-z0-9_\-\.=]{16,}", r"\1 [REDACTED_TOKEN]"),
        (
            r"(?i)\b(pass(?:word|wd|phrase)?|secret|token|api[_\-]?key|auth)\s*[:=]\s*['\"]?"
            r"[^\s'\"]{6,}",
            r"\1=[REDACTED]",
        ),
        (r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", "[EMAIL]"),
        (r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[IP]"),
    ]

    class Scrubber:  # type: ignore[no-redef]
        def __init__(self, deny_domains=None):
            self.hits: dict[str, int] = {}
            self._rx = [(re.compile(p, re.S), r) for p, r in _PATTERNS]
            self._deny = [re.compile(r"(?i)" + re.escape(d)) for d in (deny_domains or []) if d]

        def __call__(self, text: str) -> str:
            for rx, rep in self._rx:
                text, n = rx.subn(rep, text)
                if n:
                    self.hits[rep] = self.hits.get(rep, 0) + n
            for rx in self._deny:
                text, n = rx.subn("[CLIENT_DOMAIN]", text)
                if n:
                    self.hits["[CLIENT_DOMAIN]"] = self.hits.get("[CLIENT_DOMAIN]", 0) + n
            return text

    def load_deny_list(path):  # type: ignore[no-redef]
        if not path or not os.path.exists(path):
            return []
        return [
            ln.split("#", 1)[0].strip()
            for ln in Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
            if ln.split("#", 1)[0].strip()
        ]


# --------------------------------------------------------------------------- tiny YAML subset


def _parse_scalar(s: str):
    s = s.strip()
    if not s:
        return ""
    if s[0] in "'\"" and s[-1] == s[0] and len(s) >= 2:
        return s[1:-1]
    if s.startswith("["):
        inner = s[1:-1].strip()
        if not inner:
            return []
        out, cur, q = [], "", None
        for ch in inner:
            if q:
                if ch == q:
                    q = None
                else:
                    cur += ch
            elif ch in "'\"":
                q = ch
            elif ch == ",":
                out.append(cur.strip())
                cur = ""
            else:
                cur += ch
        out.append(cur.strip())
        return [x for x in out if x]
    if s in ("true", "True"):
        return True
    if s in ("false", "False"):
        return False
    return s


def load_registry(path: str) -> dict:
    """Parse boxes.yaml (2-space indent, lists of mappings, flow lists, quoted scalars)."""
    lines = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        if "#" in raw and not raw.strip().startswith("#"):
            # strip trailing comment unless inside quotes
            q = None
            for i, ch in enumerate(raw):
                if q:
                    if ch == q:
                        q = None
                elif ch in "'\"":
                    q = ch
                elif ch == "#":
                    raw = raw[:i].rstrip()
                    break
        if raw.strip() and not raw.strip().startswith("#"):
            lines.append(raw.rstrip())

    def parse_block(i: int, indent: int):
        if i < len(lines) and lines[i].lstrip().startswith("- "):
            items = []
            while i < len(lines):
                ln = lines[i]
                ind = len(ln) - len(ln.lstrip())
                if ind < indent or not ln.lstrip().startswith("- "):
                    break
                first = ln.lstrip()[2:]
                item: dict = {}
                if ":" in first:
                    k, v = first.split(":", 1)
                    item[k.strip()] = _parse_scalar(v)
                i += 1
                sub, i = parse_block(i, ind + 2)
                if isinstance(sub, dict):
                    item.update(sub)
                items.append(item)
            return items, i
        obj: dict = {}
        while i < len(lines):
            ln = lines[i]
            ind = len(ln) - len(ln.lstrip())
            if ind < indent or ln.lstrip().startswith("- "):
                break
            if ind > indent:
                i += 1
                continue
            k, v = ln.strip().split(":", 1)
            if v.strip():
                obj[k.strip()] = _parse_scalar(v)
                i += 1
            else:
                i += 1
                child, i = parse_block(i, ind + 2)
                obj[k.strip()] = child
        return obj, i

    data, _ = parse_block(0, 0)
    return data


# --------------------------------------------------------------------------- collection


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _excluded(rel: str, patterns: list[str], drop: re.Pattern | None) -> bool:
    parts = rel.replace("\\", "/").split("/")
    for pat in patterns:
        if any(fnmatch.fnmatch(p, pat) for p in parts) or fnmatch.fnmatch(parts[-1], pat):
            return True
    return bool(drop and drop.search(rel))


def _expand(root: Path, spec: str) -> list[Path]:
    """Resolve one include spec (dir, file, or glob with * in dir names) under root."""
    spec = spec.replace("\\", "/")
    try:
        matches = list(root.glob(spec)) if any(ch in spec for ch in "*?[") else [root / spec]
    except (OSError, ValueError):
        return []
    out: list[Path] = []
    for m in matches:
        if m.is_dir():
            out.extend(p for p in m.rglob("*") if p.is_file())
        elif m.is_file():
            out.append(m)
    return out


def collect(
    box: dict, defaults: dict, *, full: bool, last: dict, scrub: Scrubber, max_bytes: int
) -> tuple[list[dict], dict[str, bytes], int]:
    root = Path(os.path.expanduser(str(box["root"])))
    include = dict(defaults.get("include", {}))
    include.update(box.get("include", {}) or {})
    exclude = list(defaults.get("exclude", [])) + list(box.get("exclude_extra", []) or [])
    drop_s = box.get("drop_pattern") or defaults.get("drop_pattern")
    drop = re.compile(drop_s) if drop_s else None
    last_sha = {f["path"]: f["sha256"] for f in last.get("files", [])}

    files: list[dict] = []
    payload: dict[str, bytes] = {}
    n_excluded = 0
    seen: set[str] = set()

    def add(kind: str, src: Path, rel: str, text_mode: bool) -> None:
        nonlocal n_excluded
        rel = rel.replace("\\", "/")
        if _excluded(rel, exclude, drop):
            n_excluded += 1
            return
        dest = f"{kind}/{rel}"
        if dest in seen:
            return
        seen.add(dest)
        try:
            st = src.stat()
            if st.st_size > max_bytes:
                n_excluded += 1
                return
            raw = src.read_bytes()
        except OSError:
            return
        if text_mode:
            raw = scrub(raw.decode("utf-8", "replace")).encode("utf-8")
        sha = _sha(raw)
        if not full and last_sha.get(dest) == sha:
            return
        files.append(
            {
                "path": dest,
                "sha256": sha,
                "bytes": len(raw),
                "mtime": _iso(st.st_mtime),
                "type": kind,
            }
        )
        payload[dest] = raw

    if root.is_dir():
        for kind in ("episodic", "semantic", "procedural", "telemetry"):
            for spec in include.get(kind, []) or []:
                for p in _expand(root, spec):
                    add(kind, p, str(p.relative_to(root)), text_mode=True)
    for d in box.get("claude_projects", []) or []:
        base = Path(os.path.expanduser(str(d)))
        if not base.is_dir():
            continue
        for p in base.rglob(defaults.get("transcripts_glob", "*.jsonl")):
            if p.is_file():
                add("transcripts", p, f"{base.name}/{p.relative_to(base)}", text_mode=True)
    return files, payload, n_excluded


# --------------------------------------------------------------------------- bundle


def build_manifest(
    box: dict, files: list[dict], scrub: Scrubber, *, full: bool, since: str | None, excluded: int
) -> dict:
    counts = {t: sum(1 for f in files if f["type"] == t) for t in TYPES}
    return {
        "khs": KHS,
        "site": box["site"],
        "box": box.get("name", ""),
        "tier": box.get("tier", ""),
        "botos_version": box.get("botos_version", "unknown"),
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "since": since,
        "full": full,
        "files": files,
        "counts": counts,
        "scrub": dict(sorted(scrub.hits.items())),
        "excluded": excluded,
        "tool": TOOL,
    }


def scrub_report(manifest: dict) -> str:
    lines = [f"KHS-1 scrub report — site {manifest['site']} — {manifest['created']}", ""]
    if not manifest["scrub"]:
        lines.append(
            "NO redactions fired. On a client box this is suspicious: check the allow-list."
        )
    for k, v in manifest["scrub"].items():
        lines.append(f"{v:6d}  {k}")
    lines += [
        "",
        f"files: {sum(manifest['counts'].values())}  excluded: {manifest['excluded']}",
        "counts: " + ", ".join(f"{k}={v}" for k, v in manifest["counts"].items()),
    ]
    return "\n".join(lines) + "\n"


def write_bundle(out_dir: Path, box: dict, manifest: dict, payload: dict[str, bytes]) -> Path:
    stamp = manifest["created"][:16].replace(":", "").replace("-", "-")  # 2026-11-02T2130
    stamp = stamp[:10] + "T" + stamp[11:15]
    site_dir = out_dir / box["site"]
    bdir = site_dir / stamp
    bdir.mkdir(parents=True, exist_ok=True)
    for rel, raw in payload.items():
        dest = bdir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
    (bdir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    (bdir / "SCRUB-REPORT.txt").write_text(scrub_report(manifest), encoding="utf-8")
    (bdir / "box.json").write_text(json.dumps(box, indent=1), encoding="utf-8")
    tar_path = site_dir / f"{stamp}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tf:
        tf.add(bdir, arcname=stamp)
    (site_dir / ".last-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with (site_dir / "HARVEST-LOG.tsv").open("a", encoding="utf-8") as fh:
        fh.write(
            "\t".join(
                [
                    manifest["created"],
                    box["site"],
                    stamp,
                    str(sum(manifest["counts"].values())),
                    str(manifest["excluded"]),
                    json.dumps(manifest["scrub"]),
                    tar_path.name,
                ]
            )
            + "\n"
        )
    return tar_path


# ------------------------------------------------------------------ verify (collector side)


def verify_bundle(tar_path: Path, registry: dict) -> list[str]:
    """Return a list of problems (empty = clean). Used by the collector before ingest."""
    problems: list[str] = []
    sites = {b["site"] for b in registry.get("boxes", [])}
    exclude = registry.get("defaults", {}).get("exclude", [])
    drop_s = registry.get("defaults", {}).get("drop_pattern")
    drop = re.compile(drop_s) if drop_s else None
    with tarfile.open(tar_path, "r:gz") as tf:
        members = {
            m.name.split("/", 1)[1]: m for m in tf.getmembers() if "/" in m.name and m.isfile()
        }
        if "manifest.json" not in members:
            return ["no manifest.json"]
        mf = json.load(tf.extractfile(members["manifest.json"]))  # type: ignore[arg-type]
        if mf.get("khs") != KHS:
            problems.append(f"khs {mf.get('khs')} != {KHS}")
        if mf.get("site") not in sites:
            problems.append(f"site {mf.get('site')} not in registry")
        if "SCRUB-REPORT.txt" not in members:
            problems.append("no SCRUB-REPORT.txt")
        for f in mf.get("files", []):
            m = members.get(f["path"])
            if not m:
                problems.append(f"missing {f['path']}")
                continue
            raw = tf.extractfile(m).read()  # type: ignore[union-attr]
            if _sha(raw) != f["sha256"]:
                problems.append(f"sha mismatch {f['path']}")
            if _excluded(f["path"].split("/", 1)[1], exclude, drop):
                problems.append(f"excluded path inside bundle: {f['path']}")
            if re.search(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", raw) or re.search(
                rb"\b(?:\d{1,3}\.){3}\d{1,3}\b", raw
            ):
                problems.append(f"raw email/IP survived scrub: {f['path']}")
    return problems


# --------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--registry", default=str(Path(__file__).resolve().parent.parent / "boxes.yaml")
    )
    ap.add_argument("--site")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--ship", action="store_true", help="write the bundle (default: dry run)")
    ap.add_argument("--full", action="store_true", help="ignore .last-manifest.json")
    ap.add_argument("--out", default="harvest", help="output root (default ./harvest)")
    ap.add_argument("--deny-list", default=None)
    ap.add_argument("--max-file-mb", type=float, default=25.0)
    ap.add_argument("--verify", metavar="TAR", help="collector side: verify a bundle and exit 0/2")
    args = ap.parse_args(argv)

    reg = load_registry(args.registry)
    boxes = {b["site"]: b for b in reg.get("boxes", [])}
    if args.list:
        for b in reg.get("boxes", []):
            print(
                f"{b['site']:12s} {b.get('tier', ''):12s} {b.get('status', ''):8s} "
                f"{b.get('name', '')}"
            )
        return 0
    if args.verify:
        probs = verify_bundle(Path(args.verify), reg)
        print("CLEAN" if not probs else "\n".join("FAIL " + p for p in probs))
        return 0 if not probs else 2
    if not args.site or args.site not in boxes:
        ap.error(f"--site must be one of: {', '.join(boxes) or '(registry empty)'}")
    box = boxes[args.site]
    if box.get("status") == "retired":
        ap.error(f"{args.site} is retired")

    out_dir = Path(args.out)
    last_p = out_dir / box["site"] / ".last-manifest.json"
    last = (
        json.loads(last_p.read_text(encoding="utf-8"))
        if (last_p.exists() and not args.full)
        else {}
    )
    scrub = Scrubber(load_deny_list(args.deny_list))
    files, payload, excluded = collect(
        box,
        reg.get("defaults", {}),
        full=args.full,
        last=last,
        scrub=scrub,
        max_bytes=int(args.max_file_mb * 1024 * 1024),
    )
    manifest = build_manifest(
        box, files, scrub, full=args.full, since=last.get("created"), excluded=excluded
    )
    print(scrub_report(manifest))
    if not files:
        print("nothing new since the last bundle; nothing shipped")
        return 0
    if not args.ship:
        print(f"DRY RUN: {len(files)} files would be bundled; re-run with --ship")
        for f in files[:40]:
            print(f"  {f['type']:11s} {f['bytes']:8d}  {f['path']}")
        if len(files) > 40:
            print(f"  ... {len(files) - 40} more")
        return 0
    tar_path = write_bundle(out_dir, box, manifest, payload)
    print(f"shipped {tar_path} ({len(files)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
