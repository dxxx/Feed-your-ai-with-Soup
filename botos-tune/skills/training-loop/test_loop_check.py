"""Tests for loop-check.py.

Run: python -m pytest botos-tune/skills/training-loop -q -o addopts=''
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).parent
_spec = importlib.util.spec_from_file_location("loop_check", HERE / "loop-check.py")
lc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lc)  # type: ignore[union-attr]


def summary(extract: float, n: int = 60, level: float = 1.0, fail: float = 0.93) -> dict:
    # same shape as the Bot-OS eval kit's *.summary.json
    return {"suites": {
        "extract": {"n": n, "pass_first": extract},
        "classify": {"action_level": {"n": 18, "accuracy": level},
                     "failure_class": {"n": 14, "accuracy": fail}},
    }}


def write(tmp: Path, name: str, obj) -> str:
    p = tmp / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return str(p)


def files(tmp: Path, cand: dict, base: dict | None = None):
    gate = json.loads((HERE / "gate.template.json").read_text(encoding="utf-8"))
    return (write(tmp, "gate.json", gate), write(tmp, "base.json", base or summary(0.80)),
            write(tmp, "cand.json", cand), write(tmp, "d.json", {"forgetting": {"verdict": "OK"}}))


ALL_RC = ["--adapter-check-rc", "0", "--ship-rc", "0", "--canary-rc", "0"]


def test_keep_when_everything_passes(tmp_path, capsys):
    g, b, c, d = files(tmp_path, summary(0.92))
    rc = lc.main(["--gate", g, "--base", b, "--cand", c, "--diagnose", d, *ALL_RC,
                  "--ledger", str(tmp_path / "a.tsv"), "--unit", "proxy", "--change", "x"])
    out = capsys.readouterr().out
    assert rc == 0 and "DECISION: KEEP" in out
    lines = (tmp_path / "a.tsv").read_text().splitlines()
    assert lines[0].startswith("time\tunit") and "\tKEEP\t" in lines[1]


def test_revert_below_min_and_below_delta(tmp_path, capsys):
    g, b, c, d = files(tmp_path, summary(0.70))  # v0.1-like: below base
    assert lc.main(["--gate", g, "--base", b, "--cand", c, "--diagnose", d, *ALL_RC]) == 2
    out = capsys.readouterr().out
    assert "extract" in out and "FAIL" in out and "DECISION: REVERT" in out
    # above min but not +10 over base
    g, b, c, d = files(tmp_path, summary(0.92), base=summary(0.88))
    assert lc.main(["--gate", g, "--base", b, "--cand", c, "--diagnose", d, *ALL_RC]) == 2
    assert "delta" in capsys.readouterr().out


def test_small_n_is_inconclusive(tmp_path, capsys):
    g, b, c, d = files(tmp_path, summary(1.0, n=10))  # R4: n=10 cannot pass
    assert lc.main(["--gate", g, "--base", b, "--cand", c, "--diagnose", d, *ALL_RC]) == 2
    assert "INCONCLUSIVE" in capsys.readouterr().out


def test_missing_rc_fails_and_wrong_rc_fails(tmp_path, capsys):
    g, b, c, d = files(tmp_path, summary(0.95))
    assert lc.main(["--gate", g, "--base", b, "--cand", c, "--diagnose", d]) == 2
    assert "not supplied" in capsys.readouterr().out
    assert lc.main(["--gate", g, "--base", b, "--cand", c, "--diagnose", d,
                    "--adapter-check-rc", "2", "--ship-rc", "0", "--canary-rc", "0"]) == 2
    assert "rc 2 != 0" in capsys.readouterr().out  # R2: adapter not attached


def test_diagnose_major_fails(tmp_path, capsys):
    g, b, c, _ = files(tmp_path, summary(0.95))
    d = write(tmp_path, "dm.json", {"checks": [{"name": "format", "verdict": "MAJOR"}]})
    assert lc.main(["--gate", g, "--base", b, "--cand", c, "--diagnose", d, *ALL_RC]) == 2
    assert "MAJOR" in capsys.readouterr().out


def test_broken_check_exits_1(tmp_path, capsys):
    g, b, _, d = files(tmp_path, summary(0.95))
    bad = write(tmp_path, "bad.json", {"suites": {}})
    assert lc.main(["--gate", g, "--base", b, "--cand", bad, "--diagnose", d, *ALL_RC]) == 1
    assert lc.main(["--gate", g, "--base", b, "--cand", str(tmp_path / "nope.json")]) == 1


def test_stop_after_max_attempts(tmp_path, capsys):
    g, b, c, d = files(tmp_path, summary(0.5))
    lc.main(["--gate", g, "--base", b, "--cand", c, "--diagnose", d, *ALL_RC,
             "--unit", "proxy", "--attempt", "3"])
    assert "STOP: proxy failed 3/3" in capsys.readouterr().out
