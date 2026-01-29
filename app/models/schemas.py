from typing import Optional, List, Dict, Literal

from pydantic import BaseModel, Field, model_validator


class IngestResponse(BaseModel):
    indexed_chunks: int
    saved_files: List[str]


class GenerateRequest(BaseModel):
    jd_text: str = Field(..., min_length=20)
    top_k: int = Field(default=25, ge=5, le=60)
    multi_query: bool = False
    parse_with_claude: bool = False
    audit: bool = False
    domain_rewrite: bool = False
    target_company_type: Optional[str] = None
    bullets_per_role: int = 15
    use_experience_inventory: bool = True
    max_roles: Optional[int] = None


class RetrievedChunk(BaseModel):
    score: float
    resume_type: str
    source_file: str
    text: str
    support_level: str


class ResumeAudit(BaseModel):
    unsupported_claims: List[str]
    risky_phrases: Optional[List[str]] = None
    missing_must_haves: Optional[List[str]] = None


class GenerateResponse(BaseModel):
    model: str
    top_k: int
    retrieved: List[RetrievedChunk]
    resume_text: str
    audit: Optional[ResumeAudit] = None
    resume_id: Optional[str] = None


class JDParseRequest(BaseModel):
    jd_text: str = Field(..., min_length=20)


class JDParseResponse(BaseModel):
    role: str
    domain: Optional[str] = None
    seniority: Optional[str] = None
    must_have_skills: List[str]
    nice_to_have_skills: List[str]
    responsibilities: List[str]


class ExportDocxRequest(BaseModel):
    resume_id: Optional[str] = None
    company_name: Optional[str] = None
    position_name: Optional[str] = None
    job_id: Optional[str] = None
    jd_text: Optional[str] = None
    top_k: int = Field(default=25, ge=5, le=60)
    multi_query: bool = False
    parse_with_claude: bool = False
    audit: bool = False
    domain_rewrite: bool = False
    target_company_type: Optional[str] = None
    bullets_per_role: int = 15
    use_experience_inventory: bool = True
    max_roles: Optional[int] = None

    @model_validator(mode="after")
    def validate_export_inputs(self):
        if self.resume_id:
            if (self.company_name and not self.position_name) or (self.position_name and not self.company_name):
                raise ValueError("company_name and position_name must be provided together when overriding output paths")
        else:
            if not self.company_name or not self.position_name or not self.jd_text:
                raise ValueError("company_name, position_name, and jd_text are required when resume_id is not provided")
        if self.jd_text and len(self.jd_text.strip()) < 20:
            raise ValueError("jd_text must be at least 20 characters")
        return self


class ExportDocxResponse(BaseModel):
    saved_dir: str
    resume_docx_path: str
    jd_path: str
    audit: Optional[ResumeAudit] = None
    resume_id: Optional[str] = None
    version: Optional[str] = None
    internal_version_dir: Optional[str] = None
    internal_resume_docx_path: Optional[str] = None
    internal_jd_path: Optional[str] = None
    final_saved_dir: Optional[str] = None
    final_resume_docx_path: Optional[str] = None
    final_jd_path: Optional[str] = None


class ExportDocxFromTextRequest(BaseModel):
    company_name: str = Field(..., min_length=1)
    position_name: str = Field(..., min_length=1)
    job_id: Optional[str] = None
    jd_text: str = Field(..., min_length=20)
    resume_text: str = Field(..., min_length=20)


class ResumeHeader(BaseModel):
    name: Optional[str] = None
    location_line: Optional[str] = None
    contact_line: Optional[str] = None


class ExperienceRole(BaseModel):
    role_id: str
    company: str
    title: Optional[str] = None
    location: Optional[str] = None
    dates: Optional[str] = None
    bullets: List[str]


class ResumeSections(BaseModel):
    professional_summary: str
    technical_skills: List[str]
    experience: List[ExperienceRole]
    education: Optional[List[str]] = None


class ResumeState(BaseModel):
    header: ResumeHeader
    sections: ResumeSections


class RoleSelector(BaseModel):
    role_id: Optional[str] = None
    company: Optional[str] = None
    dates: Optional[str] = None


class BulletEditRequest(BaseModel):
    role_selector: RoleSelector
    bullet_index: int = Field(..., ge=0)
    new_bullet: str = Field(..., min_length=10, max_length=300)
    export_docx: bool = True


class BulletEditResponse(BaseModel):
    resume_id: str
    version: str
    updated_role: Dict[str, Optional[str]]
    updated_bullet_index: int
    paths: Dict[str, Optional[str]]


class BulletRewriteRequest(BaseModel):
    role_selector: RoleSelector
    bullet_index: int = Field(..., ge=0)
    jd_text: Optional[str] = None
    rewrite_hint: Optional[str] = None
    override_skill: Optional[str] = None
    temperature: float = Field(default=0.2, ge=0.0, le=1.0)


class BulletRewriteResponse(BaseModel):
    resume_id: str
    role_id: str
    bullet_index: int
    original_bullet: str
    rewritten_bullet: str

class ResumeStateResponse(BaseModel):
    resume_id: str
    version: str
    state: ResumeState
    jd_text: Optional[str] = None


