"""Intake tool: pull the target email (and any domain hints) out of the raw blob."""

import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"https?://([A-Za-z0-9.\-]+)")
BARE_DOMAIN_RE = re.compile(
    r"\b(?:www\.)?((?:[A-Za-z0-9\-]+\.)+[A-Za-z]{2,})\b"
)


def _strip_www(host: str) -> str:
    return host[4:] if host.lower().startswith("www.") else host

_JUNK_EMAIL_DOMAINS = {
    "example.com",
    "sentry.io",
    "wixpress.com",
    "domain.com",
    "email.com",
    "yourcompany.com",
}


def parse_blob(text: str) -> dict:
    """Parses a raw job-posting blob for a contact email and domain hints.

    Args:
        text (str): The pasted blob containing a job opening and, ideally, an email.

    Returns:
        dict: {status, email, all_emails, domain_hints}. ``email`` is None when the
        blob contains no usable address (the orchestrator should then run
        find_hiring_email with the company name).
    """
    raw_emails = [e.strip(".,;:()<>[]\"' ") for e in EMAIL_RE.findall(text or "")]
    emails = []
    for e in raw_emails:
        dom = e.split("@")[-1].lower()
        if dom in _JUNK_EMAIL_DOMAINS:
            continue
        if e.lower() not in [x.lower() for x in emails]:
            emails.append(e)

    domains: list[str] = []
    email_domains = {e.split("@")[-1].lower() for e in emails}
    for host in URL_RE.findall(text or ""):
        host = _strip_www(host.lower())
        if host and host not in domains and "." in host:
            domains.append(host)
    for host in BARE_DOMAIN_RE.findall(text or ""):
        host = _strip_www(host.lower())
        tld = host.rsplit(".", 1)[-1]
        if host in domains or host in email_domains:
            continue
        if tld in {"com", "io", "ai", "co", "org", "net", "dev", "app", "xyz", "tech"}:
            domains.append(host)

    return {
        "status": "success",
        "email": emails[0] if emails else None,
        "all_emails": emails,
        "domain_hints": domains,
    }
