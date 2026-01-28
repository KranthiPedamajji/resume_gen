from fastapi import APIRouter, HTTPException
import re
import logging

from app.config import settings
from app.models.schemas import (
    OverridesRequest,
    OverridesResponse,
    SuggestPatchesRequest,
    SuggestPatchesResponse,
    PatchOperation,
    ApplyPatchesRequest,
    ApplyPatchesResponse,
    IncludeSkillsRequest,
    IncludeSkillsResponse,
    OverrideSkill,
)
from app.services.resume_store import load_latest_state, append_resume_version, update_version_docx_path, load_latest_jd_text
from app.services.resume_overrides import save_overrides, load_overrides
from app.services.ats_scoring import score_resume_against_jd
from app.services.resume_patches import apply_patches_to_state, apply_truth_guardrails, validate_patches_truth_mode, proof_bullet_template
from pathlib import Path
from app.services.docx_exporter import export_docx_from_state
from app.services.prompts import BULLET_REWRITE_SYSTEM_PROMPT, build_bullet_rewrite_prompt
from app.services.claude_client import generate_with_claude
from app.services.outcome_enforcer import enforce_outcome_clauses, ensure_outcome_clause


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/resumes/{resume_id}/overrides", response_model=OverridesResponse)
def save_resume_overrides(resume_id: str, payload: OverridesRequest) -> OverridesResponse:
    _ensure_resume_exists(resume_id)
    path = save_overrides(settings.generated_resumes_dir, resume_id, payload)
    return OverridesResponse(resume_id=resume_id, overrides_path=str(path.as_posix()))


@router.post("/resumes/{resume_id}/suggest-patches", response_model=SuggestPatchesResponse)
def suggest_patches(resume_id: str, payload: SuggestPatchesRequest) -> SuggestPatchesResponse:
    state, _ = _load_state(resume_id)
    ats = score_resume_against_jd(payload.jd_text, state, strict_mode=payload.strict_mode)
    overrides = load_overrides(settings.generated_resumes_dir, resume_id) if payload.apply_overrides else None

    suggested: list[PatchOperation] = []
    inserts_per_role: dict[str, int] = {}
    tech_skill_added: set[str] = set()

    if overrides and overrides.skills:
        for entry in overrides.skills:
            skill = entry.skill
            if not skill:
                continue
            skill_key = skill.strip().lower()
            if skill_key and skill_key not in tech_skill_added and not _skill_in_technical_skills(state, skill):
                tech_patch = _build_technical_skill_patch(state, skill)
                if tech_patch:
                    suggested.append(tech_patch)
                tech_skill_added.add(skill_key)

            for role_id in entry.target_roles:
                if inserts_per_role.get(role_id, 0) >= 2:
                    continue
                role = _find_role(state, role_id)
                if not role:
                    continue
                if _role_has_skill(role, skill):
                    continue
                for proof in entry.proof_bullets:
                    if inserts_per_role.get(role_id, 0) >= 2:
                        break
                    rewritten = proof
                    if payload.rewrite_overrides_with_claude:
                        rewritten = _rewrite_override_bullet(
                            role=role,
                            skill=skill,
                            proof_bullet=proof,
                            jd_text=payload.jd_text,
                        )
                    suggested.append(
                        PatchOperation(
                            role_id=role_id,
                            section="experience",
                            action="insert",
                            after_index=len(role.bullets) - 1,
                            new_bullet=rewritten,
                            skill=skill,
                        )
                    )
                    inserts_per_role[role_id] = inserts_per_role.get(role_id, 0) + 1
        filtered, blocked = apply_truth_guardrails(
            suggested,
            ats,
            overrides,
            payload.truth_mode,
            state,
            jd_text=payload.jd_text,
        )
        return SuggestPatchesResponse(suggested_patches=filtered, blocked=blocked)

    for skill in ats.missing_required:
        override_entry = _find_override(overrides, skill) if overrides else None
        if override_entry:
            continue

        if _skill_already_present(state, skill):
            continue

        suggested.append(
            PatchOperation(
                section="technical_skills",
                action="insert",
                after_index=len(state.sections.technical_skills) - 1,
                new_bullet=f"Exposure to {skill}",
                skill=skill,
            )
        )

    filtered, blocked = apply_truth_guardrails(
        suggested,
        ats,
        overrides,
        payload.truth_mode,
        state,
        jd_text=payload.jd_text,
    )

    return SuggestPatchesResponse(suggested_patches=filtered, blocked=blocked)


