export type ApiResponse<T> = { ok: true; data: T } | { ok: false; error: string };

export interface RetrievedChunk {
  score: number;
  resume_type: string;
  source_file: string;
  text: string;
  support_level: string;
}

export interface ResumeAudit {
  unsupported_claims: string[];
  risky_phrases?: string[];
  missing_must_haves?: string[];
}

export interface GenerateResponse {
  model: string;
  top_k: number;
  retrieved: RetrievedChunk[];
  resume_text: string;
  audit?: ResumeAudit;
  resume_id?: string;
}

export interface ExperienceRole {
  role_id: string;
  company: string;
  title?: string;
  location?: string;
  dates?: string;
  bullets: string[];
}

export interface ResumeState {
  header: {
    name?: string;
    location_line?: string;
    contact_line?: string;
  };
  sections: {
    professional_summary: string;
    technical_skills: string[];
    experience: ExperienceRole[];
    education?: string[];
  };
}

export interface ResumeStateResponse {
  resume_id: string;
  version: string;
  state: ResumeState;
  jd_text?: string;
}

export interface AtsSkillEvidence {
  section: string;
  role_id?: string;
  bullet_index?: number;
  snippet: string;
}

export type SkillStatus = "direct" | "partial" | "missing";

export interface SkillCoverage {
  skill: string;
  status: SkillStatus;
  evidence: AtsSkillEvidence[];
  direct_from_resume: boolean;
}

export interface AtsScoreResponse {
  ats_score: number;
  required: SkillCoverage[];
  preferred: SkillCoverage[];
  missing_required: string[];
  missing_preferred: string[];
}

export interface PatchOperation {
  role_id?: string;
  section: "experience" | "technical_skills";
  action: "replace" | "insert";
  bullet_index?: number;
  after_index?: number;
  new_bullet: string;
  skill?: string;
  reason?: string;
}

export interface SuggestPatchesResponse {
  suggested_patches: PatchOperation[];
  blocked: BlockedSuggestion[];
}

export interface BlockedSuggestion {
  skill: string;
  reason: string;
  recommended_action: "add_override" | "downgrade_to_exposure";
  suggested_role_ids: string[];
  example_override_payload?: Record<string, unknown>;
}

export interface ApplyPatchesResponse {
  resume_id: string;
  version: string;
  paths: {
    resume_json: string | null;
    resume_docx: string | null;
  };
}

export interface BulletRewriteResponse {
  resume_id: string;
  role_id: string;
  bullet_index: number;
  original_bullet: string;
  rewritten_bullet: string;
}

export interface BulletEditResponse {
  resume_id: string;
  version: string;
  updated_role: Record<string, string | null>;
  updated_bullet_index: number;
  paths: Record<string, string | null>;
}

export interface ExportDocxResponse {
  saved_dir: string;
  resume_docx_path: string;
  jd_path: string;
  audit?: ResumeAudit;
  resume_id?: string;
  version?: string;
  internal_version_dir?: string;
  internal_resume_docx_path?: string;
  internal_jd_path?: string;
  final_saved_dir?: string;
  final_resume_docx_path?: string;
  final_jd_path?: string;
}

export interface TemplateListResponse {
  files: string[];
}

export interface ResumeListResponse {
  files: string[];
}

export interface DeleteResumeResponse {
  deleted: string;
  indexed_chunks: number;
  remaining_files: string[];
}
