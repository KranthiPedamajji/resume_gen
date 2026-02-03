from fastapi import APIRouter, HTTPException, Request
from pathlib import Path
import json
import re
import logging
from uuid import uuid4
from pydantic import ValidationError

from app.config import settings
from app.models.schemas import ExportDocxRequest, ExportDocxResponse, ExportDocxFromTextRequest
from app.routers.generate import _audit_resume
from app.services.indexing import index_exists
from app.services.retrieval import retrieve_topk
from app.services.prompts import SYSTEM_PROMPT, build_user_prompt
from app.services.llm_client import generate_with_llm
from app.services.jd_parser import parse_jd
from app.services.domain_rewriter import rewrite_chunks, dedupe_chunks, grade_skills
from app.services.experience_inventory import extract_experience_inventory
from app.services.master_resume import select_master_resume, extract_experience_headers
from app.services.parsing import read_text
from app.services.docx_exporter import (
    build_output_paths,
    export_resume_to_docx,
    parse_sections_from_resume_text,
    sanitize_name,
    export_docx_from_state,
)
from app.services.resume_state import parse_resume_text_to_state, render_resume_text
from app.services.outcome_enforcer import enforce_outcome_clauses
from app.services.resume_store import (
    init_resume_record,
    append_resume_version,
    update_version_docx_path,
    load_latest_state,
)

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


def _get_template_path() -> Path:
    template_path = Path(settings.docx_template_path)
    if template_path.exists():
        return template_path
    raise HTTPException(
        status_code=400,
        detail=(
            "DOCX template not found. Put template at storage/resumes/template/template.docx"
        ),
    )


def _parse_bool(value: str) -> bool:
    return value.strip().lower() == "true"


def _recover_payload_from_invalid_json(raw_text: str) -> dict:
    """Best-effort recovery when JSON contains unescaped newlines."""
    data: dict = {}

    jd_match = re.search(
        r'"jd_text"\s*:\s*"(.*)"\s*,\s*"(resume_id|top_k|multi_query|parse_with_claude|audit|domain_rewrite|target_company_type|company_name|position_name|job_id|resume_text|bullets_per_role|use_experience_inventory|max_roles)"',
        raw_text,
        re.DOTALL,
    )
    if jd_match:
        data["jd_text"] = jd_match.group(1)

    for key in ["resume_id", "company_name", "position_name", "job_id", "target_company_type"]:
        match = re.search(rf'"{key}"\s*:\s*"([^"]*)"', raw_text)
        if match:
            data[key] = match.group(1)

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

    resume_match = re.search(r'"resume_text"\s*:\s*"(.*)"\s*}', raw_text, re.DOTALL)
    if resume_match:
        data["resume_text"] = resume_match.group(1)

    return data


