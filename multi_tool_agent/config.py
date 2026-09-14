"""Shared paths and candidate config for the cold-apply agent system."""

from __future__ import annotations

import json
import os
from pathlib import Path

try:  # google-adk ships python-dotenv; load .env sitting next to this package
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent / ".env")
except Exception:  # pragma: no cover - dotenv is optional
    pass

PACKAGE_DIR = Path(__file__).parent
PROFILE_DIR = PACKAGE_DIR / "profile"
RESUME_DIR = PACKAGE_DIR / "resume"

# On a host where the real profile/resume aren't in the repo (e.g. Render
# Secret Files, mounted outside git), point SECRETS_DIR at that mount and it
# takes priority over the local profile/ and resume/ folders. Unset locally.
SECRETS_DIR = Path(os.environ["SECRETS_DIR"]) if os.environ.get("SECRETS_DIR") else None


def _resolve(filename: str, local_dir: Path) -> Path:
    if SECRETS_DIR and (SECRETS_DIR / filename).exists():
        return SECRETS_DIR / filename
    return local_dir / filename


MASTER_PROFILE_PATH = _resolve("master_profile.md", PROFILE_DIR)
CANDIDATE_JSON_PATH = _resolve("candidate.json", PROFILE_DIR)

# Model used across every agent. Override with COLD_APPLY_MODEL in .env.
#   Gemini:  gemini-flash-latest  (plain string, uses GOOGLE_API_KEY)
#   OpenAI:  openai/gpt-4o  or  gpt-4o-mini  (routed via LiteLLM, uses OPENAI_API_KEY)
_MODEL_NAME = os.environ.get("COLD_APPLY_MODEL", "gemini-flash-latest").strip()


def _build_model(name: str):
    """Return a model spec ADK's Agent accepts: a str for Gemini, LiteLlm otherwise."""
    lname = name.lower()
    is_openai = lname.startswith(("gpt-", "o1", "o3", "o4", "chatgpt"))
    if "/" in name or is_openai:
        from google.adk.models.lite_llm import LiteLlm

        if is_openai and "/" not in name:
            name = f"openai/{name}"
        # Render's free-tier network occasionally drops the first outbound
        # HTTPS connection after a cold start ("Connection error." from
        # litellm/openai). Retry transient connection failures instead of
        # failing the whole 8-call pipeline on one blip.
        return LiteLlm(model=name, timeout=60, num_retries=3)
    return name  # Gemini model name


MODEL = _build_model(_MODEL_NAME)

# When true the mailer builds the message but does NOT send it (safe testing).
DRY_RUN = os.environ.get("COLD_APPLY_DRY_RUN", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def load_candidate() -> dict:
    """Reads profile/candidate.json and resolves the resume path to an absolute file."""
    if not CANDIDATE_JSON_PATH.exists():
        return {"_error": f"missing {CANDIDATE_JSON_PATH}"}

    data = json.loads(CANDIDATE_JSON_PATH.read_text(encoding="utf-8"))

    # A mounted Secret File wins outright when present (e.g. on Render) -
    # candidate.json's own resume_path is only used for local dev.
    if SECRETS_DIR and (SECRETS_DIR / "resume.pdf").exists():
        resume_path = (SECRETS_DIR / "resume.pdf").resolve()
    else:
        resume = (data.get("resume_path") or "").strip()
        resume_path = Path(resume) if resume else (RESUME_DIR / "resume.pdf")
        if not resume_path.is_absolute():
            resume_path = (PACKAGE_DIR / resume_path).resolve()

        # Fall back to the first PDF dropped into resume/ locally.
        if not resume_path.exists() and RESUME_DIR.exists():
            pdfs = sorted(RESUME_DIR.glob("*.pdf"))
            if pdfs:
                resume_path = pdfs[0].resolve()

    data["resume_path_resolved"] = str(resume_path)
    data["resume_exists"] = resume_path.exists()
    return data


def load_master_profile() -> str:
    """Reads the free-form master profile markdown (all context across domains)."""
    if not MASTER_PROFILE_PATH.exists():
        return ""
    return MASTER_PROFILE_PATH.read_text(encoding="utf-8")
