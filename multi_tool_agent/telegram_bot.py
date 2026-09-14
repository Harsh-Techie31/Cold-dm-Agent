"""Telegram polling bot front-end for the cold-apply agent.

Run it (from C:\\Users\\micro\\multi_tool_agent, the repo root):

    python -m multi_tool_agent.telegram_bot

No public URL / webhook / HTTPS needed - the bot long-polls Telegram.

Message protocol (from your phone):
  * Send the raw job blob            -> DRAFT only (builds the email, does not send)
  * Prefix the blob with  send:      -> actually sends the email
  * /start or /help                  -> usage

Only Telegram user ids listed in TELEGRAM_ALLOWED_USER_IDS may use the bot.
Everyone else gets their id echoed back (so you can learn yours) and nothing runs.
"""

import asyncio
import logging
import os
import traceback

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import config
from .agent import root_agent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("cold_apply.telegram")

APP_NAME = "cold_apply"
RUN_TIMEOUT_S = 240
TG_MAX = 4096

_session_service = InMemorySessionService()
_runner = Runner(app_name=APP_NAME, agent=root_agent, session_service=_session_service)
# Serialize agent runs: the pipeline toggles config.DRY_RUN as a process global,
# so two concurrent runs would race on it.
_run_lock = asyncio.Lock()


def _allowed_ids() -> set[int]:
    raw = os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "")
    out = set()
    for tok in raw.replace(";", ",").split(","):
        tok = tok.strip()
        if tok.isdigit():
            out.add(int(tok))
    return out


async def _run_blob(blob: str, *, send_for_real: bool) -> str:
    """Runs the full agent pipeline once and returns its final text."""
    async with _run_lock:
        prev = config.DRY_RUN
        config.DRY_RUN = not send_for_real
        try:
            session = await _session_service.create_session(
                app_name=APP_NAME, user_id="telegram"
            )
            message = types.Content(role="user", parts=[types.Part(text=blob)])
            parts: list[str] = []
            async for event in _runner.run_async(
                user_id="telegram",
                session_id=session.id,
                new_message=message,
            ):
                if event.is_final_response() and event.content and event.content.parts:
                    for p in event.content.parts:
                        if getattr(p, "text", None):
                            parts.append(p.text)
            return "\n".join(parts).strip() or "(agent returned no text)"
        finally:
            config.DRY_RUN = prev


async def _reply_chunked(update: Update, text: str) -> None:
    for i in range(0, len(text), TG_MAX):
        await update.message.reply_text(text[i : i + TG_MAX])


async def cmd_start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Cold-apply bot.\n\n"
        "\u2022 Paste a job blob -> I DRAFT the email (nothing is sent).\n"
        "\u2022 Start your message with `send:` -> I actually send it.\n"
        "\u2022 If the blob has no email, include the company name and I'll try "
        "to find one.\n\n"
        "One application per message.",
        parse_mode=None,
    )


async def on_message(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    uid = user.id if user else None
    allowed = _allowed_ids()

    if not allowed:
        await update.message.reply_text(
            f"No allow-list configured. Set TELEGRAM_ALLOWED_USER_IDS in .env. "
            f"Your Telegram id is: {uid}"
        )
        return
    if uid not in allowed:
        log.warning("rejected message from unauthorized id=%s", uid)
        await update.message.reply_text(f"Not authorized. Your id: {uid}")
        return

    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("Send the job blob as text.")
        return

    send_for_real = False
    if text[:5].lower() == "send:":
        send_for_real = True
        text = text[5:].strip()

    if len(text) < 40:
        await update.message.reply_text(
            "That looks too short to be a job posting. Paste the full blob."
        )
        return

    mode = "SEND" if send_for_real else "DRAFT"
    await update.message.reply_text(f"\u23f3 Running ({mode})\u2026 this takes ~30-90s.")
    await _ctx.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)

    try:
        result = await asyncio.wait_for(
            _run_blob(text, send_for_real=send_for_real), timeout=RUN_TIMEOUT_S
        )
    except asyncio.TimeoutError:
        await update.message.reply_text(
            f"Timed out after {RUN_TIMEOUT_S}s. Try again or simplify the blob."
        )
        return
    except Exception as e:  # noqa: BLE001 - surface anything to the operator
        log.exception("agent run failed")
        await _reply_chunked(
            update, "Run failed:\n" + "".join(traceback.format_exception_only(type(e), e))
        )
        return

    header = "\u2705 Sent.\n\n" if send_for_real else "\U0001f4dd Draft (not sent). Resend with `send:` to send.\n\n"
    await _reply_chunked(update, header + result)


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in multi_tool_agent/.env")

    ids = _allowed_ids()
    log.info("allow-list: %s", sorted(ids) or "EMPTY (bot will refuse to run blobs)")
    log.info("model: %s", getattr(config.MODEL, "model", config.MODEL))
    log.info("default dry-run: %s", config.DRY_RUN)

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    log.info("bot up; polling. Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
