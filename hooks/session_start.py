"""Supply the bundled planning rule to a new Codex session."""

import json
from pathlib import Path


if __name__ == "__main__":
    rule = Path(__file__).resolve().parents[1] / "planning.md"
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": rule.read_text(encoding="utf-8"),
        },
    }))
