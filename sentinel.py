#!/usr/bin/env python3
"""
Sentinel — A lean personal AI daemon.

Claude Code CLI (your subscription) + Telegram + Heartbeat monitoring.
Three-layer memory: session (--resume) + CLAUDE.md (facts) + memory.json (backing store).

Usage:
    python sentinel.py
    python sentinel.py --config custom.yaml

Prerequisites:
    - Claude Code installed and authenticated (`claude login`)
    - ANTHROPIC_API_KEY must NOT be set (or Claude Code uses API billing instead of subscription)
    - Telegram bot token from @BotFather
"""

import asyncio
import logging
import os
import re
import signal
import sys
from pathlib import Path

import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sentinel")


def load_config(path: str = "config.yaml") -> dict:
    if not Path(path).exists():
        logger.error(f"Config not found: {path}")
        sys.exit(1)

    raw = Path(path).read_text()

    # Substitute ${ENV_VAR}
    raw = re.sub(
        r"\$\{(\w+)\}",
        lambda m: os.environ.get(m.group(1), ""),
        raw,
    )
    config = yaml.safe_load(raw)

    # Validate
    token = config.get("telegram", {}).get("bot_token", "")
    if not token or token == "":
        logger.error("TELEGRAM_BOT_TOKEN not set. Get one from @BotFather.")
        sys.exit(1)

    # Warn if API key is set (it'll override subscription billing)
    if os.environ.get("ANTHROPIC_API_KEY"):
        logger.warning(
            "⚠️  ANTHROPIC_API_KEY is set — Claude Code will use API billing "
            "instead of your subscription. Unset it to use your Pro/Max plan: "
            "unset ANTHROPIC_API_KEY"
        )

    return config


async def main():
    config_path = "config.yaml"
    if "--config" in sys.argv:
        idx = sys.argv.index("--config")
        if idx + 1 < len(sys.argv):
            config_path = sys.argv[idx + 1]

    config = load_config(config_path)

    # Import after config is loaded
    import agent
    import bot
    import heartbeat
    import memory

    logger.info("══════════════════════════════════════")
    logger.info("  🤖 Sentinel starting up...")
    logger.info("══════════════════════════════════════")

    project_dir = config.get("claude", {}).get("project_dir", ".")
    logger.info(f"  Project: {project_dir}")

    memory.init(project_dir)
    agent.init(config)
    bot.init(config)
    heartbeat.init(bot.send_to_operator)

    # Graceful shutdown
    shutdown = asyncio.Event()

    def handle_signal():
        logger.info("Shutdown signal received")
        shutdown.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal)

    try:
        await bot.start()
        heartbeat.start(config)

        logger.info("══════════════════════════════════════")
        logger.info("  Sentinel is running. Ctrl+C to stop.")
        logger.info("══════════════════════════════════════")

        try:
            await bot.send_to_operator("🤖 Sentinel is online and monitoring.")
        except Exception:
            pass

        await shutdown.wait()

    except Exception as e:
        logger.error(f"Fatal: {e}", exc_info=True)
    finally:
        heartbeat.stop()
        await bot.stop()
        logger.info("Sentinel stopped. Goodbye.")


if __name__ == "__main__":
    asyncio.run(main())
