# cold_apply_agent — automated cold job applications (Google ADK)

Paste a blob of text with a job opening (and ideally a contact email). The system
analyses the JD, writes a short application email in your voice using only real
facts from your profile, attaches your resume PDF, and sends it from your Gmail.

## Architecture

```
cold_apply_agent  (orchestrator LLM, agent.py)
├── parse_blob            tools_blob.py         find the email + domain hints in the blob
├── find_hiring_email     tools_email_finder.py web-search + scrape for a hiring inbox
│                                               (only if the blob has no email)
├── load_profile          tools_profile.py      load master_profile.md + candidate.json
├── jd_analyst            sub_agents.py         JD -> structured must-haves / keywords
├── outreach_writer       sub_agents.py         analysis + profile -> subject + body
└── send_application      tools_mailer.py       SMTP send, resume PDF attached
```

`jd_analyst` and `outreach_writer` are their own LLM agents exposed to the
orchestrator as tools (`AgentTool`), so each has a focused prompt and can be
swapped/tuned independently.

## One-time setup

1. **Resume** — drop your PDF at `resume/resume.pdf` (or set an absolute
   `resume_path` in `profile/candidate.json`).
2. **Identity** — fill in `profile/candidate.json` (name, email, links,
   `resume_filename`).
3. **Profile** — fill in `profile/master_profile.md` with every domain, project,
   and real metric you'd ever cite. The writer uses **only** what's in here and is
   told never to invent — thin profile means thin emails.
4. **.env** — already has `GOOGLE_API_KEY` and Gmail `SMTP_EMAIL` /
   `SMTP_PASSWORD` (Gmail *App Password*). Optional:
   - `COLD_APPLY_DRY_RUN=true` — build the email but don't send (test mode).
   - `COLD_APPLY_MODEL` — model for all agents. `gemini-flash-latest` (default,
     uses `GOOGLE_API_KEY`) or an OpenAI model like `openai/gpt-4o-mini` /
     `openai/gpt-4o` (routed via LiteLLM, needs `OPENAI_API_KEY` and
     `pip install litellm`).

## Run

```bash
cd C:\Users\micro\multi_tool_agent   # the repo root (one level above this file)
adk web            # pick "multi_tool_agent", then paste the job blob
# or
adk run multi_tool_agent
```

Set `COLD_APPLY_DRY_RUN=true` for your first run and check the printed subject /
body / recipient before switching it off.

## Trigger it from your phone (Telegram)

No webhook / public URL — the bot long-polls Telegram, so it runs anywhere
that can stay on (your PC, a free VM, a Space).

1. In Telegram, message **@BotFather** -> `/newbot` -> copy the token into
   `TELEGRAM_BOT_TOKEN` in `.env`.
2. Message **@userinfobot** to get your numeric id -> put it in
   `TELEGRAM_ALLOWED_USER_IDS` (comma-separate for more than one). The bot
   refuses to run any blob until this is set, and ignores every other user.
3. Install deps and run:

   ```bash
   C:\Users\micro\adk-env\Scripts\python.exe -m pip install python-telegram-bot litellm
   cd C:\Users\micro\multi_tool_agent
   C:\Users\micro\adk-env\Scripts\python.exe -m multi_tool_agent.telegram_bot
   ```

Then from your phone, DM the bot:

| You send | Bot does |
|---|---|
| the raw job blob | **drafts** the email, shows it, sends nothing |
| `send:` + the job blob | actually sends it |
| `/start` | usage |

The `send:` prefix overrides `COLD_APPLY_DRY_RUN` per-message, so you can leave
that flag alone. Runs are serialized (one blob at a time).

To keep it running after you close the terminal: on Windows use Task Scheduler
(trigger "at log on", action = the command above); on a Linux VM use a
`systemd` service or `tmux`.

## Deploy to Render (webhook — free, no computer of yours needed)

This is a **different front-end** from the Telegram polling bot above:
`webhook_app.py` is a small FastAPI app. Telegram pushes each message to it
over HTTPS instead of the bot pulling messages in a loop, which is what lets
it live on Render's free tier (which only offers *web* services, not
always-on background workers). Same agent underneath, same message protocol
(`send:` prefix), different transport.

