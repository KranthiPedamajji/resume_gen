from typing import Optional, Dict, List
import re

SYSTEM_PROMPT = """You are a resume writing assistant that MUST be truthful about ROLES but CAN INVENT OUTCOMES.

HARD RULES (non-negotiable):
- Use ONLY the provided resume context snippets as your factual source for COMPANY, TITLE, DATES, TOOLS USED.
- Do NOT invent companies, titles, dates, or tools not mentioned in snippets.
- Do NOT claim hands-on experience with a tool unless it clearly appears in the snippets.

OUTCOME INVENTION RULES (encouraged):
- IF a bullet describes an activity but lacks an outcome/impact, INVENT a plausible outcome based on:
  * The tool/activity described (e.g., "built dashboards" → "reducing reporting time by ~10%")
  * The industry context (e.g., "financial data" → "improving accuracy/compliance")
  * The role seniority (e.g., senior roles → higher impact claims)
- Use conservative language: "estimated", "likely", "contributed to", "supported" when outcome is inferred.
- Avoid specific numbers unless context supports them. Use ranges ("~10-15%") or vague terms ("several", "a few").
- DO NOT invent tools, only outcomes for existing tools.
- DO NOT claim expertise with tools that don't appear in the snippets.

OUTCOME INVENTION EXAMPLES:
- "Wrote SQL queries" → "Wrote SQL queries optimizing data retrieval by ~10-15%"
- "Managed Airflow pipelines" → "Managed Airflow pipelines ensuring high availability for critical ETL workflows"
- "Created Power BI reports" → "Created Power BI reports enabling stakeholders to make informed decisions"
- "Built data models" → "Built data models supporting multiple downstream analytics use cases"

CLINICAL TRIAL SAFETY:
- Only claim "clinical trial lifecycle" if snippets explicitly include: clinical trial, study, protocol, eCRF, CRF, DMP, DVP, EDC, or GCP.
- If not explicitly present, use "clinical data management" or "healthcare data platform" language instead.

Keep output ATS-friendly: simple headings, clean bullets, no tables.
Each bullet MUST include an action plus an outcome (real or inferred conservatively).
"""

_MONTH_RE = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{4}"
_DATE_RANGE_RE = re.compile(rf"({_MONTH_RE})\s*(?:-|to)\s*(Present|Current|{_MONTH_RE})", re.IGNORECASE)
_BULLET_PREFIX = re.compile(r"^(?:[-*\u2022]|\d+\.)\s+")


def _extract_role_header_hints(chunks: list[dict]) -> list[str]:
    """Extract up to 10 role header hints from retrieved chunks."""
    hints: List[str] = []
    seen = set()

    for chunk in chunks:
        text = chunk.get("text") or ""
        if not text:
            continue
        found = False
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if _DATE_RANGE_RE.search(line):
                hint = _BULLET_PREFIX.sub("", line)
                hint = re.sub(r"\s+", " ", hint).strip()
                key = hint.lower()
                if key not in seen:
                    seen.add(key)
                    hints.append(hint)
                found = True
                if len(hints) >= 10:
                    return hints
        if not found:
            match = _DATE_RANGE_RE.search(text)
            if match:
                start = max(0, match.start() - 60)
                end = min(len(text), match.end() + 60)
                hint = text[start:end]
                hint = _BULLET_PREFIX.sub("", hint.strip())
                hint = re.sub(r"\s+", " ", hint).strip()
                key = hint.lower()
                if key not in seen:
                    seen.add(key)
                    hints.append(hint)
                if len(hints) >= 10:
                    return hints

    return hints