class AtsScoreRequest(BaseModel):
    jd_text: str = Field(..., min_length=20)
    resume_id: Optional[str] = None
    resume_text: Optional[str] = None
    top_n_skills: int = 25
    strict_mode: bool = True

    @model_validator(mode="after")
    def validate_resume_source(self):
        if not self.resume_id and not self.resume_text:
            raise ValueError("resume_id or resume_text is required")
        return self


class SkillEvidence(BaseModel):
    section: str
    role_id: Optional[str] = None
    bullet_index: Optional[int] = None
    snippet: str


class SkillCoverage(BaseModel):
    skill: str
    status: Literal["direct", "partial", "missing"]
    evidence: List[SkillEvidence] = []
    direct_from_resume: bool = False


class AtsScoreResponse(BaseModel):
    ats_score: int
    required: List[SkillCoverage]
    preferred: List[SkillCoverage]
    missing_required: List[str]
    missing_preferred: List[str]


class OverrideSkill(BaseModel):
    skill: str = Field(..., min_length=2)
    level: Literal["hands_on", "worked_with", "exposure"]
    target_roles: List[str] = Field(..., min_length=1)
    proof_bullets: List[str] = Field(..., min_length=1, max_length=3)

    @model_validator(mode="after")
    def validate_proof_bullets(self):
        if self.level == "exposure" and len(self.proof_bullets) < 1:
            raise ValueError("exposure level requires at least 1 proof bullet")
        if self.level != "exposure" and not (1 <= len(self.proof_bullets) <= 3):
            raise ValueError("proof_bullets must be 1-3 items for hands_on/worked_with")
        return self


class OverridesRequest(BaseModel):
    skills: List[OverrideSkill] = Field(default_factory=list)


class OverridesResponse(BaseModel):
    resume_id: str
    overrides_path: str


class PatchOperation(BaseModel):
    role_id: Optional[str] = None
    section: Literal["experience", "technical_skills"] = "experience"
    action: Literal["replace", "insert"]
    bullet_index: Optional[int] = None
    after_index: Optional[int] = None
    new_bullet: str = Field(..., min_length=5, max_length=600)
    skill: Optional[str] = None
    reason: Optional[str] = None

    @model_validator(mode="after")
    def validate_action(self):
        if self.action == "replace":
            if self.section == "technical_skills":
                if self.bullet_index is None:
                    raise ValueError("replace for technical_skills requires bullet_index")
            else:
                if not self.role_id or self.bullet_index is None:
                    raise ValueError("replace requires role_id and bullet_index")
        if self.action == "insert":
            if self.section == "experience" and not self.role_id:
                raise ValueError("insert for experience requires role_id")
            if self.after_index is None:
                raise ValueError("insert requires after_index")
        return self


class SuggestPatchesRequest(BaseModel):
    jd_text: str = Field(..., min_length=20)
    strict_mode: bool = True
    apply_overrides: bool = True
    rewrite_overrides_with_claude: bool = True
    truth_mode: Literal["off", "strict", "balanced"] = "off"


class BlockedSuggestion(BaseModel):
    skill: str
    reason: str
    recommended_action: Literal["add_override", "downgrade_to_exposure"]
    suggested_role_ids: List[str] = Field(default_factory=list)
    example_override_payload: Optional[Dict[str, object]] = None


class SuggestPatchesResponse(BaseModel):
    suggested_patches: List[PatchOperation]
    blocked: List[BlockedSuggestion] = Field(default_factory=list)


class BlockedPlanRequest(BaseModel):
    jd_text: str = Field(..., min_length=20)
    truth_mode: Literal["off", "strict", "balanced"] = "off"
    top_n: int = 10
    strict_mode: bool = True


class BlockedPlanResponse(BaseModel):
    blocked: List[BlockedSuggestion] = Field(default_factory=list)


class ApplyPatchesRequest(BaseModel):
    patches: List[PatchOperation] = Field(..., min_length=1)
    export_docx: bool = True
    truth_mode: Literal["off", "strict", "balanced"] = "off"


class ApplyPatchesResponse(BaseModel):
    resume_id: str
    version: str
    paths: Dict[str, Optional[str]]


class OverridesFromBlockedItem(BaseModel):
    skill: str = Field(..., min_length=2)
    level: Literal["hands_on", "worked_with", "exposure"]
    role_id: str
    proof_bullet: Optional[str] = Field(default=None, max_length=300)


class OverridesFromBlockedRequest(BaseModel):
    items: List[OverridesFromBlockedItem] = Field(..., min_length=1)
    jd_text: Optional[str] = None


class OverridesFromBlockedResponse(BaseModel):
    resume_id: str
    overrides_path: str
    overrides: OverridesRequest


class IncludeSkillsRequest(BaseModel):
    items: List[OverridesFromBlockedItem] = Field(..., min_length=1)
    jd_text: str = Field(..., min_length=20)
    truth_mode: Literal["off", "strict", "balanced"] = "off"
    strict_mode: bool = True
    rewrite_overrides_with_claude: bool = True
    export_docx: bool = False


class IncludeSkillsResponse(BaseModel):
    resume_id: str
    version: str
    applied_patches: List[PatchOperation]
    paths: Dict[str, Optional[str]]
    state: ResumeState
    blocked: List[BlockedSuggestion] = Field(default_factory=list)

