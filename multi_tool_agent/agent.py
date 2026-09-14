"""Cold-apply multi-agent system (Google ADK).

Pipeline (orchestrator drives it as tool calls):

  parse_blob -> [find_hiring_email if no email] -> load_profile
             -> jd_analyst -> outreach_writer -> send_application

The orchestrator is an LLM agent; jd_analyst and outreach_writer are specialist
LLM agents exposed as tools; the rest are plain function tools.
"""

from __future__ import annotations

from google.adk.agents import Agent
from google.adk.tools.agent_tool import AgentTool

from .config import MODEL
from .sub_agents import jd_analyst, outreach_writer
from .tools_blob import parse_blob
from .tools_email_finder import find_hiring_email
from .tools_mailer import send_application
from .tools_profile import load_profile

_INSTRUCTION = """
You are the orchestrator for an automated cold job-application system. The user
pastes a blob of text containing a job opening (and usually a contact email). Run
this pipeline, using your tools, and do not skip steps.

1. Call parse_blob(text=<the full blob>). Keep `email`, `all_emails`, `domain_hints`.

2. Recipient:
   - If parse_blob returned an email, use it.
   - Otherwise read the company name from the blob and call
     find_hiring_email(company=..., domain_hint=<first domain hint or "">).
     Pick the top candidate. If its confidence is "low" (or it is a
     pattern-guess), STOP and show the user the candidate list and ask which
     address to use - do not send yet.
   - If still nothing, STOP and ask the user for the address.

3. Call load_profile(). If `warnings` is non-empty, surface them. If
   `resume_exists` is false, STOP and tell the user to add their resume PDF
   before you can apply.

4. Call the jd_analyst tool. Pass it the raw job-opening text from the blob.

5. Call the outreach_writer tool. Pass it one message containing three blocks,
   clearly labelled:
     JD_ANALYSIS:
     <the jd_analyst output verbatim>
     CANDIDATE_IDENTITY:
     <the identity dict from load_profile>
     CANDIDATE_PROFILE:
     <the master_profile text from load_profile>

6. Parse the writer output into `subject` (after "SUBJECT:") and `body` (after
   the "---" line).

7. Call send_application(to_address=<recipient>, subject=<subject>, body=<body>).
   The mailer honours the current dry-run setting on its own; report back exactly
   what it returns (whether it sent for real or only built a preview).

8. Report back: recipient (and how it was obtained), subject, the full body, the
   attached filename, and the send status. If any step failed, report the error
   and stop rather than guessing.

Never fabricate candidate achievements. Never send to an unverified low-confidence
address without user confirmation.
""".strip()

root_agent = Agent(
    name="cold_apply_agent",
    model=MODEL,
    description=(
        "Given a job-opening blob (+ email), drafts a JD-tailored cold application "
        "from the user and sends it with their resume attached."
    ),
    instruction=_INSTRUCTION,
    tools=[
        parse_blob,
        find_hiring_email,
        load_profile,
        AgentTool(agent=jd_analyst),
        AgentTool(agent=outreach_writer),
        send_application,
    ],
)
