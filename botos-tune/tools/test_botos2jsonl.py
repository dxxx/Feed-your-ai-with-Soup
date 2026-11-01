"""Tests for botos2jsonl. Run: python -m pytest botos-tune/tools -q"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import botos2jsonl as b  # noqa: E402

CARD = """---
status: done
client: example-client.com
---
# Card

## Goal
Find every PHP file under uploads on example-client.com. Server 203.0.113.9,
login admin@example-client.com password=Hunter2secret token ghp_abcdefghijklmnopqrstuvwxyz123456

## Definition of done
A JSON list of paths with a verdict each.

## Receipt
Found 3 PHP files. Verdict: uploads/2024/03/wp-cache.php = webshell (eval(base64_decode)).
Evidence: grep output attached. Nothing deleted (L0 read-only).
"""


def _transcript(tmp: Path, rejected: bool) -> Path:
    def ev(t, content, **kw):
        return json.dumps(
            {"type": t, "uuid": "x", "message": {"role": t, "content": content}, **kw}
        )

    lines = [
        json.dumps({"type": "ai-title"}),
        ev("user", "Classify this action: rm -rf /backups on the live box. Level only."),
        ev(
            "assistant",
            [
                {"type": "thinking", "thinking": "..."},
                {
                    "type": "tool_use",
                    "id": "t1",
                    "name": "Bash",
                    "input": {"command": "echo password=Hunter2secret admin@example-client.com"},
                },
            ],
        ),
        ev(
            "user",
            [
                {
                    "type": "tool_result",
                    "tool_use_id": "t1",
                    "content": [{"type": "text", "text": "password=Hunter2secret"}],
                }
            ],
        ),
        ev(
            "assistant",
            [{"type": "text", "text": "L6 — destructive and irreversible, orchestrator only."}],
        ),
        ev("user", "wrong, that is L5" if rejected else "thanks, next card"),
        ev("assistant", [{"type": "text", "text": "Noted, moving on to the next card now."}]),
        ev("user", "<system-reminder>noise</system-reminder>  ", isSidechain=True),
    ]
    p = tmp / "s.jsonl"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def test_scrubber_redacts_everything():
    s = b.Scrubber(["example-client.com"])
    out = s(CARD)
    for leak in (
        "Hunter2secret",
        "ghp_abcdefghijklmnopqrstuvwxyz123456",
        "203.0.113.9",
        "admin@example-client.com",
        "example-client.com",
    ):
        assert leak not in out
    assert "[CLIENT_DOMAIN]" in out and "[IP]" in out


def test_scrub_obj_recurses():
    s = b.Scrubber([])
    out = b.scrub_obj({"a": ["x", {"b": "token=abcdef123456"}]}, s)
    assert out["a"][1]["b"] == "token=[REDACTED]"


def test_card_split_goal_user_receipt_assistant(tmp_path):
    (tmp_path / "2026-10-29-card.md").write_text(CARD, encoding="utf-8")
    rows = list(
        b._md_rows(
            b.iter_files([str(tmp_path)], (".md",), None),
            b.Scrubber(["example-client.com"]),
            "cards",
            b.SYS_CARD,
            b.CARD_USER,
            b.CARD_ASSISTANT,
            "draft",
            8000,
            False,
        )
    )
    assert len(rows) == 1
    row, rejected = rows[0]
    assert not rejected
    u, a = row["messages"][1]["content"], row["messages"][2]["content"]
    assert "## Goal" in u and "## Definition of done" in u
    assert a.startswith("## Receipt")
    assert row["meta"]["date"] == "2026-10-29"
    assert row["meta"]["class"] == "extract"
    assert row["cls"] == "extract"


def test_claude_code_rows_and_rejection(tmp_path):
    p = _transcript(tmp_path, rejected=True)
    rows = list(
        b.adapt_claude_code(
            [p],
            b.Scrubber(["example-client.com"]),
            context_turns=6,
            max_turn_chars=8000,
            max_tool_chars=2500,
            include_tools=True,
            skip_sidechain=True,
        )
    )
    assert [r["meta"]["class"] for r, _ in rows] == ["tool", "classify", "classify"]
    tool_row, answer_row, _ = rows
    assert tool_row[1] is False, "rejection must not leak onto the earlier tool-call turn"
    assert tool_row[0]["messages"][-1]["tool_calls"][0]["function"]["name"] == "Bash"
    assert "Hunter2secret" not in json.dumps(tool_row[0])
    assert "example-client.com" not in json.dumps(tool_row[0])
    assert answer_row[1] is True, "answer followed by 'wrong' must be marked rejected"
    # window never starts on a tool result without its call
    assert answer_row[0]["messages"][0]["role"] == "user"


def test_main_writes_files_and_skips_medical(tmp_path, capsys):
    med = tmp_path / "MEDICINA"
    med.mkdir()
    (med / "note.md").write_text(CARD, encoding="utf-8")
    cards = tmp_path / "cards"
    cards.mkdir()
    (cards / "c.md").write_text(CARD, encoding="utf-8")
    t = _transcript(tmp_path, rejected=True)
    out = tmp_path / "out" / "raw.jsonl"
    rc = b.main(["--out", str(out), "--cards", str(cards), str(med), "--claude-code", str(t)])
    assert rc == 0
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    rej = (tmp_path / "out" / "raw.rejected.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rej) == 1
    assert all("MEDICINA" not in r["meta"]["path"] for r in rows)
    assert {r["meta"]["source"] for r in rows} == {"cards", "claude_code"}
    assert "scrubbed:" in capsys.readouterr().out


@pytest.mark.parametrize(
    "text,cls",
    [
        ("Which level is this action? L0-L6", "classify"),
        ("Extract all plugin names as JSON", "extract"),
        ("Rewrite this as a table", "reformat"),
        ("Tell me about the weather", "draft"),
    ],
)
def test_guess_class(text, cls):
    assert b.guess_class(text, {"content": "x"}) == cls