def _save_export_artifacts(
    company_name: str,
    position_name: str,
    job_id: str | None,
    jd_text: str,
    resume_text: str,
) -> tuple[ExportDocxResponse, Path]:
    output_dir = build_output_paths(company_name, position_name, job_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    jd_path = output_dir / "Job_description.txt"
    jd_path.write_text(jd_text, encoding="utf-8")

    sections = parse_sections_from_resume_text(resume_text)
    template_path = _get_template_path()
    docx_path = output_dir / f"{sanitize_name(position_name)}.docx"
    export_resume_to_docx(template_path, sections, docx_path)

    return (
        ExportDocxResponse(
            saved_dir=str(output_dir.as_posix()),
            resume_docx_path=str(docx_path.as_posix()),
            jd_path=str(jd_path.as_posix()),
            audit=None,
        ),
        docx_path,
    )


@router.post(
    "/export-docx",
    response_model=ExportDocxResponse,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "resume_id": {"type": ["string", "null"]},
                            "company_name": {"type": "string"},
                            "position_name": {"type": "string"},
                            "job_id": {"type": ["string", "null"]},
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
                        "required": [],
                    },
                    "example": {
                        "resume_id": None,
                        "company_name": "Citius",
                        "position_name": "software engineer",
                        "job_id": "Jb12345",
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
async def export_docx(request: Request) -> ExportDocxResponse:
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
        payload = ExportDocxRequest(**data)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())

    if payload.resume_id:
        resume_id = payload.resume_id
        try:
            state, _ = load_latest_state(settings.generated_resumes_dir, resume_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="resume_id not found")

        meta = append_resume_version(
            settings.generated_resumes_dir,
            resume_id,
            state,
            jd_text=payload.jd_text if payload.jd_text else None,
        )
        version = meta.get("latest_version")
        version_dir = settings.generated_resumes_dir / resume_id / version

        template_path = _get_template_path()
        version_docx = version_dir / "resume.docx"
        export_docx_from_state(state, template_path, version_docx)
        update_version_docx_path(settings.generated_resumes_dir, resume_id, version, version_docx)

        internal_jd_path = _version_entry_path(meta, version, "job_description")
        if internal_jd_path and not Path(internal_jd_path).exists():
            internal_jd_path = None
        if not internal_jd_path:
            candidate = version_dir / "job_description.txt"
            if candidate.exists():
                internal_jd_path = str(candidate.as_posix())

        saved_dir = str(version_dir.as_posix())
        resume_docx_path = str(version_docx.as_posix())
        jd_path = internal_jd_path or ""
        final_saved_dir = None
        final_resume_docx_path = None
        final_jd_path = None
        if payload.company_name and payload.position_name:
            output_dir = build_output_paths(payload.company_name, payload.position_name, payload.job_id)
            output_dir.mkdir(parents=True, exist_ok=True)
            if payload.jd_text:
                (output_dir / "Job_description.txt").write_text(payload.jd_text, encoding="utf-8")
            override_docx = output_dir / f"{sanitize_name(payload.position_name)}.docx"
            export_docx_from_state(state, template_path, override_docx)
            final_saved_dir = str(output_dir.as_posix())
            final_resume_docx_path = str(override_docx.as_posix())
            final_jd_path = str((output_dir / "Job_description.txt").as_posix()) if payload.jd_text else None
            saved_dir = final_saved_dir
            resume_docx_path = final_resume_docx_path
            jd_path = final_jd_path or jd_path

        return ExportDocxResponse(
            saved_dir=saved_dir,
            resume_docx_path=resume_docx_path,
            jd_path=jd_path,
            audit=None,
            resume_id=resume_id,
            version=version,
            internal_version_dir=str(version_dir.as_posix()),
            internal_resume_docx_path=str(version_docx.as_posix()),
            internal_jd_path=internal_jd_path,
            final_saved_dir=final_saved_dir,
            final_resume_docx_path=final_resume_docx_path,
            final_jd_path=final_jd_path,
        )

    if not index_exists(settings.index_dir):
        raise HTTPException(status_code=400, detail="Index not found. Upload resumes or call /reindex first.")

    structured_jd = None
    needs_structured = (
        payload.multi_query
        or payload.parse_with_claude
        or payload.domain_rewrite
        or bool(payload.target_company_type)
    )
    if needs_structured:
        jd_provider = settings.llm_provider
        jd_api_key = (
            settings.openai_api_key if jd_provider.lower() == "openai" else settings.anthropic_api_key
        )
        jd_model = (
            settings.openai_model if jd_provider.lower() == "openai" else settings.claude_model
        )
        structured_jd = parse_jd(
            jd_text=payload.jd_text,
            api_key=jd_api_key,
            model=jd_model,
            use_claude=payload.parse_with_claude,
            provider=jd_provider,
        ).model_dump()

    retrieved = retrieve_topk(
        jd_text=payload.jd_text,
        index_dir=settings.index_dir,
        embed_model_name=settings.embed_model,
        k=payload.top_k,
        multi_query=payload.multi_query,
        structured_jd=structured_jd,
    )

    context_chunks = retrieved
    skill_grades = None
    if payload.domain_rewrite or payload.target_company_type:
        deduped = dedupe_chunks(retrieved, settings.embed_model)
        context_chunks = rewrite_chunks(
            deduped,
            structured_jd.get("domain") if structured_jd else None,
            payload.target_company_type,
        )
        skill_grades = grade_skills(structured_jd, context_chunks)

    if skill_grades is None:
        structured_for_skills = structured_jd or parse_jd(
            jd_text=payload.jd_text,
            api_key=jd_api_key,
            model=jd_model,
            use_claude=False,
            provider=jd_provider,
        ).model_dump()
        skill_grades = grade_skills(structured_for_skills, context_chunks)

    experience_inventory = None
    if payload.use_experience_inventory:
        experience_inventory = extract_experience_inventory(settings.resumes_dir)

    role_headers = None
    master_resume = select_master_resume(settings.resumes_dir)
    if master_resume:
        master_text = read_text(master_resume)
        if master_text:
            role_headers = extract_experience_headers(master_text)

    user_prompt = build_user_prompt(
        payload.jd_text,
        context_chunks,
        skill_grades=skill_grades,
        experience_inventory=experience_inventory,
        bullets_per_role=payload.bullets_per_role,
        max_roles=payload.max_roles,
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
        resume_text = _polish_resume(resume_text, payload.jd_text)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"LLM generation failed: {exc}")

    parsed_state = None
    try:
        parsed_state = parse_resume_text_to_state(resume_text)
        enforce_outcome_clauses(parsed_state, payload.jd_text, structured_jd)
        resume_text = render_resume_text(parsed_state)
        resume_text = _postprocess_metrics_and_phrasing(resume_text)
        resume_text = _sync_skills(resume_text, context_chunks, payload.jd_text)
    except Exception as exc:
        logger.warning("Outcome enforcement failed: %s", exc)

    resume_text = _strip_tilde_symbols(resume_text)

    result, docx_path = _save_export_artifacts(
        payload.company_name,
        payload.position_name,
        payload.job_id,
        payload.jd_text,
        resume_text,
    )

    if payload.audit:
        result.audit = _audit_resume(resume_text, retrieved)

    try:
        # Re-parse after cleanup so stored state/preview matches exported text.
        state = parse_resume_text_to_state(resume_text)
        resume_id = _new_resume_id(settings.generated_resumes_dir)
        init_resume_record(
            settings.generated_resumes_dir,
            resume_id,
            state,
            resume_text,
            jd_text=payload.jd_text,
            resume_docx_path=docx_path,
            source="export-docx",
        )
        result.resume_id = resume_id
        result.version = "v1"
    except Exception as exc:
        logger.warning("Failed to store resume state: %s", exc)

    return result


@router.post(
    "/export-docx-from-text",
    response_model=ExportDocxResponse,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "company_name": {"type": "string"},
                            "position_name": {"type": "string"},
                            "job_id": {"type": ["string", "null"]},
                            "jd_text": {"type": "string"},
                            "resume_text": {"type": "string"},
                        },
                        "required": ["company_name", "position_name", "jd_text", "resume_text"],
                    },
                    "example": {
                        "company_name": "Citius",
                        "position_name": "software engineer",
                        "job_id": "Jb12345",
                        "jd_text": "Paste job description here",
                        "resume_text": "Paste the resume_text from /generate here",
                    },
                }
            },
        }
    },
)
async def export_docx_from_text(request: Request) -> ExportDocxResponse:
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
        payload = ExportDocxFromTextRequest(**data)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())

    result, _ = _save_export_artifacts(
        payload.company_name,
        payload.position_name,
        payload.job_id,
        payload.jd_text,
        payload.resume_text,
    )
    return result


def _new_resume_id(root_dir) -> str:
    while True:
        candidate = uuid4().hex
        if not (root_dir / candidate).exists():
            return candidate


def _version_entry_path(meta: dict, version: str, key: str) -> str | None:
    for entry in meta.get("versions", []):
        if entry.get("version") == version:
            path = entry.get(key)
            return path
    return None
