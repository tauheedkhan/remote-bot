"""
Telegram bot — bidirectional interface to Claude Code.
"""

import logging
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters,
)

import agent
import memory

logger = logging.getLogger("sentinel.bot")

_app: Application | None = None
_allowed_users: set[int] = set()


def _authorized(user_id: int) -> bool:
    return not _allowed_users or user_id in _allowed_users


def _split(text: str, max_len: int = 4000) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


async def _send_safe(chat_id: int, text: str):
    for chunk in _split(text):
        try:
            await _app.bot.send_message(chat_id, chunk, parse_mode="Markdown")
        except Exception:
            await _app.bot.send_message(chat_id, chunk)


# ── Handlers ────────────────────────────────────────────

async def _on_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update.effective_user.id):
        return await update.message.reply_text("⛔ Unauthorized.")
    await update.message.reply_text(
        f"🤖 Sentinel online.\n\n"
        f"Your user ID: `{update.effective_user.id}`\n\n"
        "Commands:\n/status — Session + memory info\n"
        "/alerts — Recent alerts\n/forget — Reset session\n"
        "/remember key=value — Store a fact\n\n"
        "Or just message me anything.",
        parse_mode="Markdown",
    )


async def _on_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update.effective_user.id):
        return
    s = memory.get_status()
    alerts = memory.get_recent_alerts(3)
    msg = (
        f"🤖 *Sentinel Status*\n"
        f"Session: `{s['session_id'][:12] + '...' if s['session_id'] else 'none'}`\n"
        f"Facts: {s['fact_count']} | Alerts: {s['alert_count']}"
    )
    if alerts:
        msg += "\n\nRecent:"
        for a in alerts:
            msg += f"\n• {a['message'][:100]}"
    await _send_safe(update.effective_chat.id, msg)


async def _on_alerts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update.effective_user.id):
        return
    alerts = memory.get_recent_alerts(20)
    if not alerts:
        return await update.message.reply_text("No alerts.")
    import time
    msg = "📋 *Recent Alerts*\n"
    for a in alerts:
        ts = time.strftime("%m/%d %H:%M", time.localtime(a["timestamp"]))
        msg += f"\n`{ts}` {a['message'][:150]}"
    await _send_safe(update.effective_chat.id, msg)


async def _on_forget(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update.effective_user.id):
        return
    agent.reset_session()
    await update.message.reply_text(
        "🧹 Session reset. Fresh context next message.\n"
        "Persistent memory (facts, alerts) preserved in CLAUDE.md."
    )


async def _on_remember(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update.effective_user.id):
        return
    text = update.message.text.replace("/remember", "", 1).strip()
    if "=" not in text:
        return await update.message.reply_text("Usage: /remember key=value")
    key, value = text.split("=", 1)
    memory.set_fact(key.strip(), value.strip())
    await update.message.reply_text(f"✅ Stored: {key.strip()} = {value.strip()}")


async def _on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update.effective_user.id):
        return await update.message.reply_text("⛔ Unauthorized.")

    text = update.message.text
    logger.info(f"[msg] {update.effective_user.id}: {text[:80]}")

    await update.message.chat.send_action("typing")

    # Keep typing alive for long responses
    typing_task = None

    async def keep_typing():
        while True:
            await update.message.chat.send_action("typing")
            await __import__("asyncio").sleep(4)

    typing_task = __import__("asyncio").get_event_loop().create_task(keep_typing())

    try:
        response = await agent.chat(text)
        typing_task.cancel()
        await _send_safe(update.effective_chat.id, response)
    except Exception as e:
        if typing_task:
            typing_task.cancel()
        logger.error(f"Bot error: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Error: {str(e)[:300]}")


# ── Lifecycle ───────────────────────────────────────────

async def send_to_operator(text: str):
    """Proactive outbound message."""
    if not _app or not _allowed_users:
        return
    target = next(iter(_allowed_users))
    await _send_safe(target, text)


def init(config: dict):
    global _app, _allowed_users

    _allowed_users = set(
        uid for uid in config["telegram"].get("allowed_users", [])
        if isinstance(uid, int) and uid > 0
    )

    _app = Application.builder().token(config["telegram"]["bot_token"]).build()
    _app.add_handler(CommandHandler("start", _on_start))
    _app.add_handler(CommandHandler("status", _on_status))
    _app.add_handler(CommandHandler("alerts", _on_alerts))
    _app.add_handler(CommandHandler("forget", _on_forget))
    _app.add_handler(CommandHandler("remember", _on_remember))
    _app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _on_message))


async def start():
    await _app.initialize()
    await _app.start()
    await _app.updater.start_polling(drop_pending_updates=True)
    logger.info("Telegram bot: started")


async def stop():
    if _app:
        await _app.updater.stop()
        await _app.stop()
        await _app.shutdown()
