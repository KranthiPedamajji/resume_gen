import {
  ApiResponse,
  GenerateResponse,
  ResumeStateResponse,
  AtsScoreResponse,
  SuggestPatchesResponse,
  ApplyPatchesResponse,
  BulletRewriteResponse,
  BulletEditResponse,
  ExportDocxResponse,
  DeleteResumeResponse,
} from './types';

const BASE_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://127.0.0.1:8000';

async function request<T>(path: string, options?: RequestInit): Promise<ApiResponse<T>> {
  try {
    const res = await fetch(`${BASE_URL}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(options?.headers || {}),
      },
    });
    if (!res.ok) {
      const error = await res.text();
      return { ok: false, error };
    }
    const data = await res.json();
    return { ok: true, data } as ApiResponse<T>;
  } catch (error: any) {
    return { ok: false, error: error.message || 'Unknown error' };
  }
}

async function uploadForm<T>(path: string, form: FormData): Promise<ApiResponse<T>> {
  try {
    const res = await fetch(`${BASE_URL}${path}`, {
      method: 'POST',
      body: form,
    });
    if (!res.ok) {
      const error = await res.text();
      return { ok: false, error };
    }
    const raw = await res.text();
    if (!raw) {
      return { ok: true, data: undefined as unknown as T } as ApiResponse<T>;
    }
    try {
      const parsed = JSON.parse(raw);
      return { ok: true, data: parsed } as ApiResponse<T>;
    } catch (err: any) {
      return { ok: false, error: 'Invalid JSON response' };
    }
  } catch (error: any) {
    return { ok: false, error: error.message || 'Unknown error' };
  }
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: any) => request<T>(path, { method: 'POST', body: JSON.stringify(body) }),
  patch: <T>(path: string, body: any) => request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),

  health: () => request<{ status: string; ok: boolean }>('/health'),

  uploadResumes: (files: File[]) => {
    const form = new FormData();
    files.forEach((file) => form.append('files', file));
    return uploadForm<{ indexed_chunks: number; saved_files: string[] }>('/upload-resumes', form);
  },

  generate: (payload: {
    jd_text: string;
    top_k?: number;
    multi_query?: boolean;
    parse_with_claude?: boolean;
    audit?: boolean;
    domain_rewrite?: boolean;
    target_company_type?: string | null;
    bullets_per_role?: number;
    use_experience_inventory?: boolean;
    max_roles?: number | null;
  }) => request<GenerateResponse>('/generate', { method: 'POST', body: JSON.stringify(payload) }),

  getResume: (resumeId: string) => request<ResumeStateResponse>(`/resumes/${resumeId}`),

  atsScore: (payload: { jd_text: string; resume_id?: string; resume_text?: string; top_n_skills?: number; strict_mode?: boolean }) =>
    request<AtsScoreResponse>('/ats-score', { method: 'POST', body: JSON.stringify(payload) }),

  suggestPatches: (resumeId: string, payload: { jd_text: string; strict_mode?: boolean; apply_overrides?: boolean; truth_mode?: 'off' | 'strict' | 'balanced' }) =>
    request<SuggestPatchesResponse>(`/resumes/${resumeId}/suggest-patches`, { method: 'POST', body: JSON.stringify(payload) }),

  applyPatches: (resumeId: string, payload: { patches: any[]; export_docx?: boolean; truth_mode?: 'off' | 'strict' | 'balanced' }) =>
    request<ApplyPatchesResponse>(`/resumes/${resumeId}/apply-patches`, { method: 'POST', body: JSON.stringify(payload) }),

  rewriteBullet: (resumeId: string, payload: any) =>
    request<BulletRewriteResponse>(`/resumes/${resumeId}/rewrite-bullet`, { method: 'POST', body: JSON.stringify(payload) }),

  editBullet: (resumeId: string, payload: any) =>
    request<BulletEditResponse>(`/resumes/${resumeId}/bullet`, { method: 'PATCH', body: JSON.stringify(payload) }),

  blockedPlan: (resumeId: string, payload: { jd_text: string; truth_mode?: 'off' | 'strict' | 'balanced'; top_n?: number; strict_mode?: boolean }) =>
    request<any>(`/resumes/${resumeId}/blocked-plan`, { method: 'POST', body: JSON.stringify(payload) }),

  overridesFromBlocked: (resumeId: string, payload: any) =>
    request<any>(`/resumes/${resumeId}/overrides/from-blocked`, { method: 'POST', body: JSON.stringify(payload) }),

  exportDocx: (payload: any) => request<ExportDocxResponse>('/export-docx', { method: 'POST', body: JSON.stringify(payload) }),

  listTemplates: () => request<import('./types').TemplateListResponse>('/resumes/templates'),

  listResumes: () => request<import('./types').ResumeListResponse>('/resumes'),

  deleteResume: (resumePath: string) => request<DeleteResumeResponse>(`/resumes/${encodeURIComponent(resumePath)}`, { method: 'DELETE' }),
};
