from __future__ import annotations

from typing import Optional, Dict
import re

from app.models.schemas import ResumeState


_OUTCOME_MARKERS = re.compile(
    r"\b("
    r"resulting in|leading to|so that|thereby|which\b|"
    r"improv\w+|increas\w+|reduc\w+|decreas\w+|"
    r"optim\w+|streamlin\w+|autom\w+|"
    r"enable\w+|ensur\w+|deliver\w+|achiev\w+|"
    r"boost\w+|cut\b|save\w+|lower\w+|raise\w+|"
    r"reliab\w+|availab\w+|uptime|performance|latency|throughput|"
    r"scalab\w+|security|compliance|quality|accuracy|"
    r"efficien\w+|cost|risk|stability|resilien\w+"
    r")\b",
    re.IGNORECASE,
)

_TO_OUTCOME_VERBS = re.compile(
    r"\bto\s+(improv\w+|enable\w+|support\w+|reduce\w+|increase\w+|"
    r"ensure\w+|drive\w+|deliver\w+|accelerat\w+|optim\w+)\b",
    re.IGNORECASE,
)

_NUMBER_MARKERS = re.compile(r"\b\d+(\.\d+)?%?\b|\b\d+x\b", re.IGNORECASE)

_GOAL_PATTERNS = [
    (r"\breliab|availability|uptime|resilien", "reliability and uptime"),
    (r"\bperformance|latency|throughput|speed", "performance and latency"),
    (r"\bscalab|scale|high traffic|high-volume", "scalability"),
    (r"\bsecurity|auth|oauth|compliance|privacy|risk", "security and compliance"),
    (r"\bdata quality|quality|accuracy|validation", "data quality"),
    (r"\bautomation|manual effort|ops|operational", "automation and operational efficiency"),
    (r"\bcost|optimi[sz]ation|efficien", "cost and efficiency"),
    (r"\banalytics|reporting|insight|dashboard", "analytics reporting"),
    (r"\bpipeline|ingest|ingestion|etl|elt|warehouse|data", "reliable data pipelines"),
]

_LEADING_VERBS = {
    "design",
    "develop",
    "build",
    "implement",
    "create",
    "own",
    "lead",
    "deliver",
    "maintain",
    "optimize",
    "support",
    "improve",
    "enhance",
    "manage",
    "coordinate",
    "collaborate",
    "translate",
    "define",
    "establish",
}


_OUTCOME_PATTERNS = {
    "pipeline": [
        "ensuring {percentage}% uptime for critical data workflows",
        "supporting daily data refresh for {count}+ downstream systems",
        "processing {scale} records daily with {percentage}% accuracy",
    ],
    "dashboard": [
        "supporting {count}+ stakeholders with real-time insights",
        "enabling {count}+ reporting use cases across the organization",
        "reducing report generation time from hours to minutes",
    ],
    "query": [
        "optimizing data retrieval by an estimated {percentage}%",
        "reducing execution time from {duration1} to {duration2}",
        "supporting sub-second response times for {count}+ analytics queries",
    ],
    "database": [
        "supporting {count}+ concurrent users and {volume} TB+ data volume",
        "enabling {count}+ monthly reporting requests",
        "improving query performance by an estimated {percentage}%",
    ],
    "etl": [
        "automating data ingestion for {count}+ data sources",
        "reducing manual data processing time by an estimated {percentage}%",
        "ensuring data freshness within {duration} for critical use cases",
    ],
    "model": [
        "supporting {count}+ downstream analytics use cases",
        "improving data consistency across {count}+ reporting dimensions",
        "enabling faster time-to-insight for business analysts",
    ],
    "optimization": [
        "improving performance by an estimated {percentage}%",
        "reducing infrastructure costs by approximately {percentage}%",
        "increasing system reliability to {percentage}%+ uptime",
    ],
    "documentation": [
        "improving team onboarding time by an estimated {percentage}%",
        "enabling {count}+ team members to self-serve data access",
        "reducing data engineering support requests by an estimated {percentage}%",
    ],
}

_INDUSTRY_CONTEXT = {
    "finance": ["compliance", "audit trail", "regulatory reporting", "risk management"],
    "healthcare": ["patient outcomes", "clinical research", "data governance", "privacy"],
    "ecommerce": ["conversion rates", "customer experience", "revenue impact", "user engagement"],
    "saas": ["customer retention", "platform reliability", "feature adoption", "user growth"],
}


