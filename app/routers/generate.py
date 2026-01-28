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
from app.services.claude_client import generate_with_claude
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

    raw = generate_with_claude(
        api_key=settings.anthropic_api_key,
        model=settings.claude_model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=400,
        temperature=0.0,
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
    needs_structured = (
        req.multi_query
        or req.parse_with_claude
        or req.domain_rewrite
        or bool(req.target_company_type)
    )
    if needs_structured:
        structured_jd = parse_jd(
            jd_text=req.jd_text,
            api_key=settings.anthropic_api_key,
            model=settings.claude_model,
            use_claude=req.parse_with_claude,
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
            api_key=settings.anthropic_api_key,
            model=settings.claude_model,
            use_claude=False,
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
        resume_text = generate_with_claude(
            api_key=settings.anthropic_api_key,
            model=settings.claude_model,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=2500,
            temperature=0.2,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Claude generation failed: {exc}")

    parsed_state = None
    try:
        parsed_state = parse_resume_text_to_state(resume_text)
        enforce_outcome_clauses(parsed_state, req.jd_text, structured_jd)
        resume_text = render_resume_text(parsed_state)
    except Exception as exc:
        logger.warning("Outcome enforcement failed: %s", exc)

    audit = _audit_resume(resume_text, retrieved) if req.audit else None

    resume_id = None
    try:
        state = parsed_state or parse_resume_text_to_state(resume_text)
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
        model=settings.claude_model,
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
