"""
Three-layer memory system for Sentinel:

Layer 1: Claude Code session (--resume) — full conversation history
Layer 2: CLAUDE.md — auto-read by Claude Code every call, contains persistent facts/identity
Layer 3: memory.json — backing store for facts, alerts, session tracking
"""

import json
import time
from pathlib import Path

MEMORY_PATH = Path("./data/memory.json")
CLAUDE_MD_PATH = Path("./CLAUDE.md")  # Updated by init()


def init(project_dir: str = "."):
    """Set CLAUDE.md path to the project directory so Claude Code reads it."""
    global CLAUDE_MD_PATH
    CLAUDE_MD_PATH = Path(project_dir) / "CLAUDE.md"
    _load()
    _write_claude_md()

_data: dict = {
    "session_id": None,
    "facts": {},
    "alerts": [],
}


def _load():
    global _data
    try:
        if MEMORY_PATH.exists():
            _data = json.loads(MEMORY_PATH.read_text())
    except (json.JSONDecodeError, IOError):
        pass


def _save():
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_PATH.write_text(json.dumps(_data, indent=2, default=str))
    _write_claude_md()


def _write_claude_md():
    """
    Write CLAUDE.md with current memory state.
    Claude Code auto-reads this file every invocation.
    This is how we persist identity + facts across session resets.
    """
    lines = [
        "# Sentinel Memory",
        "",
        "You are Sentinel, a personal AI daemon. This file contains your persistent memory.",
        "It is automatically updated — do not edit manually.",
        "",
    ]

    # Facts
    if _data["facts"]:
        lines.append("## Known Facts")
        lines.append("")
        for key, entry in _data["facts"].items():
            lines.append(f"- **{key}**: {entry['value']}")
        lines.append("")

    # Recent alerts
    recent = _data["alerts"][-10:] if _data["alerts"] else []
    if recent:
        lines.append("## Recent Alerts")
        lines.append("")
        for a in recent:
            ts = time.strftime("%m/%d %H:%M", time.localtime(a["timestamp"]))
            lines.append(f"- `{ts}` [{a['monitor']}] {a['message'][:150]}")
        lines.append("")

    CLAUDE_MD_PATH.write_text("\n".join(lines))


# ── Session ─────────────────────────────────────────────

def get_session_id() -> str | None:
    return _data.get("session_id")


def set_session_id(sid: str):
    _data["session_id"] = sid
    _save()


def clear_session():
    _data["session_id"] = None
    _save()


# ── Facts ───────────────────────────────────────────────

def set_fact(key: str, value: str):
    _data["facts"][key] = {"value": value, "updated": time.time()}
    _save()


def get_fact(key: str) -> str | None:
    entry = _data["facts"].get(key)
    return entry["value"] if entry else None


# ── Alerts ──────────────────────────────────────────────

def log_alert(monitor: str, message: str):
    _data["alerts"].append({
        "monitor": monitor,
        "message": message,
        "timestamp": time.time(),
    })
    _data["alerts"] = _data["alerts"][-200:]
    _save()


def get_recent_alerts(n: int = 10) -> list[dict]:
    return _data["alerts"][-n:]


# ── Status ──────────────────────────────────────────────

def get_status() -> dict:
    return {
        "session_id": _data.get("session_id"),
        "alert_count": len(_data.get("alerts", [])),
        "fact_count": len(_data.get("facts", {})),
    }


# Call memory.init(project_dir) from sentinel.py to initialize
