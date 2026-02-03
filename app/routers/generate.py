from fastapi import APIRouter, HTTPException, Request
import json
import re
import logging
from uuid import uuid4
from pydantic import ValidationError

from app.config import settings
from app.models.schemas import GenerateRequest, GenerateResponse, RetrievedChunk, ResumeAudit
from app.services.indexing import index_exists
from app.services.retrieval import retrieve_topk
from app.services.prompts import SYSTEM_PROMPT, build_user_prompt
from app.services.llm_client import generate_with_llm
from app.services.jd_parser import parse_jd
from app.services.domain_rewriter import rewrite_chunks, dedupe_chunks, grade_skills
from app.services.experience_inventory import extract_experience_inventory
from app.services.master_resume import select_master_resume, extract_experience_headers
from app.services.parsing import read_text
from app.services.resume_state import parse_resume_text_to_state, render_resume_text
from app.services.outcome_enforcer import enforce_outcome_clauses
from app.services.resume_store import init_resume_record

router = APIRouter()
logger = logging.getLogger(__name__)


POLISH_SYSTEM = """You are a resume bullet polisher.
Keep COMPANY, TITLE, DATES exactly as in the input. Do not add new roles or change headings.
Be assertive: never use hedge words (estimated, likely, approximately, about) and do not use "~".
Rules:
- Every bullet = Action + Outcome (prefer metrics: latency, throughput, error rate, $/time saved, tickets reduced).
- Avoid repeating the same closing clause across bullets and avoid repeating "improve scalability" wording.
- Vary verbs and endings; use impact verbs (cut, reduced, decreased, lowered, saved, increased, boosted, raised, accelerated, shortened, improved by X%, avoided, prevented).
- Keep bullets concise (1-2 lines), ATS-friendly, no tables.
- Make phrasing impact-first when possible; clarify why frameworks/processes matter (e.g., faster onboarding, standardization).
- Call out collaboration when evident (e.g., cross-functional teams, product/data/engineering).
- Avoid parenthetical tool lists; weave tools inline.
- Do NOT change or add tools/dates/companies beyond what is plausible for the existing roles."""

# Metric limiter and phrasing de-dupe
_END_CLIP = re.compile(r"(by\s+~?\d+%|by\s+~?\d+\s*(ms|s|minutes|hours)|by\s+~?\d+\s*(requests|users|pipelines))", re.IGNORECASE)
_METRIC_RANGE = re.compile(
    r"~?\d+(?:\.\d+)?\s*[–-]\s*~?\d+(?:\.\d+)?\s*(%|ms|s|sec|seconds|minutes|hours)",
    re.IGNORECASE,
)
_METRIC_TOKEN = re.compile(
    r"~?\d+(?:\.\d+)?\s*(%|ms|s|sec|seconds|minutes|hours|x|times|tps|rps|req/s|requests/sec|requests/s|users|pipelines|jobs|tickets|incidents)",
    re.IGNORECASE,
)
_DANGLING_METRIC = re.compile(r"\bby\s+~%|\b~%|~–%", re.IGNORECASE)
_DANGLING_ESTIMATE = re.compile(
    r"\b(using\s+estimated|using\s+an?\s+estimated|by\s+estimated|by\s+an?\s+estimated)\b(?!\s*~?\d)",
    re.IGNORECASE,
)
_LONE_ESTIMATE = re.compile(r"\bestimated\b(?!\s*~?\d)", re.IGNORECASE)
_TILDE_NO_NUMBER = re.compile(r"~\s*(%|ms|s|sec|seconds|minutes|hours)\b", re.IGNORECASE)
_PARENS = re.compile(r"\(([^()]+)\)")
_P_RESPONSE_TIMES = re.compile(r"\bp\s+response\s+times\b", re.IGNORECASE)
_P_RESPONSE = re.compile(r"\bp\s+response\b", re.IGNORECASE)
_S_TRIGGERS = re.compile(r"\band\s+S\s+triggers\b", re.IGNORECASE)
_HEDGE_WORDS = re.compile(r"\b(estimated|likely|approximately|about)\b", re.IGNORECASE)
_BULLET_LINE = re.compile(r"^\s*[-*\u2022]\s+")
_TILDE_CHARS = re.compile(r"[~∼˜～]")
_MAX_METRICS_PER_ROLE = 6  # cap metrics; excess will be converted to qualitative outcomes
_METRIC_PHRASE_PATTERNS = (
    re.compile(
        r"\bby\s+an?\s+estimated\s+~?\d+(?:\.\d+)?(?:\s*[–-]\s*~?\d+(?:\.\d+)?)?\s*(?:%|ms|s|sec|seconds|minutes|hours|x|times)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bestimated\s+~?\d+(?:\.\d+)?(?:\s*[–-]\s*~?\d+(?:\.\d+)?)?\s*(?:%|ms|s|sec|seconds|minutes|hours|x|times)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bby\s+~?\d+(?:\.\d+)?(?:\s*[–-]\s*~?\d+(?:\.\d+)?)?\s*(?:%|ms|s|sec|seconds|minutes|hours|x|times)\b",
        re.IGNORECASE,
    ),
    re.compile(r"~?\d+(?:\.\d+)?\s*[–-]\s*~?\d+(?:\.\d+)?\s*%", re.IGNORECASE),
    re.compile(r"~?\d+(?:\.\d+)?\s*%", re.IGNORECASE),
)


