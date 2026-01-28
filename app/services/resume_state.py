from __future__ import annotations

from typing import Dict, List, Optional
import hashlib
import re

from app.models.schemas import ResumeState, ResumeHeader, ResumeSections, ExperienceRole


_HEADING_MAP = {
    "PROFESSIONAL SUMMARY": "professional_summary",
    "TECHNICAL SKILLS": "technical_skills",
    "CORE SKILLS": "technical_skills",
    "PROFESSIONAL EXPERIENCE": "experience",
    "EXPERIENCE HIGHLIGHTS": "experience",
    "EDUCATION": "education",
}

_BULLET_RE = re.compile(r"^\s*(?:[-•*]|\d+\.)\s+")
_MONTH_RE = r"(?:Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|" \
            r"Jul|July|Aug|August|Sep|Sept|September|Oct|October|Nov|November|" \
            r"Dec|December)"
_DATE_RANGE_RE = re.compile(
    rf"\b({_MONTH_RE}\s+\d{{4}})\s*[–-]\s*(Present|Current|{_MONTH_RE}\s+\d{{4}})\b",
    re.IGNORECASE,
)


def parse_resume_text_to_state(resume_text: str) -> ResumeState:
    """Parse resume text into a structured ResumeState with sections and bullets."""
    lines = [_clean_line(line) for line in resume_text.splitlines()]
    lines = [line for line in lines if line]

    header_lines, body_lines = _split_header(lines)
    header = _parse_header_lines(header_lines)

    sections = _extract_sections(body_lines)
    summary = "\n".join(sections.get("professional_summary", [])).strip()
    skills = [_strip_bullet(line) for line in sections.get("technical_skills", [])]

    experience_lines = sections.get("experience", [])
    roles = _parse_experience_roles(experience_lines)

    education = sections.get("education", [])

    return ResumeState(
        header=header,
        sections=ResumeSections(
            professional_summary=summary,
            technical_skills=skills,
            experience=roles,
            education=education or None,
        ),
    )


def render_resume_text(state: ResumeState) -> str:
    """Render a ResumeState back into a simple text resume format."""
    lines: List[str] = []

    if state.header.name:
        lines.append(state.header.name)
    if state.header.location_line:
        lines.append(state.header.location_line)
    if state.header.contact_line:
        lines.append(state.header.contact_line)

    if lines:
        lines.append("")

    if state.sections.professional_summary:
        lines.append("PROFESSIONAL SUMMARY")
        lines.append(state.sections.professional_summary.strip())
        lines.append("")

    if state.sections.technical_skills:
        lines.append("TECHNICAL SKILLS")
        lines.extend(state.sections.technical_skills)
        lines.append("")

    if state.sections.experience:
        lines.append("PROFESSIONAL EXPERIENCE")
        for role in state.sections.experience:
            header = _format_role_header(role)
            lines.append(header)
            for bullet in role.bullets:
                lines.append(f"- {bullet}")
            lines.append("")

    if state.sections.education:
        lines.append("EDUCATION")
        lines.extend(state.sections.education)

    return "\n".join(lines).strip()


def _format_role_header(role: ExperienceRole) -> str:
    parts = [role.company]
    if role.title:
        parts.append(role.title)
    header = " - ".join(parts) if len(parts) > 1 else parts[0]
    tail = []
    if role.location:
        tail.append(role.location)
    if role.dates:
        tail.append(role.dates)
    if tail:
        header = f"{header} | " + " | ".join(tail)
    return header


def _split_header(lines: List[str]) -> tuple[List[str], List[str]]:
    header = []
    body = []
    in_body = False
    for line in lines:
        heading = _detect_heading(line)
        if heading and not in_body:
            in_body = True
            body.append(line)
            continue
        if in_body:
            body.append(line)
        else:
            header.append(line)
    return header, body


