"""
Heartbeat loop — runs monitors on interval, alerts via Telegram.
"""

import asyncio
import logging

import memory
import monitors
from agent import quick_query

logger = logging.getLogger("sentinel.heartbeat")

_running = False
_task: asyncio.Task | None = None
_send_fn = None


def init(send_fn):
    global _send_fn
    _send_fn = send_fn


async def _cycle(config: dict):
    alerts = await monitors.run_all(config.get("monitors", []))
    if not alerts:
        return

    for alert in alerts:
        memory.log_alert("heartbeat", alert)
        logger.warning(f"Alert: {alert}")

    # Have Claude compose a concise message
    try:
        assessment = await quick_query(
            f"These monitoring alerts just fired:\n\n"
            + "\n".join(alerts)
            + "\n\nCompose a concise Telegram alert. Be actionable."
        )
        if assessment and _send_fn:
            await _send_fn(f"🔔 Sentinel Alert\n\n{assessment}")
    except Exception:
        if _send_fn:
            await _send_fn(f"🔔 Sentinel Alert\n\n" + "\n".join(alerts))


async def _loop(config: dict):
    interval = config.get("heartbeat", {}).get("interval_seconds", 300)
    logger.info(f"Heartbeat started (every {interval}s)")

    while _running:
        try:
            await _cycle(config)
        except Exception as e:
            logger.error(f"Heartbeat error: {e}", exc_info=True)
        await asyncio.sleep(interval)


def start(config: dict):
    global _running, _task

    hb = config.get("heartbeat", {})
    if not hb.get("enabled", True):
        logger.info("Heartbeat: disabled")
        return

    enabled = [m for m in config.get("monitors", []) if m.get("enabled")]
    if not enabled:
        logger.info("Heartbeat: no monitors enabled")
        return

    _running = True
    _task = asyncio.ensure_future(_loop(config))
    logger.info(f"Heartbeat: {len(enabled)} monitor(s) active")


def stop():
    global _running
    _running = False
    if _task:
        _task.cancel()