def _strip_tilde_symbols(text: str) -> str:
    return _TILDE_CHARS.sub("", text)


def _line_has_metric(line: str) -> bool:
    return bool(_END_CLIP.search(line) or _METRIC_RANGE.search(line) or _METRIC_TOKEN.search(line))


def _soften_metric_phrase(line: str, qualitative: bool = False) -> str:
    softened = line
    for pattern in _METRIC_PHRASE_PATTERNS:
        softened = pattern.sub("", softened)
    softened = _DANGLING_ESTIMATE.sub("", softened)
    softened = _LONE_ESTIMATE.sub("", softened)
    softened = _DANGLING_METRIC.sub("", softened)
    softened = _TILDE_NO_NUMBER.sub("", softened)
    softened = re.sub(r"\s+by\s*$", "", softened, flags=re.IGNORECASE)
    softened = re.sub(r"\s{2,}", " ", softened).rstrip(" ,.;:-")
    if qualitative:
        # Ensure a meaningful, non-numeric benefit remains.
        if softened.strip():
            softened = softened.rstrip(" ,.;:-")
            if not re.search(r"(reliab|stabil|quality|accuracy|freshness|risk|uptime|sla)", softened, re.IGNORECASE):
                softened = softened + " improving reliability and consistency"
    return softened


def _postprocess_metrics_and_phrasing(resume_text: str) -> str:
    """Keep at most 4 numeric metrics per role and remove tilde characters."""
    lines = resume_text.splitlines()
    out: list[str] = []
    metric_count = 0
    role_buffer: list[str] = []

    def flush_role():
        nonlocal role_buffer, out
        if not role_buffer:
            return
        metrics = []
        non_metrics = []
        for b in role_buffer:
            if _line_has_metric(b.strip()):
                metrics.append(b)
            else:
                non_metrics.append(b)
        interleaved: list[str] = []
        i = j = 0
        while i < len(metrics) or j < len(non_metrics):
            if i < len(metrics):
                interleaved.append(metrics[i]); i += 1
            if j < len(non_metrics):
                interleaved.append(non_metrics[j]); j += 1
        out.extend(interleaved)
        role_buffer = []

    for raw_line in lines:
        line = _strip_tilde_symbols(raw_line)
        stripped = line.strip()

        if not stripped:
            flush_role()
            out.append(line)
            continue

        if not _BULLET_LINE.match(stripped):
            metric_count = 0
            flush_role()
            out.append(line)
            continue

        bullet = line
        if _line_has_metric(stripped):
            metric_count += 1
            if _MAX_METRICS_PER_ROLE and metric_count > _MAX_METRICS_PER_ROLE:
                bullet = _soften_metric_phrase(bullet, qualitative=True)

        bullet = _DANGLING_ESTIMATE.sub("", bullet)
        bullet = _LONE_ESTIMATE.sub("", bullet)
        bullet = _DANGLING_METRIC.sub("", bullet)
        bullet = _TILDE_NO_NUMBER.sub("", bullet)
        bullet = _P_RESPONSE_TIMES.sub("p95 response times", bullet)
        bullet = _P_RESPONSE.sub("p95 response", bullet)
        bullet = _S_TRIGGERS.sub("and S3 triggers", bullet)
        bullet = _HEDGE_WORDS.sub("", bullet)
        if "(" in bullet and ")" in bullet:
            bullet = _PARENS.sub(lambda m: "using " + m.group(1), bullet)
        bullet = re.sub(r"\s{2,}", " ", bullet).rstrip(" ,.;:-")
        bullet = re.sub(r"^\s*[-*\u2022]\s*", "- ", bullet)
        out.append(bullet)

    return "\n".join(out)