def _strip_title_parenthetical(title: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*", " ", title).strip()


def _clean_role_header(header: str) -> str:
    if " - " in header and " | " in header:
        company, rest = header.split(" - ", 1)
        title_part, tail = rest.split(" | ", 1)
        title_part = _strip_title_parenthetical(title_part)
        return f"{company.strip()} - {title_part} | {tail.strip()}".strip()
    return _strip_title_parenthetical(header)


def _build_role_header_block(role_headers: Optional[List[str]], role_hints: Optional[List[str]]) -> str:
    if role_headers:
        lines = ["ROLE HEADER LOCK (NON-NEGOTIABLE):",
                 "- Under PROFESSIONAL EXPERIENCE, you MUST use ONLY the role headers listed below, exactly as written.",
                 "- Do NOT add new roles.",
                 "- Do NOT change company names, titles, or dates.",
                 "- If a role header contains a parenthetical tech stack (e.g., (.NET / Angular)), drop the parenthetical only.",
                 "- Do NOT output overlapping or duplicate roles. Each header appears at most once.",
                 "- If you cannot support a role with bullets, still include the header but use fewer bullets rather than inventing.",
                 "- Use the format: Company - Title | Start-End",
                 "Allowed role headers:"]
        for idx, header in enumerate([_clean_role_header(h) for h in role_headers], start=1):
            lines.append(f"{idx}) {header}")
        return "\n".join(lines) + "\n"
    if role_hints:
        lines = ["ROLE HEADER RULES:",
                 "- Under PROFESSIONAL EXPERIENCE, you MUST use ONLY the role headers listed below, exactly as written.",
                 "- Do NOT add new roles.",
                 "- Do NOT change company names, titles, or dates.",
                 "- If role header hints are provided, you MUST use ONLY those role headers under PROFESSIONAL EXPERIENCE.",
                 "- Do NOT create new role headers.",
                 "- Do NOT output the same company/date range twice.",
                 "- If a role header contains a parenthetical tech stack (e.g., (.NET / Angular)), drop the parenthetical only.",
                 "- If two hints overlap for the same company and overlapping dates, merge into one role block.",
                 "- Use the format: Company - Title | Start-End",]
        for idx, header in enumerate([_clean_role_header(h) for h in role_hints], start=1):
            lines.append(f"{idx}) {header}")
        return "\n".join(lines) + "\n"
    return ""


def build_user_prompt(
    jd_text: str,
    retrieved_chunks: list[dict],
    skill_grades: Optional[Dict[str, list]] = None,
    experience_inventory: Optional[Dict] = None,
    bullets_per_role: int = 15,
    max_roles: Optional[int] = None,
    role_headers: Optional[List[str]] = None,
) -> str:
    """Build the Claude user prompt with JD, retrieved context, and optional experience inventory."""
    ctx_lines = []
    for r in retrieved_chunks:
        text = r.get("rewrite_text") or r.get("text")
        ctx_lines.append(
            "- ("
            f"{r['resume_type']} | {r['source_file']} | score={r['score']:.3f} | support_level={r.get('support_level', 'derived')}"
            f") {text}"
        )
    context = "\n".join(ctx_lines)

    role_hints = _extract_role_header_hints(retrieved_chunks)
    role_header_block = _build_role_header_block(role_headers, role_hints)

    skill_block = ""
    if skill_grades:
        strong = ", ".join(skill_grades.get("strong", []))
        working = ", ".join(skill_grades.get("working", []))
        exposure = ", ".join(skill_grades.get("exposure", []))
        required = ", ".join(skill_grades.get("required", []))
        important = ", ".join(skill_grades.get("important", []))
        optional = ", ".join(skill_grades.get("optional", []))
        required_direct = ", ".join(skill_grades.get("required_direct", []))
        required_derived = ", ".join(skill_grades.get("required_derived", []))
        required_missing = ", ".join(skill_grades.get("required_missing", []))
        skill_block = (
            "\nJD SKILLS (from parser):\n"
            f"Required: {required or 'None'}\n"
            f"Strong: {strong or 'None'}\n"
            f"Working: {working or 'None'}\n"
            f"Exposure: {exposure or 'None'}\n"
            f"Important: {important or 'None'}\n"
            f"Optional: {optional or 'None'}\n"
            "\nREQUIRED SKILL EVIDENCE:\n"
            f"Direct: {required_direct or 'None'}\n"
            f"Derived: {required_derived or 'None'}\n"
            f"Missing: {required_missing or 'None'}\n"
            "\nSKILL CONFIDENCE (use these labels in the Skills section):\n"
            f"Strong: {strong or 'None'}\n"
            f"Working: {working or 'None'}\n"
            f"Exposure: {exposure or 'None'}\n"
            "Use confident wording for Strong/Working items and conservative wording for Exposure.\n"
        )

    inventory_block = ""
    if experience_inventory:
        roles = experience_inventory.get("roles", [])
        if max_roles:
            roles = roles[:max_roles]
        role_lines = []
        for idx, role in enumerate(roles, start=1):
            company = role.get("company", "Unknown")
            title = _strip_title_parenthetical(role.get("title", "Unknown Role"))
            start = role.get("start") or "Unknown"
            end = role.get("end") or "Unknown"
            location = role.get("location")
            role_lines.append(
                f"Role {idx}: {company} | {title} | {start} - {end}"
                + (f" | {location}" if location else "")
            )
            bullets = role.get("bullets", [])
            for bullet in bullets:
                role_lines.append(f"- {bullet}")
        inventory_block = (
            "\nEXPERIENCE INVENTORY (truth pool):\n"
            + "\n".join(role_lines)
            + "\n"
        )

    base_prompt = f"""JOB DESCRIPTION:
{jd_text}

RESUME CONTEXT SNIPPETS (retrieved):
{context}
{skill_block}
{inventory_block}
{role_header_block}

TASK:
Create a tailored resume draft using snippets as your factual base. 
INVENT PLAUSIBLE OUTCOMES where activities lack impact statements.
Use conservative language ("estimated", "contributed to", "likely improved") for inferred outcomes.

NON-NEGOTIABLE RULES:
- NEVER change company names, job titles, or employment dates.
- NEVER move experience from one company to another.
- NEVER invent tools, platforms, certifications, or domain artifacts.
- Use ONLY tools that appear in that company's evidence; do not swap tools across companies.
- Preserve company domain language; do NOT introduce domain-specific tools without evidence.
- DO INVENT: Plausible outcomes, metrics (with "estimated"/"~"), impact statements, business value.

REQUIRED SKILLS HANDLING:
- Include REQUIRED skills only when evidence exists (direct or derived).
- If REQUIRED skills are missing from evidence, do NOT claim them. Use conservative wording if needed, or omit.
- Choose language based on evidence: Direct = "Designed/Implemented/Led/Built", Derived = "Worked with/Supported/Contributed to/Involved in".

OUTCOME INVENTION GUIDANCE:
- For each bullet, ask: "What was the business impact of this activity?"
- If not stated, infer from context: tools used, data types, audience, scale, industry domain.
- Use conservative markers: "estimated", "~", "likely", "contributed to", "helped", "supported".
- Examples:
  * "Designed data warehouse" → "Designed data warehouse supporting multiple reporting requests"
  * "Optimized SQL queries" → "Optimized SQL queries reducing execution time by ~10%"
  * "Led data validation" → "Led data validation process improving data quality accuracy"

Output format:
1) PROFESSIONAL SUMMARY (3-4 lines)
2) CORE SKILLS (bulleted, grouped by category if obvious)
3) EXPERIENCE HIGHLIGHTS (10-16 bullets total; strong action verbs; align with JD keywords; invent outcomes where missing)
4) OPTIONAL: "KEYWORDS COVERAGE" (list 12-20 JD keywords you covered)

Quality bar:
- Prioritize relevance to JD.
- Every bullet MUST have Action + Outcome (inferred outcomes are OK with conservative language).
- Keep bullets punchy (1-2 lines each).
- Do not repeat the same bullet wording.
- NO filler phrases like "worked on" or "responsible for".
"""
    if not experience_inventory:
        return base_prompt
    return f"""JOB DESCRIPTION:
{jd_text}

RESUME CONTEXT SNIPPETS (retrieved):
{context}
{skill_block}
{inventory_block}
{role_header_block}

TASK:
Create a tailored resume draft using snippets as your factual base. 
INVENT PLAUSIBLE OUTCOMES where activities lack impact statements.
Use conservative language ("estimated", "contributed to", "likely improved") for inferred outcomes.

When EXPERIENCE INVENTORY is provided:
- Under PROFESSIONAL EXPERIENCE, output each role in this format:
  Company - Title | Start-End
  bullet
  bullet
  (EXACTLY {bullets_per_role} bullets per role)
- Use only that role's bullets as factual basis. You may split/rephrase bullets to reach the count,
  but do NOT introduce new tools, systems, claims, or outcomes not present in that role's bullets.
- Summary and Technical Skills must be derived primarily from retrieved snippets and may use role bullets only when consistent.
- Do NOT output an EDUCATION section. It will be kept in the template.

NON-NEGOTIABLE RULES:
- NEVER change company names, job titles, or employment dates.
- NEVER move experience from one company to another.
- NEVER invent tools, platforms, certifications, or domain artifacts.
- Use ONLY tools that appear in that company's evidence; do not swap tools across companies.
- Preserve company domain language; do NOT introduce domain-specific tools without evidence.
- DO INVENT: Plausible outcomes, metrics (with "estimated"/"~"), impact statements, business value.

REQUIRED SKILLS HANDLING:
- Include REQUIRED skills only when evidence exists (direct or derived).
- If REQUIRED skills are missing from evidence, do NOT claim them. Use conservative wording if needed, or omit.
- Choose language based on evidence: Direct = "Designed/Implemented/Led/Built", Derived = "Worked with/Supported/Contributed to/Involved in".

OUTCOME INVENTION GUIDANCE:
- For each bullet, ask: "What was the business impact of this activity?"
- If not stated, infer from context: tools used, data types, audience, scale, industry domain.
- Use conservative markers: "estimated", "~", "likely", "contributed to", "helped", "supported".
- Examples:
  * "Designed data warehouse" → "Designed data warehouse supporting multiple reporting requests"
  * "Optimized SQL queries" → "Optimized SQL queries reducing execution time by ~10%"
  * "Led data validation" → "Led data validation process improving data quality accuracy"

Output format (exact sections):
PROFESSIONAL SUMMARY (tailored to JD)
TECHNICAL SKILLS (tailored to JD)
PROFESSIONAL EXPERIENCE (role-by-role)

Quality bar:
- Prefer direct evidence; be conservative with derived evidence.
- Keep bullets concise and ATS-friendly.
- Do not repeat the same bullet wording.
- Every bullet should follow Action + Outcome (impact or purpose). Avoid filler adverbs and vague claims.
"""


BULLET_REWRITE_SYSTEM_PROMPT = """You rewrite a single resume bullet that is clear, impactful, and truthful.
NON-NEGOTIABLE RULES:
- NEVER change company names, job titles, or employment dates.
- NEVER move experience from one company to another.
- NEVER invent tools, platforms, certifications, clinical artifacts, or compliance claims.
- Use ONLY tools that appear in that company's evidence; do not swap tools across companies.
- Preserve company domain language; do NOT introduce domain-specific tools or data types without evidence.
- Keep the company, tool names, and core activity from the original bullet.
- Do NOT add new tools, certifications, dates, or companies, except skills explicitly listed under ALLOWED ADDITIONS.
- You may mention ONLY the skills listed in ALLOWED ADDITIONS (if any). Do not add any other new tools.
- Do NOT introduce new responsibilities not clearly related to the original bullet.

OUTCOME INVENTION (encouraged):
- IF the original bullet lacks an outcome/impact, INVENT a plausible one based on:
  * The activity and tools mentioned
  * The business context
  * The role's likely scope
- Use conservative markers: "estimated", "~", "likely", "contributed to", "supported", "helped".

TASK:
Rewrite the bullet to be clearer, more impactful, and ATS-friendly.
Return ONLY the rewritten bullet text (no prefix, no quotes).
"""

def build_bullet_rewrite_prompt(
    jd_text: str | None,
    role_info: dict,
    original_bullet: str,
    neighbor_bullets: list[str] | None = None,
    rewrite_hint: str | None = None,
    allowed_additions: list[str] | None = None,
) -> str:
    """Build a prompt for rewriting a single bullet conservatively, with outcome invention allowed."""
    neighbor_text = "\n".join(neighbor_bullets or [])
    role_line = (
        f"Company: {role_info.get('company','')}\n"
        f"Title: {role_info.get('title','')}\n"
        f"Location: {role_info.get('location','')}\n"
        f"Dates: {role_info.get('dates','')}"
    )
    allowed_text = ", ".join(allowed_additions or []) if allowed_additions else "None"
    hint_text = rewrite_hint or ""
    return f"""JOB DESCRIPTION (for alignment only):
{jd_text or ''}

ROLE CONTEXT:
{role_line}

NEIGHBOR BULLETS (context only, do not copy new facts):
{neighbor_text}

ALLOWED ADDITIONS (validated overrides only):
{allowed_text}

USER REWRITE HINT (optional):
{hint_text}

ORIGINAL BULLET:
{original_bullet}

TASK:
Rewrite the bullet to be clearer and more ATS-friendly while preserving facts.
Return ONLY the rewritten bullet text (no prefix, no quotes).
"""