**Repo layout matters here**: this repo's root (one level above this file) is
what Render clones. `render.yaml` at that root is a
[Render Blueprint](https://render.com/docs/blueprint-spec) that points at
`multi_tool_agent/requirements.txt` and runs
`uvicorn multi_tool_agent.webhook_app:app`.

### Steps

1. **Push this repo to GitHub** (private is fine — Render just needs read access):
   ```bash
   cd C:\Users\micro\multi_tool_agent
   git add -A
   git commit -m "cold-apply agent"
   git remote add origin https://github.com/<you>/<repo>.git
   git push -u origin main
   ```
   `.gitignore` already excludes `.env` — **verify `git status` shows nothing
   under `multi_tool_agent/.env` before you push.**

2. **Render dashboard** -> New -> **Blueprint** -> pick this repo. Render reads
   `render.yaml` and proposes the `cold-apply-agent` web service on the free
   plan. Create it.

3. **Fill in the secret env vars** Render left blank (`sync: false` in the
   blueprint means "ask me", not "leave empty") — Dashboard -> your service ->
   Environment:
   - `TELEGRAM_BOT_TOKEN` — from @BotFather
   - `TELEGRAM_WEBHOOK_SECRET` — any random string you make up (e.g.
     `openssl rand -hex 20`); must match on both ends, which is automatic
     since the app sends it to Telegram itself on boot
   - `TELEGRAM_ALLOWED_USER_IDS` — your numeric id from @userinfobot
   - `SMTP_EMAIL`, `SMTP_PASSWORD` — your Gmail + app password
   - `OPENAI_API_KEY` — if using an OpenAI model

   `profile/candidate.json`, `profile/master_profile.md`, and
   `resume/*.pdf` are **git-ignored on purpose** — your resume and identity
   never touch the repo. On the same Environment page, use **Secret Files**
   (not env vars) to upload the real versions of these three:
   | Secret File path | Content |
   |---|---|
   | `/etc/secrets/candidate.json` | your filled-in `candidate.json` |
   | `/etc/secrets/master_profile.md` | your filled-in `master_profile.md` |
   | `/etc/secrets/resume.pdf` | your resume PDF |

   `config.py` checks `SECRETS_DIR` (`/etc/secrets`, already set by
   `render.yaml`) first and only falls back to the repo's `profile/`/`resume/`
   folders locally. `multi_tool_agent/profile/*.example.json` /
   `*.example.md` in the repo show the expected shape.

4. **Deploy.** On boot the app calls Telegram's `setWebhook` itself, using
   Render's auto-provided `RENDER_EXTERNAL_URL` — no manual webhook
   registration step. Check the logs for `setWebhook(...) -> True`.

5. DM the bot from your phone. First message after idle will be slow (Render
   free cold start, ~30-50s, on top of the agent's own 30-90s) — that's
   expected, see Behaviour notes below.

### Keeping it from sleeping (optional)

Render's free web services sleep after 15 minutes with no inbound HTTP
traffic, which also kills the process (not just slows it). To avoid the cold
start entirely, add a free external pinger — **cron-job.org** or
**UptimeRobot** (no card) — hitting `https://<your-app>.onrender.com/health`
every ~10 minutes. Without it, the bot still works, just with a cold-start
delay on the first message after a gap.

### Local testing before you deploy

```bash
cd C:\Users\micro\multi_tool_agent
C:\Users\micro\adk-env\Scripts\python.exe -m uvicorn multi_tool_agent.webhook_app:app --reload --port 8000
```
Without `PUBLIC_URL`/`RENDER_EXTERNAL_URL` set, it skips webhook registration
and just serves `/health` and `/` — enough to confirm it boots.

## Behaviour notes

- **Auto-send** is on. The one guard: if the recipient had to be guessed
  (`find_hiring_email` returned only low-confidence / pattern addresses), the
  orchestrator stops and asks you to pick the address first.
- `find_hiring_email` is best-effort and network-dependent (DuckDuckGo HTML +
  page scrape, no paid API). It returns `high`/`medium`/`low` confidence and the
  source URL for each candidate.
- Resume tailoring + Google Drive upload are **not** in v1 (static PDF attach).
  The seams for it: a new `resume_tailor` agent + a `render_pdf` / `drive_upload`
  tool, called between `jd_analyst` and `outreach_writer`, writing the link into
  the writer's input.

## Files

| File | Purpose |
|------|---------|
| `agent.py` | orchestrator + pipeline instruction |
| `sub_agents.py` | `jd_analyst`, `outreach_writer` |
| `tools_blob.py` | blob → email / domains |
| `tools_email_finder.py` | company → hiring email candidates |
| `tools_profile.py` | load candidate profile |
| `tools_mailer.py` | SMTP send with attachment |
| `config.py` | paths, model, dry-run, profile loaders |
| `telegram_bot.py` | Telegram front-end, polling (PC / Pi / phone) |
| `webhook_app.py` | Telegram front-end, webhook (Render) |
| `_demo_*.py.bak` | the original ADK quickstart agents, kept for reference |

At the repo root (one level up): `render.yaml` (Render Blueprint), `.gitignore`.
