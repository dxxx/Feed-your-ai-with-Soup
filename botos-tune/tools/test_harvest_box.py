"""Tests for harvest-box.py (KHS-1). Run: python -m pytest botos-tune/tools -q -o addopts=''"""

from __future__ import annotations

import importlib.util
import json
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
_spec = importlib.util.spec_from_file_location("harvest_box", HERE / "harvest-box.py")
hb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hb)  # type: ignore[union-attr]

REG = """\
defaults:
  include:
    episodic:   [done, "projects/*/done", decisions]
    semantic:   [vault/hot.md]
    procedural: [agency/gotcha-outbox]
    telemetry:  [agency/task-classes.md]
  exclude: [".secrets", "*.key", "*.sql", evidence, ".git"]
  drop_pattern: "(?i)MEDICINA|\\\\.key[\\\\\\\\/]"
  transcripts_glob: "*.jsonl"

boxes:
  - site: s-test
    name: test box   # comment after value
    tier: client-copy
    status: active
    root: '{root}'
    claude_projects: ['{cp}']
    transport: local
    cadence: weekly
  - site: s-old
    name: retired one
    tier: snapshot
    status: retired
    root: '/nowhere'
    claude_projects: []
"""


def _box(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "box"
    (root / "done").mkdir(parents=True)
    (root / "done" / "2026-10-29-card.md").write_text(
        "## Goal\nClean client.example.com, server 203.0.113.9, mail admin@client.example.com\n"
        "## Receipt\ndone, password=Hunter2secret rotated\n",
        encoding="utf-8",
    )
    (root / "projects" / "siro" / "done").mkdir(parents=True)
    (root / "projects" / "siro" / "done" / "x.md").write_text(
        "## Goal\na\n## Receipt\nb\n", encoding="utf-8"
    )
    (root / "projects" / "siro" / "evidence").mkdir()
    (root / "projects" / "siro" / "evidence" / "dump.sql").write_text(
        "secret rows", encoding="utf-8"
    )
    (root / "vault").mkdir()
    (root / "vault" / "hot.md").write_text("fact: 1\n", encoding="utf-8")
    (root / ".secrets").mkdir()
    (root / ".secrets" / "x.env").write_text("TOKEN=abc\n", encoding="utf-8")
    (root / "agency").mkdir()
    (root / "agency" / "task-classes.md").write_text("| extract | L0 |\n", encoding="utf-8")
    cp = tmp_path / "claude-projects"
    cp.mkdir()
    (cp / "s1.jsonl").write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": "ip 198.51.100.7"}})
        + "\n",
        encoding="utf-8",
    )
    reg = tmp_path / "boxes.yaml"
    reg.write_text(
        REG.format(root=str(root).replace("\\", "/"), cp=str(cp).replace("\\", "/")),
        encoding="utf-8",
    )
    return root, cp, reg


def test_registry_parser(tmp_path):
    _, _, reg = _box(tmp_path)
    r = hb.load_registry(str(reg))
    assert r["defaults"]["include"]["episodic"] == ["done", "projects/*/done", "decisions"]
    assert r["defaults"]["exclude"][0] == ".secrets"
    assert [b["site"] for b in r["boxes"]] == ["s-test", "s-old"]
    assert r["boxes"][0]["name"] == "test box"
    assert r["boxes"][0]["cadence"] == "weekly"


def test_dry_run_then_ship_then_incremental(tmp_path, capsys):
    root, _, reg = _box(tmp_path)
    out = tmp_path / "harvest"
    assert hb.main(["--registry", str(reg), "--site", "s-test", "--out", str(out)]) == 0
    assert "DRY RUN" in capsys.readouterr().out
    assert not (out / "s-test").exists()

    assert hb.main(["--registry", str(reg), "--site", "s-test", "--out", str(out), "--ship"]) == 0
    tars = list((out / "s-test").glob("*.tar.gz"))
    assert len(tars) == 1
    with tarfile.open(tars[0]) as tf:
        names = [m.name.split("/", 1)[1] for m in tf.getmembers() if "/" in m.name]
        blob = b"".join(tf.extractfile(m).read() for m in tf.getmembers() if m.isfile())
    assert "manifest.json" in names and "SCRUB-REPORT.txt" in names
    assert any(n.startswith("episodic/done/2026-10-29-card.md") for n in names)
    assert any(n.startswith("episodic/projects/siro/done/x.md") for n in names)
    assert any(n.startswith("transcripts/claude-projects/s1.jsonl") for n in names)
    assert not any("evidence" in n or ".secrets" in n or n.endswith(".sql") for n in names)
    for leak in (b"203.0.113.9", b"admin@client", b"Hunter2secret", b"198.51.100.7"):
        assert leak not in blob
    assert (out / "s-test" / "HARVEST-LOG.tsv").read_text().count("\n") == 1

    # incremental: nothing changed -> nothing shipped
    assert hb.main(["--registry", str(reg), "--site", "s-test", "--out", str(out), "--ship"]) == 0
    assert "nothing new" in capsys.readouterr().out
    # change one file -> only it ships
    (root / "vault" / "hot.md").write_text("fact: 2\n", encoding="utf-8")
    assert hb.main(["--registry", str(reg), "--site", "s-test", "--out", str(out), "--ship"]) == 0
    mf = json.loads((out / "s-test" / ".last-manifest.json").read_text())
    assert [f["path"] for f in mf["files"]] == ["semantic/vault/hot.md"]
    assert mf["since"] is not None and mf["full"] is False


def test_verify_clean_and_tampered(tmp_path):
    _, _, reg = _box(tmp_path)
    out = tmp_path / "harvest"
    hb.main(["--registry", str(reg), "--site", "s-test", "--out", str(out), "--ship"])
    tar = next((out / "s-test").glob("*.tar.gz"))
    r = hb.load_registry(str(reg))
    assert hb.verify_bundle(tar, r) == []
    # tamper: rebuild the tar with a changed file
    bdir = next(p for p in (out / "s-test").iterdir() if p.is_dir())
    (bdir / "semantic" / "vault" / "hot.md").write_text(
        "fact: tampered admin@x.com\n", encoding="utf-8"
    )
    with tarfile.open(tar, "w:gz") as tf:
        tf.add(bdir, arcname=bdir.name)
    probs = hb.verify_bundle(tar, r)
    assert any("sha mismatch" in p for p in probs)
    assert any("raw email/IP" in p for p in probs)


def test_unknown_or_retired_site_refused(tmp_path):
    _, _, reg = _box(tmp_path)
    import pytest

    with pytest.raises(SystemExit):
        hb.main(["--registry", str(reg), "--site", "s-nope"])
    with pytest.raises(SystemExit):
        hb.main(["--registry", str(reg), "--site", "s-old"])
