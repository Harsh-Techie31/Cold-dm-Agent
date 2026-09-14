"""Profile tool: hand the writer agent everything it knows about the candidate."""

from .config import load_candidate, load_master_profile


def load_profile() -> dict:
    """Loads the candidate's master profile and structured identity.

    Returns:
        dict: {status, identity, master_profile, resume_path, resume_exists,
        warnings}. ``master_profile`` is free-form markdown covering every domain
        the candidate works in; the writer must only use facts found here or in
        ``identity`` and must never invent achievements.
    """
    identity = load_candidate()
    profile_md = load_master_profile()
    warnings = []

    if identity.get("_error"):
        warnings.append(identity["_error"])
    if not profile_md.strip():
        warnings.append("profile/master_profile.md is empty - fill it in.")
    if not identity.get("resume_exists"):
        warnings.append(
            f"resume not found at {identity.get('resume_path_resolved')!r} - "
            "drop your PDF in resume/ or set resume_path in candidate.json."
        )

    return {
        "status": "success",
        "identity": {
            k: v for k, v in identity.items() if not k.startswith("_")
        },
        "master_profile": profile_md,
        "resume_path": identity.get("resume_path_resolved"),
        "resume_exists": identity.get("resume_exists", False),
        "warnings": warnings,
    }