@router.post("/resumes/{resume_id}/apply-patches", response_model=ApplyPatchesResponse)
def apply_patches(resume_id: str, payload: ApplyPatchesRequest) -> ApplyPatchesResponse:
    state, _ = _load_state(resume_id)
    overrides = load_overrides(settings.generated_resumes_dir, resume_id)

    try:
        validate_patches_truth_mode(payload.patches, state, overrides, payload.truth_mode)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        apply_patches_to_state(state, payload.patches)
    except (IndexError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    jd_text = load_latest_jd_text(settings.generated_resumes_dir, resume_id) or ""
    enforce_outcome_clauses(state, jd_text)

    meta = append_resume_version(settings.generated_resumes_dir, resume_id, state)
    version = meta.get("latest_version")
    version_dir = settings.generated_resumes_dir / resume_id / version
    resume_docx_path = None

    if payload.export_docx:
        template_path = Path(settings.docx_template_path)
        if not template_path.exists():
            raise HTTPException(status_code=400, detail="DOCX template not found")
        export_docx_from_state(state, template_path, version_dir / "resume.docx")
        resume_docx_path = version_dir / "resume.docx"
        update_version_docx_path(settings.generated_resumes_dir, resume_id, version, resume_docx_path)

    return ApplyPatchesResponse(
        resume_id=resume_id,
        version=version,
        paths={
            "resume_json": str((version_dir / "resume.json").as_posix()),
            "resume_docx": str(resume_docx_path.as_posix()) if resume_docx_path else None,
        },
    )


@router.post("/resumes/{resume_id}/include-skills", response_model=IncludeSkillsResponse)
def include_skills(resume_id: str, payload: IncludeSkillsRequest) -> IncludeSkillsResponse:
    state, _ = _load_state(resume_id)
    overrides = load_overrides(settings.generated_resumes_dir, resume_id) or OverridesRequest()

    for item in payload.items:
        if not _role_exists(state, item.role_id):
            raise HTTPException(status_code=422, detail=f"role_id not found: {item.role_id}")

        proof = (item.proof_bullet or "").strip()
        cleaned = _clean_bullet(proof)
        if len(cleaned) < 5:
            cleaned = _clean_bullet(proof_bullet_template(item.skill, payload.jd_text))
        if len(cleaned) < 5:
            raise HTTPException(status_code=422, detail="proof_bullet is too short after sanitization")

        entry = _find_override(overrides, item.skill)
        if entry:
            entry.level = item.level
            if item.role_id not in entry.target_roles:
                entry.target_roles.append(item.role_id)
            if cleaned not in entry.proof_bullets:
                entry.proof_bullets.append(cleaned)
            if len(entry.proof_bullets) > 3:
                entry.proof_bullets = entry.proof_bullets[:3]
        else:
            overrides.skills.append(
                OverrideSkill(
                    skill=item.skill,
                    level=item.level,
                    target_roles=[item.role_id],
                    proof_bullets=[cleaned],
                )
            )

    save_overrides(settings.generated_resumes_dir, resume_id, overrides)

    ats = score_resume_against_jd(payload.jd_text, state, strict_mode=payload.strict_mode)
    suggested, blocked = _build_patches_from_overrides(
        state=state,
        overrides=overrides,
        jd_text=payload.jd_text,
        rewrite_overrides_with_claude=payload.rewrite_overrides_with_claude,
        truth_mode=payload.truth_mode,
        ats=ats,
    )

    try:
        validate_patches_truth_mode(suggested, state, overrides, payload.truth_mode)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        apply_patches_to_state(state, suggested)
    except (IndexError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    enforce_outcome_clauses(state, payload.jd_text)

    meta = append_resume_version(settings.generated_resumes_dir, resume_id, state)
    version = meta.get("latest_version")
    version_dir = settings.generated_resumes_dir / resume_id / version
    resume_docx_path = None

    if payload.export_docx:
        template_path = Path(settings.docx_template_path)
        if not template_path.exists():
            raise HTTPException(status_code=400, detail="DOCX template not found")
        export_docx_from_state(state, template_path, version_dir / "resume.docx")
        resume_docx_path = version_dir / "resume.docx"
        update_version_docx_path(settings.generated_resumes_dir, resume_id, version, resume_docx_path)

    return IncludeSkillsResponse(
        resume_id=resume_id,
        version=version,
        applied_patches=suggested,
        paths={
            "resume_json": str((version_dir / "resume.json").as_posix()),
            "resume_docx": str(resume_docx_path.as_posix()) if resume_docx_path else None,
        },
        state=state,
        blocked=blocked,
    )


def _ensure_resume_exists(resume_id: str) -> None:
    path = settings.generated_resumes_dir / resume_id / "meta.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="resume_id not found")


def _load_state(resume_id: str):
    try:
        return load_latest_state(settings.generated_resumes_dir, resume_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="resume_id not found")


def _find_override(overrides: OverridesRequest | None, skill: str):
    if not overrides:
        return None
    for entry in overrides.skills:
        if entry.skill.strip().lower() == skill.strip().lower():
            return entry
    return None


def _find_role(state, role_id: str):
    for role in state.sections.experience:
        if role.role_id == role_id:
            return role
    return None


def _role_exists(state, role_id: str) -> bool:
    return any(role.role_id == role_id for role in state.sections.experience)


def _skill_already_present(state, skill: str) -> bool:
    token = skill.strip().lower()
    pattern = r"(?<!\\w)" + re.escape(token) + r"(?!\\w)"
    for line in state.sections.technical_skills:
        if re.search(pattern, line, re.IGNORECASE):
            return True
    for bullet in state.sections.professional_summary.splitlines():
        if re.search(pattern, bullet, re.IGNORECASE):
            return True
    for role in state.sections.experience:
        for bullet in role.bullets:
            if re.search(pattern, bullet, re.IGNORECASE):
                return True
    return False


def _skill_in_technical_skills(state, skill: str) -> bool:
    token = skill.strip().lower()
    if not token:
        return False
    pattern = r"(?<!\\w)" + re.escape(token) + r"(?!\\w)"
    for line in state.sections.technical_skills:
        if re.search(pattern, line, re.IGNORECASE):
            return True
    return False


def _role_has_skill(role, skill: str) -> bool:
    token = skill.strip().lower()
    if not token:
        return False
    pattern = r"(?<!\w)" + re.escape(token) + r"(?!\w)"
    for bullet in role.bullets:
        if re.search(pattern, bullet, re.IGNORECASE):
            return True
    return False


def _build_patches_from_overrides(
    state,
    overrides: OverridesRequest,
    jd_text: str,
    rewrite_overrides_with_claude: bool,
    truth_mode: str,
    ats,
) -> tuple[list[PatchOperation], list]:
    suggested: list[PatchOperation] = []
    inserts_per_role: dict[str, int] = {}
    tech_skill_added: set[str] = set()

    for entry in overrides.skills:
        skill = entry.skill
        if not skill:
            continue
        skill_key = skill.strip().lower()
        if skill_key and skill_key not in tech_skill_added and not _skill_in_technical_skills(state, skill):
            tech_patch = _build_technical_skill_patch(state, skill)
            if tech_patch:
                suggested.append(tech_patch)
            tech_skill_added.add(skill_key)

        for role_id in entry.target_roles:
            if inserts_per_role.get(role_id, 0) >= 2:
                continue
            role = _find_role(state, role_id)
            if not role:
                continue
            if _role_has_skill(role, skill):
                continue
            for proof in entry.proof_bullets:
                if inserts_per_role.get(role_id, 0) >= 2:
                    break
                rewritten = proof
                if rewrite_overrides_with_claude:
                    rewritten = _rewrite_override_bullet(
                        role=role,
                        skill=skill,
                        proof_bullet=proof,
                        jd_text=jd_text,
                    )
                suggested.append(
                    PatchOperation(
                        role_id=role_id,
                        section="experience",
                        action="insert",
                        after_index=len(role.bullets) - 1,
                        new_bullet=rewritten,
                        skill=skill,
                    )
                )
                inserts_per_role[role_id] = inserts_per_role.get(role_id, 0) + 1

    filtered, blocked = apply_truth_guardrails(
        suggested,
        ats,
        overrides,
        truth_mode,
        state,
        jd_text=jd_text,
    )
    return filtered, blocked


def _build_technical_skill_patch(state, skill: str) -> PatchOperation | None:
    """Insert skill into the best matching technical skills category."""
    lines = state.sections.technical_skills or []
    if not lines:
        return PatchOperation(
            section="technical_skills",
            action="insert",
            after_index=-1,
            new_bullet=f"Other Skills: {skill.strip()}",
            skill=skill,
        )

    other_idx = _find_other_skills_index(lines)
    idx = _pick_skill_category_index(lines, skill)
    if idx is None and other_idx is not None:
        idx = other_idx

    if idx is None:
        return PatchOperation(
            section="technical_skills",
            action="insert",
            after_index=len(lines) - 1,
            new_bullet=f"Other Skills: {skill.strip()}",
            skill=skill,
        )

    updated = _insert_skill_into_line(lines[idx], skill)
    if not updated or updated == lines[idx]:
        return None

    return PatchOperation(
        section="technical_skills",
        action="replace",
        bullet_index=idx,
        new_bullet=updated,
        skill=skill,
    )


def _pick_skill_category_index(lines: list[str], skill: str) -> int | None:
    categories = []
    for idx, line in enumerate(lines):
        if ":" not in line:
            continue
        label = line.split(":", 1)[0].strip().lower()
        if not label:
            continue
        categories.append((idx, label))

    if not categories:
        return None

    skill_key = skill.strip().lower()
    hints = _category_hints_for_skill(skill_key)
    if hints:
        for idx, label in categories:
            if any(hint in label for hint in hints):
                return idx

    # Fallback: if label already contains the skill token, use that line.
    for idx, label in categories:
        if skill_key and skill_key in label:
            return idx

    return None


def _category_hints_for_skill(skill_key: str) -> list[str]:
    mapping = {
        "kafka": ["stream", "real-time", "realtime"],
        "bigquery": ["warehous", "cloud", "data engineering"],
        "redshift": ["warehous", "cloud", "data engineering"],
        "snowflake": ["warehous", "cloud", "data engineering"],
        "fivetran": ["integration", "ingestion"],
        "airflow": ["orchestration", "pipeline"],
        "dbt": ["transform", "model"],
        "spark": ["transform", "data engineering"],
        "pyspark": ["transform", "data engineering"],
        "tableau": ["bi", "visual", "analytics", "report"],
        "power bi": ["bi", "visual", "analytics", "report"],
        "python": ["program", "scripting"],
        "java": ["program", "backend"],
        "aws": ["cloud"],
        "azure": ["cloud"],
        "gcp": ["cloud"],
    }
    return mapping.get(skill_key, [])


def _insert_skill_into_line(line: str, skill: str) -> str | None:
    if ":" not in line:
        return None
    label, rest = line.split(":", 1)
    label = label.strip()
    items = _split_skill_items(rest)
    if _items_contains_skill(items, skill):
        return line
    items.append(skill.strip())
    return f"{label}: {', '.join(items)}"


def _find_other_skills_index(lines: list[str]) -> int | None:
    for idx, line in enumerate(lines):
        if ":" not in line:
            continue
        label = line.split(":", 1)[0].strip().lower()
        if label == "other skills":
            return idx
    return None


def _split_skill_items(text: str) -> list[str]:
    tokens = re.split(r"[;,]", text)
    return [t.strip() for t in tokens if t.strip()]


def _items_contains_skill(items: list[str], skill: str) -> bool:
    token = skill.strip().lower()
    if not token:
        return False
    return any(_has_token(item, token) for item in items)


def _rewrite_override_bullet(role, skill: str, proof_bullet: str, jd_text: str) -> str:
    """Rewrite a user-provided proof bullet with Claude for a specific role."""
    cleaned_proof = _clean_bullet(proof_bullet)
    if not cleaned_proof:
        return proof_bullet

    role_info = {
        "company": role.company,
        "title": role.title or "",
        "location": role.location or "",
        "dates": role.dates or "",
    }
    neighbors = [b for b in role.bullets if b][:2]
    rewrite_hint = f"Ensure the bullet explicitly mentions the skill: {skill}."

    user_prompt = build_bullet_rewrite_prompt(
        jd_text=jd_text,
        role_info=role_info,
        original_bullet=cleaned_proof,
        neighbor_bullets=neighbors,
        rewrite_hint=rewrite_hint,
        allowed_additions=[skill] if skill else [],
    )

    try:
        rewritten = generate_with_claude(
            api_key=settings.anthropic_api_key,
            model=settings.claude_model,
            system_prompt=BULLET_REWRITE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=160,
            temperature=0.2,
        )
    except Exception as exc:
        logger.warning("Claude rewrite failed for override bullet: %s", exc)
        return cleaned_proof

    cleaned = _clean_bullet(rewritten)
    if not cleaned or len(cleaned) < 5 or len(cleaned) > 300:
        return cleaned_proof

    if skill and _has_token(cleaned, skill) is False and _has_token(cleaned_proof, skill):
        return cleaned_proof

    return ensure_outcome_clause(cleaned, jd_text)


def _clean_bullet(text: str) -> str:
    cleaned = text.replace("\t", " ").replace("\r", " ").replace("\n", " ")
    cleaned = re.sub(r"^\s*(?:[-\u2022*]|\d+\.)\s+", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _has_token(text: str, token: str) -> bool:
    if not token:
        return False
    pattern = r"(?<!\w)" + re.escape(token) + r"(?!\w)"
    return bool(re.search(pattern, text or "", re.IGNORECASE))
