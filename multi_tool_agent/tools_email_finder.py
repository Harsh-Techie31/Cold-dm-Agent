"""Best-effort hiring-email discovery from a company name (web search + scrape).

No paid APIs. Uses DuckDuckGo's HTML endpoints for search and plain ``requests``
for page fetches, then ranks any addresses it finds. Network-dependent and
best-effort: treat "low" confidence results as guesses, not facts.
"""

import asyncio
import re
import urllib.parse

import requests

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_TIMEOUT = 12

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_MAILTO_RE = re.compile(r"mailto:([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})", re.I)
_DDG_RESULT_RE = re.compile(r'result__a[^>]+href="([^"]+)"')
_DDG_LITE_RE = re.compile(r'href="(https?://[^"]+)"[^>]*>[^<]', re.I)

_SOCIAL = (
    "facebook.",
    "twitter.",
    "x.com",
    "linkedin.",
    "instagram.",
    "youtube.",
    "wikipedia.",
    "crunchbase.",
    "glassdoor.",
    "indeed.",
    "duckduckgo.",
    "reddit.",
)
_JUNK_EMAIL_DOMAINS = (
    "sentry.io",
    "wixpress.com",
    "example.com",
    "cloudflare",
    "godaddy",
    "schema.org",
    "w3.org",
    "googleapis.com",
)
_JUNK_LOCALPART = re.compile(r"(png|jpg|jpeg|gif|svg|webp|2x|3x|[0-9a-f]{16,})", re.I)

_HIRING_WORDS = (
    "career",
    "careers",
    "job",
    "jobs",
    "hr",
    "recruit",
    "recruiting",
    "recruitment",
    "talent",
    "hiring",
    "people",
    "work",
    "join",
    "apply",
)
_GENERIC_WORDS = ("info", "hello", "contact", "team", "admin", "office", "support")
_CANDIDATE_PATHS = ("", "/careers", "/careers/", "/jobs", "/join-us", "/about", "/contact", "/company/careers")


def _http_get(url: str) -> str:
    try:
        r = requests.get(url, headers={"User-Agent": _UA}, timeout=_TIMEOUT)
        if r.status_code == 200 and r.text:
            return r.text
    except requests.RequestException:
        pass
    return ""


def _ddg_search(query: str) -> list[str]:
    """Returns result URLs for a query, best-effort, newest DDG HTML endpoints."""
    urls: list[str] = []
    q = urllib.parse.quote_plus(query)
    for endpoint, pattern in (
        (f"https://html.duckduckgo.com/html/?q={q}", _DDG_RESULT_RE),
        (f"https://lite.duckduckgo.com/lite/?q={q}", _DDG_LITE_RE),
    ):
        html = _http_get(endpoint)
        if not html:
            continue
        for m in pattern.findall(html):
            link = m
            if link.startswith("//duckduckgo.com/l/?") or "uddg=" in link:
                qs = urllib.parse.urlparse(
                    link if link.startswith("http") else "https:" + link
                ).query
                uddg = urllib.parse.parse_qs(qs).get("uddg", [])
                if uddg:
                    link = uddg[0]
            if link.startswith("http") and link not in urls:
                urls.append(link)
        if urls:
            break
    return urls


def _root_domain(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")
    return host


def _guess_official_domain(company: str) -> str:
    for url in _ddg_search(f"{company} official website"):
        host = _root_domain(url)
        if host and not any(s in host for s in _SOCIAL):
            return host
    return ""


def _clean_emails(text: str, prefer_domain: str) -> list[str]:
    found = set(m.lower() for m in _MAILTO_RE.findall(text))
    found |= set(m.lower() for m in EMAIL_RE.findall(text))
    out = []
    for e in found:
        local, _, dom = e.partition("@")
        if any(j in dom for j in _JUNK_EMAIL_DOMAINS):
            continue
        if _JUNK_LOCALPART.search(local):
            continue
        out.append(e)
    # Prefer addresses on the company's own domain.
    if prefer_domain:
        on = [e for e in out if e.endswith("@" + prefer_domain) or e.endswith("." + prefer_domain)]
        if on:
            return sorted(set(on))
    return sorted(set(out))


def _score(email: str) -> tuple[str, int]:
    local = email.split("@")[0].lower()
    if any(w in local for w in _HIRING_WORDS):
        return "medium", 3
    if any(w in local for w in _GENERIC_WORDS):
        return "low", 1
    return "low", 2  # looks personal; could be a real recruiter, could be noise


async def find_hiring_email(company: str, domain_hint: str = "") -> dict:
    """Finds likely hiring/recruiting email addresses for a company.

    Use only when the blob had no email. Results are best-effort and network
    dependent. Do NOT auto-send to a "low" confidence result without the user
    confirming the address first.

    Args:
        company (str): Company name as written in the job posting.
        domain_hint (str): Optional known domain (e.g. "acme.com") to skip search.

    Returns:
        dict: {status, domain, candidates: [{email, source, confidence}]}. Candidates
        are sorted best-first. May be empty.
    """
    # This does several sequential blocking `requests` calls (each up to
    # _TIMEOUT seconds). Run it off the event loop so a webhook host's
    # /health endpoint (and everything else) stays responsive while it runs.
    return await asyncio.to_thread(_find_hiring_email_blocking, company, domain_hint)


def _find_hiring_email_blocking(company: str, domain_hint: str = "") -> dict:
    domain = (domain_hint or "").strip().lower().removeprefix("www.")
    if not domain:
        domain = _guess_official_domain(company)

    candidates: dict[str, dict] = {}

    if domain:
        for path in _CANDIDATE_PATHS:
            html = _http_get(f"https://{domain}{path}")
            if not html:
                continue
            for e in _clean_emails(html, domain):
                conf, _ = _score(e)
                src = f"https://{domain}{path or '/'}"
                if e not in candidates:
                    candidates[e] = {"email": e, "source": src, "confidence": conf}

    # Targeted search for a careers/contact address mentioned anywhere.
    for url in _ddg_search(f'"{company}" careers OR recruiting email contact'):
        if domain and _root_domain(url) not in (domain, "www." + domain):
            # still fetch first-party-looking pages
            if domain not in _root_domain(url):
                continue
        html = _http_get(url)
        for e in _clean_emails(html, domain):
            if e not in candidates:
                conf, _ = _score(e)
                candidates[e] = {"email": e, "source": url, "confidence": conf}

    # Pattern guesses as a last resort.
    if domain:
        for lp in ("careers", "jobs", "recruiting", "talent", "hr", "hello"):
            e = f"{lp}@{domain}"
            if e not in candidates:
                candidates[e] = {
                    "email": e,
                    "source": "pattern-guess",
                    "confidence": "low",
                }

    def sort_key(c: dict):
        rank = {"high": 0, "medium": 1, "low": 2}[c["confidence"]]
        guess_penalty = 1 if c["source"] == "pattern-guess" else 0
        return (rank, guess_penalty, c["email"])

    ordered = sorted(candidates.values(), key=sort_key)
    return {
        "status": "success" if ordered else "error",
        "domain": domain or None,
        "candidates": ordered[:8],
        "error_message": None if ordered else "No addresses found; provide the email manually.",
    }
