from __future__ import annotations

from typing import Optional, Dict, Callable
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

_METRIC_UNITS = re.compile(
    r"\b("
    r"ms|millisecond[s]?|second[s]?|minute[s]?|hour[s]?|day[s]?|week[s]?|month[s]?|"
    r"gb|tb|mb|kb|"
    r"qps|tps|rps|rpm|"
    r"records/day|records per day|rows/day|rows per day|"
    r"requests/day|requests per day|"
    r")\b",
    re.IGNORECASE,
)

_METRIC_TERMS = re.compile(
    r"\b("
    r"p95|p99|sla|slo|mttr|uptime|latency|throughput|"
    r"error rate|failure rate|success rate|conversion rate|"
    r"availability|response time|lead time|cycle time"
    r")\b",
    re.IGNORECASE,
)

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

_METRIC_PATTERNS: list[tuple[str, str]] = [
    (r"\bpostgres|postgresql|sql|query|index|schema|database|warehouse\b", "db_tuning"),
    (r"\bairflow|kafka|etl|elt|pipeline|ingestion|batch|stream\b", "ingestion"),
    (r"\bdashboard|analytics|reporting|bi\b", "reporting"),
    (r"\blogging|monitoring|alerting|cloudwatch|observability\b", "monitoring"),
    (r"\bswagger|openapi|documentation|runbook|docs\b", "documentation"),
    (r"\bapi|microservice|fastapi|service\b", "api"),
    (r"\bauth|oauth|security|compliance|permission\b", "security"),
]

_METRIC_TEMPLATES: Dict[str, list[str]] = {
    "db_tuning": [
        "reducing query time for key analytics paths",
        "improving query performance for high-concurrency reads",
        "lowering database latency on primary dashboards",
    ],
    "ingestion": [
        "keeping ingestion success within SLA windows",
        "preventing reprocessing loops and failed reruns",
        "maintaining stable throughput during peak loads",
    ],
    "reporting": [
        "speeding up report refresh to meet stakeholder SLAs",
        "keeping dashboard data fresh for daily reviews",
        "shortening ad-hoc analytics turnaround for business users",
    ],
    "monitoring": [
        "reducing MTTR through better alerting and runbooks",
        "improving incident response time with actionable signals",
        "keeping data services available for on-call rotations",
    ],
    "documentation": [
        "reducing onboarding time with clear runbooks and examples",
        "increasing self-service adoption of data sets",
        "cutting support handoffs via documented contracts",
    ],
    "api": [
        "improving integration speed with stable versioned contracts",
        "reducing API onboarding time with samples and mocks",
        "increasing internal adoption of shared services",
    ],
    "security": [
        "reducing access-related incidents with RBAC and audits",
        "improving compliance readiness via standardized controls",
        "lowering auth-related support tickets with safer defaults",
    ],
}

_OUTCOME_PATTERNS = {
    "pipeline": [
        "keeping critical data workflows within SLA and uptime targets",
        "supporting daily data refresh for downstream systems",
        "processing high-volume records while maintaining accuracy",
    ],
    "dashboard": [
        "supporting stakeholders with timely, trustable insights",
        "enabling key reporting use cases across the organization",
        "reducing report generation friction for business users",
    ],
    "query": [
        "optimizing data retrieval for latency-sensitive queries",
        "reducing execution time for common analytical workloads",
        "supporting responsive experiences for analytics queries",
    ],
    "database": [
        "supporting concurrent users and growing data volume reliably",
        "enabling recurring reporting cycles without regressions",
        "improving query performance for core datasets",
    ],
    "etl": [
        "automating data ingestion across multiple sources with freshness guarantees",
        "reducing manual data processing effort via repeatable pipelines",
        "ensuring data freshness for critical use cases",
    ],
    "model": [
        "supporting downstream analytics use cases consistently",
        "improving data consistency across reporting dimensions",
        "enabling faster time-to-insight for analysts",
    ],
    "optimization": [
        "improving performance for key paths",
        "reducing infrastructure costs through efficiency",
        "increasing system reliability toward target uptime",
    ],
    "documentation": [
        "improving team onboarding with clearer docs",
        "enabling teams to self-serve data access",
        "reducing data engineering support requests with better guidance",
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
            _ensure_metric_clause(
                _ensure_outcome_clause(bullet, jd_text, structured_jd),
                jd_text,
                structured_jd,
            )
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


def ensure_metric_clause(
    bullet: str,
    jd_text: str,
    structured_jd: Optional[dict] = None,
) -> str:
    """Return a bullet with a conservative metric clause if missing."""
    return _ensure_metric_clause(bullet, jd_text, structured_jd)


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


def _has_metrics(text: str) -> bool:
    if _NUMBER_MARKERS.search(text):
        return True
    if _METRIC_UNITS.search(text):
        return True
    if _METRIC_TERMS.search(text):
        return True
    return False


def _ensure_metric_clause(bullet: str, jd_text: str, structured_jd: Optional[dict]) -> str:
    clean = (bullet or "").strip()
    if not clean:
        return bullet

    if _has_metrics(clean):
        return clean

    if len(clean) > 240:
        return clean

    category = _select_metric_category(clean, jd_text, structured_jd)
    if not category:
        return clean

    clause = _metric_clause_for(category)
    if not clause:
        return clean

    clean = clean.rstrip(" .;:")
    return f"{clean}, {clause}"


def _select_metric_category(bullet: str, jd_text: str, structured_jd: Optional[dict]) -> Optional[str]:
    lower = (bullet or "").lower()
    for pattern, category in _METRIC_PATTERNS:
        if re.search(pattern, lower):
            return category
    jd_lower = (jd_text or "").lower()
    for pattern, category in _METRIC_PATTERNS:
        if re.search(pattern, jd_lower):
            return category
    return None


def _metric_clause_for(category: str) -> Optional[str]:
    options = _METRIC_TEMPLATES.get(category, [])
    if not options:
        return None
    return options[0]

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

    # Pick a consistent outcome template for this category
    templates = _OUTCOME_PATTERNS.get(best_category, [])
    if not templates:
        return None

    outcome = templates[0]  # Use first template for consistency

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
