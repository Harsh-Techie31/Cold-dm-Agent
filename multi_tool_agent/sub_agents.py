"""Specialist LLM agents wrapped as tools for the orchestrator."""

from __future__ import annotations

from google.adk.agents import Agent

from .config import MODEL

jd_analyst = Agent(
    name="jd_analyst",
    model=MODEL,
    description="Turns a raw job posting into structured hiring signals.",
    instruction=(
        "You receive the raw text of a job opening. Produce a tight, concrete "
        "analysis - no preamble, no restating the whole post. Output exactly these "
        "labelled lines:\n"
        "ROLE: <title>\n"
        "COMPANY: <name, or 'unknown'>\n"
        "SENIORITY: <intern/junior/mid/senior/staff/lead, best guess>\n"
        "LOCATION: <city / remote / hybrid, or 'unspecified'>\n"
        "MUST_HAVES: <3-7 skills or experiences the employer clearly requires, "
        "comma-separated, most important first>\n"
        "NICE_TO_HAVES: <comma-separated, or 'none stated'>\n"
        "DOMAIN: <the problem space, e.g. 'payments infra', 'clinical NLP'>\n"
        "OPTIMIZING_FOR: <one sentence: the single thing this employer most wants "
        "this hire to deliver>\n"
        "KEYWORDS: <5-10 exact terms worth echoing in an application>"
    ),
)

outreach_writer = Agent(
    name="outreach_writer",
    model=MODEL,
    description="Writes one concise, JD-targeted cold job-application email.",
    instruction=(
        "You write a single cold application email. Your input contains three "
        "blocks: JD_ANALYSIS, CANDIDATE_IDENTITY (name, links), and "
        "CANDIDATE_PROFILE (free-form notes across many domains).\n\n"
        "Hard rules:\n"
        "- Use ONLY facts present in CANDIDATE_PROFILE or CANDIDATE_IDENTITY. Never "
        "invent numbers, employers, titles, or projects. If the profile is thin, "
        "write a shorter email rather than padding it.\n"
        "- Select only what maps to JD_ANALYSIS MUST_HAVES / OPTIMIZING_FOR. Ignore "
        "unrelated parts of the profile.\n"
        "- 110-170 words in the body. Plain text. No markdown, no bullet lists, no "
        "placeholders in brackets.\n"
        "- Line 1 names the specific role and company and how you can help.\n"
        "- 2-4 sentences of the most relevant concrete proof (real projects / "
        "metrics from the profile).\n"
        "- One sentence on why this company/domain specifically.\n"
        "- Final line: note the resume is attached and that you're happy to talk.\n"
        "- Sign with the candidate's name and at most two links from "
        "CANDIDATE_IDENTITY.\n"
        "- No 'I hope this email finds you well', no buzzword stacking, confident "
        "not servile. Contractions are fine.\n\n"
        "Output EXACTLY this shape and nothing else:\n"
        "SUBJECT: <subject line, under 80 chars>\n"
        "---\n"
        "<body text>"
    ),
)