def enforce_outcome_clauses(
    state: ResumeState,
    jd_text: str,
    structured_jd: Optional[dict] = None,
) -> ResumeState:
    """Ensure experience bullets include a conservative outcome/purpose clause."""
    for role in state.sections.experience:
        role.bullets = [
            _ensure_outcome_clause(bullet, jd_text, structured_jd)
            for bullet in role.bullets
        ]
    return state


def ensure_outcome_clause(
    bullet: str,
    jd_text: str,
    structured_jd: Optional[dict] = None,
) -> str:
    """Return a bullet with a conservative outcome/purpose clause if missing."""
    return _ensure_outcome_clause(bullet, jd_text, structured_jd)


def _ensure_outcome_clause(bullet: str, jd_text: str, structured_jd: Optional[dict]) -> str:
    clean = (bullet or "").strip()
    if not clean:
        return bullet

    if _has_outcome(clean):
        return clean

    if len(clean) > 240:
        return clean

    goal, verb = _select_goal(jd_text, structured_jd)
    if not goal:
        return clean

    clean = clean.rstrip(" .;:")
    return f"{clean} {verb} {goal}"


def _has_outcome(text: str) -> bool:
    if _OUTCOME_MARKERS.search(text):
        return True
    if _TO_OUTCOME_VERBS.search(text):
        return True
    if _NUMBER_MARKERS.search(text):
        return True
    return False


def _select_goal(jd_text: str, structured_jd: Optional[dict]) -> tuple[str, str]:
    if structured_jd:
        responsibilities = structured_jd.get("responsibilities") or []
        for resp in responsibilities:
            phrase = _normalize_responsibility(resp)
            if phrase:
                return phrase, "to support"

    lower = (jd_text or "").lower()
    for pattern, goal in _GOAL_PATTERNS:
        if re.search(pattern, lower):
            return goal, "to improve"

    return "maintainability and reliability", "to improve"


def _normalize_responsibility(text: str) -> str:
    clean = re.sub(r"^[-*\u2022]\s+", "", (text or "").strip())
    clean = clean.rstrip(".;:")
    if not clean:
        return ""
    words = clean.split()
    if words and words[0].lower() in _LEADING_VERBS:
        words = words[1:]
    if len(words) > 8:
        words = words[:8]
    phrase = " ".join(words).strip()
    if phrase.lower().startswith("to "):
        phrase = phrase[3:].strip()
    return phrase


def _infer_outcome(bullet: str, domain: str) -> Optional[str]:
    """Infer plausible outcome based on activity keywords and domain."""
    lower = bullet.lower()

    # Find matching category
    best_category = None
    for category in _OUTCOME_PATTERNS.keys():
        if category in lower:
            best_category = category
            break

    if not best_category:
        # Try to detect by action verbs
        if any(word in lower for word in ["build", "create", "develop", "design"]):
            if "pipeline" in lower:
                best_category = "pipeline"
            elif "dashboard" in lower:
                best_category = "dashboard"
            elif "model" in lower:
                best_category = "model"
            elif "database" in lower or "warehouse" in lower:
                best_category = "database"

    if not best_category:
        return None

    # Pick a random outcome template for this category
    templates = _OUTCOME_PATTERNS.get(best_category, [])
    if not templates:
        return None

    outcome = templates[0]  # Use first template for consistency

    # Substitute placeholders with conservative values
    outcome = outcome.replace("{percentage}", "~10-15")
    outcome = outcome.replace("{count}", "several")
    outcome = outcome.replace("{scale}", "thousands")
    outcome = outcome.replace("{volume}", "a few")
    outcome = outcome.replace("{duration}", "hours")
    outcome = outcome.replace("{duration1}", "minutes")
    outcome = outcome.replace("{duration2}", "seconds")

    if outcome.startswith("improving") or outcome.startswith("enabling"):
        return f"{bullet.rstrip('.')} {outcome}."
    else:
        return f"{bullet.rstrip('.')}, {outcome}."


def _extract_scale_hints(bullet: str) -> Dict[str, str]:
    """Extract hints about scale from bullet context."""
    hints = {}
    if "daily" in bullet.lower():
        hints["frequency"] = "daily"
    if "weekly" in bullet.lower():
        hints["frequency"] = "weekly"
    if "monthly" in bullet.lower():
        hints["frequency"] = "monthly"
    if any(word in bullet.lower() for word in ["enterprise", "large", "big"]):
        hints["scale"] = "enterprise"
    if any(word in bullet.lower() for word in ["startup", "small", "early"]):
        hints["scale"] = "startup"
    return hints
