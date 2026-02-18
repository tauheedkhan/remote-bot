"""
Claude Code CLI agent with persistent sessions.

Uses:
  - `claude -p --output-format json` for structured responses
  - `--resume {session_id}` for conversation continuity
  - `--append-system-prompt` for Sentinel identity
  - `--allowedTools` for auto-approved tools in headless mode
  - CLAUDE.md (auto-read by Claude Code) for persistent memory across session resets

Auth: Uses your Claude Pro/Max subscription (OAuth). No API key needed.
      Make sure ANTHROPIC_API_KEY is NOT set, or Claude Code will use it instead.
"""

import asyncio
import json
import logging
import subprocess

import memory

logger = logging.getLogger("sentinel.agent")

_config: dict = {}


def init(config: dict):
    global _config
    _config = config


def _build_cmd(prompt: str, use_session: bool = True, max_turns: int | None = None) -> list[str]:
    """Build the claude CLI command."""
    cfg = _config.get("claude", {})

    cmd = ["claude", "-p"]

    # Output format: JSON so we can parse session_id
    cmd.extend(["--output-format", "json"])

    # System prompt (append, don't replace — keeps built-in tools working)
    system_prompt = cfg.get("append_system_prompt", "")
    if system_prompt:
        cmd.extend(["--append-system-prompt", system_prompt.strip()])

    # Auto-approve tools (no one to click "approve" in headless mode)
    allowed_tools = cfg.get("allowed_tools", [])
    if allowed_tools:
        cmd.extend(["--allowedTools", ",".join(allowed_tools)])

    # Max turns
    turns = max_turns or cfg.get("max_turns", 25)
    cmd.extend(["--max-turns", str(turns)])

    # Session resume
    if use_session:
        session_id = memory.get_session_id()
        if session_id:
            cmd.extend(["--resume", session_id])

    # The actual prompt
    cmd.append(prompt)

    return cmd


def _parse_response(raw_output: str) -> tuple[str, str | None]:
    """
    Parse JSON output from claude -p --output-format json.
    Returns (result_text, session_id).
    """
    try:
        data = json.loads(raw_output)
        result = data.get("result", "")
        session_id = data.get("session_id")
        return result, session_id
    except json.JSONDecodeError:
        # Might be stream-json (newline-delimited) or plain text fallback
        # Try to find the last complete JSON object
        lines = raw_output.strip().splitlines()
        for line in reversed(lines):
            try:
                data = json.loads(line)
                if "result" in data:
                    return data.get("result", ""), data.get("session_id")
            except json.JSONDecodeError:
                continue
        # Give up parsing, return raw
        return raw_output.strip(), None


async def chat(user_message: str) -> str:
    """
    Send a message through Claude Code CLI with session persistence.
    Returns Claude's response text.
    """
    cfg = _config.get("claude", {})
    timeout = cfg.get("timeout", 120)

    cmd = _build_cmd(user_message, use_session=True)
    logger.info(f"Claude call: {user_message[:80]}...")
    logger.debug(f"CMD: {' '.join(cmd[:6])}...")

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=_config.get("claude", {}).get("project_dir", "."),
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            logger.error(f"Claude Code error (exit {result.returncode}): {stderr[:300]}")

            # Session might be stale — retry without it
            session_id = memory.get_session_id()
            if session_id and ("session" in stderr.lower() or "prompt too long" in stderr.lower()):
                logger.warning("Session appears stale, retrying fresh...")
                memory.clear_session()
                return await chat(user_message)

            return f"❌ Claude Code error: {stderr[:500]}"

        response_text, session_id = _parse_response(result.stdout)

        # Persist session for next call
        if session_id:
            memory.set_session_id(session_id)
            logger.info(f"Session: {session_id[:12]}...")

        logger.info(f"Response: {response_text[:100]}...")
        return response_text or "(No response)"

    except subprocess.TimeoutExpired:
        return "⏰ Claude Code timed out. Try a simpler request."
    except FileNotFoundError:
        return (
            "❌ `claude` not found. Install Claude Code:\n"
            "https://code.claude.com/docs/en/setup\n"
            "Then run `claude login`"
        )
    except Exception as e:
        logger.error(f"Agent error: {e}", exc_info=True)
        return f"❌ Error: {e}"


async def quick_query(prompt: str) -> str:
    """
    One-shot query without session context. Used for alert assessment.
    No tools, single turn, minimal cost.
    """
    cmd = ["claude", "-p", "--output-format", "text", "--max-turns", "1"]

    # No allowed tools for quick queries
    append = _config.get("claude", {}).get("append_system_prompt", "")
    if append:
        cmd.extend(["--append-system-prompt", append.strip()])

    cmd.append(prompt)

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=_config.get("claude", {}).get("project_dir", "."),
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception as e:
        logger.error(f"Quick query failed: {e}")
        return ""


def reset_session():
    """Clear session — next message starts fresh (but CLAUDE.md memory persists)."""
    memory.clear_session()
