"""FastAPI webhook front-end for the cold-apply agent - built for Render.

Local/offline use (PC, Pi, phone): run telegram_bot.py instead (long-polling,
no server, no public URL). Use THIS file only on a host that gives you a
public HTTPS URL and can sleep-on-idle, like Render's free web service.

Flow per message:
  Telegram --POST /<TELEGRAM_WEBHOOK_PATH>--> this app
    -> verify X-Telegram-Bot-Api-Secret-Token
    -> ACK 200 immediately (Telegram expects a fast reply)
    -> run the agent pipeline in the background
    -> deliver the result via bot.send_message (a separate outbound call)

On startup the app registers its own webhook with Telegram using Render's
RENDER_EXTERNAL_URL (auto-set by Render) or a manually-set PUBLIC_URL, so a
plain `git push` -> deploy is enough; no manual setWebhook step.

Run locally for testing:
    uvicorn multi_tool_agent.webhook_app:app --reload --port 8000
Then (optional) expose it with a tunnel and set PUBLIC_URL to that tunnel URL
before startup if you want to test real Telegram delivery.
"""

import asyncio
import logging
import os
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from telegram import Bot, Update

from . import config
from .agent import root_agent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("cold_apply.webhook")

APP_NAME = "cold_apply"
RUN_TIMEOUT_S = 240
TG_MAX = 4096

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
SECRET_TOKEN = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
WEBHOOK_PATH = os.environ.get("TELEGRAM_WEBHOOK_PATH", "telegram-webhook").strip("/")

if not TOKEN:
    raise RuntimeError("Set TELEGRAM_BOT_TOKEN in the environment.")

bot = Bot(token=TOKEN)
_session_service = InMemorySessionService()
_runner = Runner(app_name=APP_NAME, agent=root_agent, session_service=_session_service)
# Serialize agent runs: the pipeline toggles config.DRY_RUN as a process
# global, so two concurrent runs would race on it.
_run_lock = asyncio.Lock()


def _allowed_ids() -> set[int]:
    raw = os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "")
    out = set()
    for tok in raw.replace(";", ",").split(","):
        tok = tok.strip()
        if tok.isdigit():
            out.add(int(tok))
    return out


async def _register_webhook() -> None:
    public_url = (
        os.environ.get("PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL") or ""
    ).rstrip("/")
    if not public_url:
        log.warning(
            "No public URL (PUBLIC_URL / RENDER_EXTERNAL_URL unset) - "
            "webhook NOT registered. Set one, or call setWebhook manually."
        )
        return
    url = f"{public_url}/{WEBHOOK_PATH}"
    ok = await bot.set_webhook(
        url=url,
        secret_token=SECRET_TOKEN or None,
        drop_pending_updates=False,
        allowed_updates=["message"],
    )
    log.info("setWebhook(%s) -> %s", url, ok)
    if not SECRET_TOKEN:
        log.warning(
            "TELEGRAM_WEBHOOK_SECRET is unset - anyone who finds this URL can "
            "POST fake updates. Set it (any random string, same value in "
            "Telegram and here)."
        )


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    await _register_webhook()
    yield


app = FastAPI(lifespan=_lifespan)


@app.get("/health")
async def health() -> PlainTextResponse:
    """Hit this from an external pinger (cron-job.org / UptimeRobot) to keep
    Render's free tier from sleeping, if you don't want to rely on cold starts."""
    return PlainTextResponse("ok")


@app.get("/")
async def root() -> PlainTextResponse:
    return PlainTextResponse("cold_apply_agent webhook is up")


@app.post("/" + WEBHOOK_PATH)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> PlainTextResponse:
    if SECRET_TOKEN and x_telegram_bot_api_secret_token != SECRET_TOKEN:
        raise HTTPException(status_code=401, detail="bad secret token")

    data = await request.json()
    update = Update.de_json(data, bot)

    if update and update.message and update.message.text:
        # Ack fast; do the slow work after we've already returned 200.
        asyncio.create_task(_handle_message(update))
    return PlainTextResponse("ok")


async def _run_blob(blob: str, *, send_for_real: bool) -> str:
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


async def _reply_chunked(chat_id: int, text: str) -> None:
    for i in range(0, len(text), TG_MAX):
        await bot.send_message(chat_id=chat_id, text=text[i : i + TG_MAX])


async def _handle_message(update: Update) -> None:
    msg = update.message
    user = msg.from_user
    uid = user.id if user else None
    chat_id = msg.chat_id
    allowed = _allowed_ids()

    if not allowed:
        await bot.send_message(
            chat_id=chat_id,
            text=f"No allow-list configured. Your Telegram id: {uid}",
        )
        return
    if uid not in allowed:
        log.warning("rejected message from unauthorized id=%s", uid)
        await bot.send_message(chat_id=chat_id, text=f"Not authorized. Your id: {uid}")
        return

    text = (msg.text or "").strip()
    if text in ("/start", "/help"):
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "Cold-apply bot (webhook / Render).\n\n"
                "• Paste a job blob -> I DRAFT the email (nothing sent).\n"
                "• Start your message with `send:` -> I actually send it.\n\n"
                "First message after a while may be slow (cold start)."
            ),
        )
        return

    send_for_real = False
    if text[:5].lower() == "send:":
        send_for_real = True
        text = text[5:].strip()

    if len(text) < 40:
        await bot.send_message(
            chat_id=chat_id,
            text="That looks too short to be a job posting. Paste the full blob.",
        )
        return

    mode = "SEND" if send_for_real else "DRAFT"
    await bot.send_message(
        chat_id=chat_id,
        text=f"⏳ Running ({mode})… usually 30-90s.",
    )

    try:
        result = await asyncio.wait_for(
            _run_blob(text, send_for_real=send_for_real), timeout=RUN_TIMEOUT_S
        )
    except asyncio.TimeoutError:
        await bot.send_message(
            chat_id=chat_id,
            text=f"Timed out after {RUN_TIMEOUT_S}s. Try again or simplify the blob.",
        )
        return
    except Exception as e:  # noqa: BLE001 - surface anything to the operator
        log.exception("agent run failed")
        await _reply_chunked(
            chat_id,
            "Run failed:\n" + "".join(traceback.format_exception_only(type(e), e)),
        )
        return

    header = (
        "✅ Sent.\n\n"
        if send_for_real
        else "\U0001f4dd Draft (not sent). Resend with `send:` to send.\n\n"
    )
    await _reply_chunked(chat_id, header + result)