_TOOL_KEYWORDS = [
    "dbt",
    "airflow",
    "kafka",
    "rag",
    "llm",
    "embedding",
    "embeddings",
    "vector",
    "semantic search",
    "spark",
    "pyspark",
    "spark sql",
    "databricks",
    "delta lake",
    "azure",
    "aws",
    "gcp",
    "mlflow",
    "monte carlo",
    "collibra",
    "postgresql",
    "sql server",
    "snowflake",
    "docker",
    "kubernetes",
    "lambda",
    "sqs",
    "sns",
    "kinesis",
    "oauth2",
    "jwt",
    "fastapi",
    "node.js",
    "express",
    "react",
    "grafana",
    "prometheus",
    "cloudwatch",
    "azure devops",
    "git",
    "dabs",
]


def _extract_tools_from_chunks(chunks: list[dict]) -> list[str]:
    found = []
    text_all = " ".join([c.get("text", "") for c in chunks]).lower()
    for tool in _TOOL_KEYWORDS:
        if tool in text_all:
            found.append(tool)
    return found


def _sync_skills(resume_text: str, chunks: list[dict], jd_text: str | None = None) -> str:
    """Skip adding catch-all Additional Tools; rely on existing skills plus JD-prioritized adds inline."""
    return resume_text


def _polish_resume(resume_text: str, jd_text: str | None = None) -> str:
    """Second-pass polish to add impact/metrics and vary phrasing."""
    user_prompt = f"""JOB DESCRIPTION (for alignment, optional):
{jd_text or ''}

RESUME DRAFT (rewrite to improve impact/metrics, keep headers/roles intact):
{resume_text}

TASK:
Rewrite the resume draft improving impact statements and metrics while keeping facts about companies/titles/dates intact.
Return the full resume text."""
    try:
        return generate_with_llm(
            system_prompt=POLISH_SYSTEM,
            user_prompt=user_prompt,
            max_tokens=2000,
            temperature=0.3,
            provider=settings.llm_provider,
        )
    except Exception as exc:
        logger.warning("Polish pass failed; returning original. %s", exc)
        return resume_text


def _audit_resume(resume_text: str, retrieved_chunks: list[dict]) -> ResumeAudit:
    """Run a lightweight Claude audit to flag unsupported claims."""
    context_lines = []
    for chunk in retrieved_chunks:
        context_lines.append(
            f"- ({chunk['resume_type']} | {chunk['source_file']}) {chunk['text']}"
        )
    context = "\n".join(context_lines)

    system_prompt = (
        "You are a strict resume auditor. Return ONLY valid JSON with no extra text."
    )
    user_prompt = (
        f"RESUME:\n{resume_text}\n\n"
        f"CONTEXT SNIPPETS:\n{context}\n\n"
        "Rules:\n"
        "- Flag any resume claim not directly supported by snippets.\n"
        "- If resume claims clinical trial lifecycle terms (clinical trial, study, protocol, eCRF/CRF, DMP, DVP, EDC, GCP)\n"
        "  but those terms do NOT appear in snippets, list them under unsupported_claims.\n"
        "- If JD must-haves appear in the resume but are not supported, list them under risky_phrases.\n"
        "- If JD must-have terms are missing from snippets entirely, list them under missing_must_haves.\n\n"
        "Return ONLY valid JSON in this schema:\n"
        '{\n'
        '  "unsupported_claims": ["..."],\n'
        '  "risky_phrases": ["..."],\n'
        '  "missing_must_haves": ["..."]\n'
        '}\n'
        "JD must-have terms to check: clinical trial, study, protocol, eCRF, CRF, DMP, DVP, EDC, GCP\n"
    )

    raw = generate_with_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=400,
        temperature=0.0,
        provider=settings.llm_provider,
    )
    unsupported_claims: list[str] = []
    risky_phrases: list[str] = []
    missing_must_haves: list[str] = []

    try:
        data = json.loads(raw)
        unsupported_claims = data.get("unsupported_claims", []) or []
        risky_phrases = data.get("risky_phrases", []) or []
        missing_must_haves = data.get("missing_must_haves", []) or []
    except json.JSONDecodeError:
        unsupported_claims = []
        risky_phrases = []
        missing_must_haves = []

    unsupported_claims = [str(item).strip() for item in unsupported_claims if str(item).strip()]
    risky_phrases = [str(item).strip() for item in risky_phrases if str(item).strip()]
    missing_must_haves = [str(item).strip() for item in missing_must_haves if str(item).strip()]

    return ResumeAudit(
        unsupported_claims=unsupported_claims,
        risky_phrases=risky_phrases,
        missing_must_haves=missing_must_haves,
    )


