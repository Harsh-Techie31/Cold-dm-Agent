"""Mailer tool: send the finished application via Gmail SMTP with the resume attached."""

import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from . import config  # read config.DRY_RUN at call time so the bot can toggle it
from .config import load_candidate

EMAIL_RE_OK = lambda s: isinstance(s, str) and "@" in s and "." in s.split("@")[-1]


def send_application(to_address: str, subject: str, body: str) -> dict:
    """Sends the cold job application email, attaching the candidate's resume PDF.

    Args:
        to_address (str): Verified recipient address (hiring contact / careers inbox).
        subject (str): Final subject line from the outreach_writer agent.
        body (str): Final plain-text email body from the outreach_writer agent.

    Returns:
        dict: {status, message, dry_run, attached}. On success the email has been
        sent (unless COLD_APPLY_DRY_RUN is set, in which case it was only built).
    """
    if not EMAIL_RE_OK(to_address):
        return {"status": "error", "error_message": f"invalid recipient: {to_address!r}"}
    if not subject.strip() or not body.strip():
        return {"status": "error", "error_message": "subject and body must be non-empty"}

    smtp_email = os.environ.get("SMTP_EMAIL")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    if not smtp_email or not smtp_password:
        return {
            "status": "error",
            "error_message": "Set SMTP_EMAIL and SMTP_PASSWORD (Gmail app password) in .env",
        }

    identity = load_candidate()
    from_name = identity.get("name") or smtp_email
    resume_path = Path(identity.get("resume_path_resolved", ""))

    msg = MIMEMultipart()
    msg["From"] = f"{from_name} <{smtp_email}>"
    msg["To"] = to_address
    msg["Subject"] = subject
    reply_to = identity.get("email")
    if reply_to and reply_to != smtp_email:
        msg["Reply-To"] = reply_to
    msg.attach(MIMEText(body, "plain", "utf-8"))

    attached = None
    if resume_path.exists():
        part = MIMEApplication(resume_path.read_bytes(), _subtype="pdf")
        fname = identity.get("resume_filename") or f"{(from_name or 'resume').replace(' ', '_')}_Resume.pdf"
        part.add_header("Content-Disposition", "attachment", filename=fname)
        msg.attach(part)
        attached = fname

    if config.DRY_RUN:
        return {
            "status": "success",
            "dry_run": True,
            "attached": attached,
            "message": f"[DRY RUN] Not sent. Would email {to_address} as {msg['From']}.",
        }

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(smtp_email, smtp_password)
            server.sendmail(smtp_email, [to_address], msg.as_string())
    except smtplib.SMTPAuthenticationError:
        return {
            "status": "error",
            "error_message": "SMTP auth failed - use a Gmail App Password, not your login password.",
        }
    except Exception as e:  # pragma: no cover - network
        return {"status": "error", "error_message": f"send failed: {e}"}

    return {
        "status": "success",
        "dry_run": False,
        "attached": attached,
        "message": f"Sent to {to_address} as {msg['From']}"
        + (f" with {attached} attached." if attached else " (no resume attached)."),
    }
