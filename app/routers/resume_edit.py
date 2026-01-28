from fastapi import APIRouter, HTTPException
from pathlib import Path
import re

from app.config import settings
from app.models.schemas import BulletEditRequest, BulletEditResponse, ResumeStateResponse, BulletRewriteRequest, BulletRewriteResponse
from app.services.resume_store import (
    load_resume_state,
    append_resume_version,
    update_version_docx_path,
    load_latest_jd_text,
)
from app.services.resume_overrides import load_overrides
from app.services.docx_exporter import export_docx_from_state
from app.services.claude_client import generate_with_claude
from app.services.prompts import BULLET_REWRITE_SYSTEM_PROMPT, build_bullet_rewrite_prompt
from app.services.outcome_enforcer import ensure_outcome_clause


router = APIRouter()


@router.get("/resumes/{resume_id}", response_model=ResumeStateResponse)
def get_resume(resume_id: str) -> ResumeStateResponse:
    try:
        state, version = load_resume_state(settings.generated_resumes_dir, resume_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="resume_id not found")

    jd_text = load_latest_jd_text(settings.generated_resumes_dir, resume_id)

    return ResumeStateResponse(resume_id=resume_id, version=version, state=state, jd_text=jd_text)


@router.patch("/resumes/{resume_id}/bullet", response_model=BulletEditResponse)
def edit_bullet(resume_id: str, payload: BulletEditRequest) -> BulletEditResponse:
    try:
        state, _ = load_resume_state(settings.generated_resumes_dir, resume_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="resume_id not found")

    role_index = _select_role_index(state.sections.experience, payload.role_selector)
    role = state.sections.experience[role_index]

    if payload.bullet_index < 0 or payload.bullet_index >= len(role.bullets):
        raise HTTPException(status_code=422, detail="bullet_index out of range")

    cleaned = _clean_bullet(payload.new_bullet)
    if not cleaned:
        raise HTTPException(status_code=422, detail="new_bullet is invalid")

    jd_text = load_latest_jd_text(settings.generated_resumes_dir, resume_id) or ""
    role.bullets[payload.bullet_index] = ensure_outcome_clause(cleaned, jd_text)

    meta = append_resume_version(
        settings.generated_resumes_dir,
        resume_id,
        state,
    )
    version = meta.get("latest_version")
    version_dir = settings.generated_resumes_dir / resume_id / version
    resume_docx_path = None

    if payload.export_docx:
        template_path = Path(settings.docx_template_path)
        if not template_path.exists():
            raise HTTPException(
                status_code=400,
                detail="DOCX template not found. Put template at storage/resumes/template/template.docx",
            )
        resume_docx_path = version_dir / "resume.docx"
        export_docx_from_state(state, template_path, resume_docx_path)
        update_version_docx_path(settings.generated_resumes_dir, resume_id, version, resume_docx_path)

    return BulletEditResponse(
        resume_id=resume_id,
        version=version,
        updated_role={
            "role_id": role.role_id,
            "company": role.company,
            "title": role.title,
            "dates": role.dates,
        },
        updated_bullet_index=payload.bullet_index,
        paths={
            "resume_json": str((version_dir / "resume.json").as_posix()),
            "resume_docx": str(resume_docx_path.as_posix()) if resume_docx_path else None,
        },
    )



@router.post("/resumes/{resume_id}/rewrite-bullet", response_model=BulletRewriteResponse)
def rewrite_bullet(resume_id: str, payload: BulletRewriteRequest) -> BulletRewriteResponse:
    try:
        state, _ = load_resume_state(settings.generated_resumes_dir, resume_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="resume_id not found")

    role_index = _select_role_index(state.sections.experience, payload.role_selector)
    role = state.sections.experience[role_index]

    if payload.bullet_index < 0 or payload.bullet_index >= len(role.bullets):
        raise HTTPException(status_code=422, detail="bullet_index out of range")

    original_bullet = role.bullets[payload.bullet_index]
    neighbors = []
    if payload.bullet_index - 1 >= 0:
        neighbors.append(role.bullets[payload.bullet_index - 1])
    if payload.bullet_index + 1 < len(role.bullets):
        neighbors.append(role.bullets[payload.bullet_index + 1])

    role_info = {
        "company": role.company,
        "title": role.title or "",
        "location": role.location or "",
        "dates": role.dates or "",
    }

    rewrite_hint = (payload.rewrite_hint or "").strip()
    allowed_additions = []
    if rewrite_hint:
        override_skill = (payload.override_skill or "").strip()
        if not override_skill:
            raise HTTPException(status_code=422, detail="override_skill is required when rewrite_hint is provided")
        overrides = load_overrides(settings.generated_resumes_dir, resume_id)
        if not overrides or not overrides.skills:
            raise HTTPException(status_code=422, detail="No overrides found for resume_id")
        override_names = {entry.skill.strip().lower() for entry in overrides.skills}
        if override_skill.lower() not in override_names:
            raise HTTPException(status_code=422, detail="override_skill not found in overrides")
        allowed_additions = [override_skill]

    user_prompt = build_bullet_rewrite_prompt(
        payload.jd_text,
        role_info,
        original_bullet,
        neighbor_bullets=neighbors,
        rewrite_hint=rewrite_hint or None,
        allowed_additions=allowed_additions,
    )

    try:
        rewritten = generate_with_claude(
            api_key=settings.anthropic_api_key,
            model=settings.claude_model,
            system_prompt=BULLET_REWRITE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=160,
            temperature=payload.temperature,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Claude rewrite failed: {exc}")

    cleaned = _clean_bullet(rewritten)
    if not cleaned:
        cleaned = original_bullet
    else:
        jd_text = (payload.jd_text or load_latest_jd_text(settings.generated_resumes_dir, resume_id) or "")
        cleaned = ensure_outcome_clause(cleaned, jd_text)

    return BulletRewriteResponse(
        resume_id=resume_id,
        role_id=role.role_id,
        bullet_index=payload.bullet_index,
        original_bullet=original_bullet,
        rewritten_bullet=cleaned,
    )


def _select_role_index(roles, selector) -> int:
    role_id = (selector.role_id or "").strip()
    company = (selector.company or "").strip()
    dates = (selector.dates or "").strip()

    if role_id:
        for idx, role in enumerate(roles):
            if role.role_id == role_id:
                return idx
        raise HTTPException(status_code=404, detail="role_id not found")

    if not company or not dates:
        raise HTTPException(status_code=422, detail="Provide role_id or company + dates")

    matches = [
        idx for idx, role in enumerate(roles)
        if role.company.strip().lower() == company.lower()
        and (role.dates or "").strip().lower() == dates.lower()
    ]

    if not matches:
        raise HTTPException(status_code=404, detail="role not found for company + dates")
    if len(matches) > 1:
        role_ids = [roles[idx].role_id for idx in matches]
        raise HTTPException(status_code=409, detail={"message": "multiple roles matched", "role_ids": role_ids})

    return matches[0]


def _clean_bullet(text: str) -> str:
    cleaned = text.replace("\t", " ").replace("\r", " ").replace("\n", " ")
    cleaned = re.sub(r"^\s*(?:[-•*]|\d+\.)\s+", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) < 10 or len(cleaned) > 300:
        return ""
    return cleaned