def _parse_bool(value: str) -> bool:
    return value.strip().lower() == "true"


def _recover_payload_from_invalid_json(raw_text: str) -> dict:
    """Best-effort recovery when JSON contains unescaped newlines."""
    data: dict = {}

    jd_match = re.search(
        r'"jd_text"\s*:\s*"(.*)"\s*,\s*"(top_k|multi_query|parse_with_claude|audit|domain_rewrite|target_company_type|bullets_per_role|use_experience_inventory|max_roles)"',
        raw_text,
        re.DOTALL,
    )
    if jd_match:
        data["jd_text"] = jd_match.group(1)
    else:
        data["jd_text"] = raw_text.strip()

    top_k_match = re.search(r'"top_k"\s*:\s*(\d+)', raw_text)
    if top_k_match:
        data["top_k"] = int(top_k_match.group(1))

    bullets_match = re.search(r'"bullets_per_role"\s*:\s*(\d+)', raw_text)
    if bullets_match:
        data["bullets_per_role"] = int(bullets_match.group(1))

    max_roles_match = re.search(r'"max_roles"\s*:\s*(\d+)', raw_text)
    if max_roles_match:
        data["max_roles"] = int(max_roles_match.group(1))

    for key in ["multi_query", "parse_with_claude", "audit", "domain_rewrite", "use_experience_inventory"]:
        match = re.search(rf'"{key}"\s*:\s*(true|false)', raw_text, re.IGNORECASE)
        if match:
            data[key] = _parse_bool(match.group(1))

    target_match = re.search(r'"target_company_type"\s*:\s*"([^"]*)"', raw_text)
    if target_match:
        data["target_company_type"] = target_match.group(1)

    return data