def _parse_header_lines(lines: List[str]) -> ResumeHeader:
    name = lines[0] if len(lines) >= 1 else None
    location_line = lines[1] if len(lines) >= 2 else None
    contact_line = " | ".join(lines[2:]) if len(lines) >= 3 else None
    return ResumeHeader(name=name, location_line=location_line, contact_line=contact_line)


def _extract_sections(lines: List[str]) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {}
    current: Optional[str] = None

    for line in lines:
        heading = _detect_heading(line)
        if heading:
            current = heading
            sections.setdefault(current, [])
            continue
        if current:
            sections[current].append(line)
    return sections


def _detect_heading(line: str) -> Optional[str]:
    normalized = _normalize_heading(line)
    return _HEADING_MAP.get(normalized)


def _normalize_heading(line: str) -> str:
    cleaned = line.strip().lstrip("#").strip()
    cleaned = cleaned.replace("**", "").replace("__", "").replace("*", "")
    return cleaned.upper()


def _parse_experience_roles(lines: List[str]) -> List[ExperienceRole]:
    roles: List[ExperienceRole] = []
    current: Optional[Dict] = None
    fallback_bullets: List[str] = []

    for line in lines:
        clean = _clean_line(line)
        if not clean:
            continue
        if _is_role_header(clean):
            if current:
                roles.append(_to_role(current))
            company, title, location, dates = _parse_role_header(clean)
            current = {
                "company": company or "Unknown",
                "title": title or None,
                "location": location or None,
                "dates": dates or None,
                "bullets": [],
            }
            continue

        bullet = _strip_bullet(clean)
        if current is None:
            fallback_bullets.append(bullet)
        else:
            current["bullets"].append(bullet)

    if current:
        roles.append(_to_role(current))

    if not roles and fallback_bullets:
        roles.append(
            ExperienceRole(
                role_id=_role_id("Unknown", "Unknown Role", None),
                company="Unknown",
                title="Unknown Role",
                location=None,
                dates=None,
                bullets=fallback_bullets,
            )
        )

    return roles


def _to_role(raw: Dict) -> ExperienceRole:
    role_id = _role_id(raw.get("company"), raw.get("title"), raw.get("dates"))
    return ExperienceRole(
        role_id=role_id,
        company=raw.get("company", "Unknown"),
        title=raw.get("title"),
        location=raw.get("location"),
        dates=raw.get("dates"),
        bullets=raw.get("bullets", []),
    )


def _role_id(company: Optional[str], title: Optional[str], dates: Optional[str]) -> str:
    token = f"{company or ''}|{title or ''}|{dates or ''}".lower().strip()
    return hashlib.sha1(token.encode("utf-8")).hexdigest()[:10]


def _is_role_header(line: str) -> bool:
    if _DATE_RANGE_RE.search(line):
        return True
    if re.search(r"\b(19|20)\d{2}\b", line) and (" | " in line or " - " in line):
        return True
    return False


def _parse_role_header(line: str) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    match = _DATE_RANGE_RE.search(line)
    dates = None
    base = line
    if match:
        dates = match.group(0).replace("\u2013", "-").replace("\u2014", "-")
        base = (line[:match.start()] + line[match.end():]).strip(" -|,")

    company = None
    title = None
    location = None

    if " - " in base:
        company, rest = base.split(" - ", 1)
        parts = [p.strip() for p in rest.split("|") if p.strip()]
        if parts:
            title = parts[0]
        if len(parts) > 1:
            location = parts[1]
    else:
        parts = [p.strip() for p in base.split("|") if p.strip()]
        if parts:
            company = parts[0]
        if len(parts) > 1:
            title = parts[1]
        if len(parts) > 2:
            location = parts[2]

    return company, title, location, dates


def _strip_bullet(line: str) -> str:
    return _BULLET_RE.sub("", line).strip()


def _clean_line(line: str) -> str:
    cleaned = line.strip()
    cleaned = cleaned.replace("**", "").replace("__", "").replace("*", "")
    cleaned = re.sub(r"^#+\s*", "", cleaned)
    return cleaned.strip()