@router.post(
    "/generate",
    response_model=GenerateResponse,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "jd_text": {"type": "string"},
                            "top_k": {"type": "integer", "default": 25},
                            "multi_query": {"type": "boolean", "default": False},
                            "parse_with_claude": {"type": "boolean", "default": False},
                            "audit": {"type": "boolean", "default": False},
                            "domain_rewrite": {"type": "boolean", "default": False},
                            "target_company_type": {"type": ["string", "null"]},
                            "bullets_per_role": {"type": "integer", "default": 15},
                            "use_experience_inventory": {"type": "boolean", "default": True},
                            "max_roles": {"type": ["integer", "null"]},
                        },
                        "required": ["jd_text"],
                    },
                    "example": {
                        "jd_text": "Paste job description here",
                        "top_k": 25,
                        "multi_query": False,
                        "parse_with_claude": False,
                        "audit": False,
                        "domain_rewrite": False,
                        "target_company_type": "enterprise",
                        "bullets_per_role": 15,
                        "use_experience_inventory": True,
                        "max_roles": None,
                    },
                }
            },
        }
    },
)
async def generate(request: Request) -> GenerateResponse:
    body = await request.body()
    content_type = request.headers.get("content-type", "")
    data = {}
    if body:
        if "application/json" in content_type:
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                text = body.decode("utf-8", errors="ignore")
                data = _recover_payload_from_invalid_json(text)
        else:
            text = body.decode("utf-8", errors="ignore").strip()
            data = {"jd_text": text}

    try:
        req = GenerateRequest(**data)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())

    if not index_exists(settings.index_dir):
        raise HTTPException(status_code=400, detail="Index not found. Upload resumes or call /reindex first.")

    structured_jd = None
    jd_provider = settings.llm_provider
    jd_api_key = settings.openai_api_key if jd_provider.lower() == "openai" else settings.anthropic_api_key
    jd_model = settings.openai_model if jd_provider.lower() == "openai" else settings.claude_model

    needs_structured = (
        req.multi_query
        or req.parse_with_claude
        or req.domain_rewrite
        or bool(req.target_company_type)
    )
    if needs_structured:
        structured_jd = parse_jd(
            jd_text=req.jd_text,
            api_key=jd_api_key,
            model=jd_model,
            use_claude=req.parse_with_claude,
            provider=jd_provider,
        ).model_dump()

    retrieved = retrieve_topk(
        jd_text=req.jd_text,
        index_dir=settings.index_dir,
        embed_model_name=settings.embed_model,
        k=req.top_k,
        multi_query=req.multi_query,
        structured_jd=structured_jd,
    )

    context_chunks = retrieved
    skill_grades = None
    if req.domain_rewrite or req.target_company_type:
        deduped = dedupe_chunks(retrieved, settings.embed_model)
        context_chunks = rewrite_chunks(
            deduped,
            structured_jd.get("domain") if structured_jd else None,
            req.target_company_type,
        )
        skill_grades = grade_skills(structured_jd, context_chunks)

    if skill_grades is None:
        structured_for_skills = structured_jd or parse_jd(
            jd_text=req.jd_text,
            api_key=jd_api_key,
            model=jd_model,
            use_claude=False,
            provider=jd_provider,
        ).model_dump()
        skill_grades = grade_skills(structured_for_skills, context_chunks)

    experience_inventory = None
    if req.use_experience_inventory:
        experience_inventory = extract_experience_inventory(settings.resumes_dir)

    role_headers = None
    master_resume = select_master_resume(settings.resumes_dir)
    if master_resume:
        master_text = read_text(master_resume)
        if master_text:
            role_headers = extract_experience_headers(master_text)

    user_prompt = build_user_prompt(
        req.jd_text,
        context_chunks,
        skill_grades=skill_grades,
        experience_inventory=experience_inventory,
        bullets_per_role=req.bullets_per_role,
        max_roles=req.max_roles,
        role_headers=role_headers,
    )

    try:
        resume_text = generate_with_llm(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=3200,
            temperature=0.35,
            provider=settings.llm_provider,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"LLM generation failed: {exc}")

    parsed_state = None
    try:
        parsed_state = parse_resume_text_to_state(resume_text)
        enforce_outcome_clauses(parsed_state, req.jd_text, structured_jd)
        resume_text = render_resume_text(parsed_state)
        resume_text = _polish_resume(resume_text, req.jd_text)
        resume_text = _postprocess_metrics_and_phrasing(resume_text)
        resume_text = _sync_skills(resume_text, context_chunks, req.jd_text)
    except Exception as exc:
        logger.warning("Outcome enforcement failed: %s", exc)

    audit = _audit_resume(resume_text, retrieved) if req.audit else None
    resume_text = _strip_tilde_symbols(resume_text)

    resume_id = None
    try:
        # Re-parse after cleanup so stored state/preview matches returned text.
        state = parse_resume_text_to_state(resume_text)
        resume_id = _new_resume_id(settings.generated_resumes_dir)
        init_resume_record(
            settings.generated_resumes_dir,
            resume_id,
            state,
            resume_text,
            jd_text=req.jd_text,
            source="generate",
        )
    except Exception as exc:
        logger.warning("Failed to store resume state: %s", exc)

    return GenerateResponse(
        model=(
            settings.claude_model
            if settings.llm_provider.lower() == "anthropic"
            else settings.openai_model
        ),
        top_k=req.top_k,
        retrieved=[RetrievedChunk(**r) for r in context_chunks],
        resume_text=resume_text,
        audit=audit,
        resume_id=resume_id,
    )


def _new_resume_id(root_dir) -> str:
    while True:
        candidate = uuid4().hex
        if not (root_dir / candidate).exists():
            return candidate
