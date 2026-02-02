"use client";
import { startTransition, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
// import { GenerateResponse } from "@/lib/types";
import "./ResumeInputScreen.css";

export default function ResumeInputScreen() {
  type UploadResponse = { indexed_chunks: number; saved_files: string[] };
  const router = useRouter();
  const [resumes, setResumes] = useState<{ id: number; name: string }[]>([]);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [company, setCompany] = useState("");
  const [role, setRole] = useState("");
  const [jdText, setJdText] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadWarning, setUploadWarning] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [listStatus, setListStatus] = useState<string | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  // const [generateResponse, setGenerateResponse] = useState<GenerateResponse | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [topK, setTopK] = useState<number>(25);
  const [bulletsPerRole, setBulletsPerRole] = useState<number>(15);
  const [targetCompanyType, setTargetCompanyType] = useState<string>("");
  const [multiQuery, setMultiQuery] = useState(false);
  const [parseWithClaude, setParseWithClaude] = useState(false);
  const [audit, setAudit] = useState(false);
  const [domainRewrite, setDomainRewrite] = useState(false);
  const [useExperienceInventory, setUseExperienceInventory] = useState(true);
  const [maxRoles, setMaxRoles] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const uploadDisabled = useMemo(() => selectedFiles.length === 0, [selectedFiles]);
  const generateDisabled = useMemo(() => generating || !role.trim() || !jdText.trim(), [generating, role, jdText]);

  const loadResumesData = async (): Promise<{ files: string[]; ok: boolean }> => {
    try {
      const res = await api.listResumes();
      if (res.ok) {
        return { files: res.data.files, ok: true };
      }
      console.warn("List resumes failed", res.error);
      return { files: [], ok: false };
    } catch (err: unknown) {
      console.warn("List resumes failed", err);
      return { files: [], ok: false };
    }
  };

  useEffect(() => {
    void (async () => {
      const { files } = await loadResumesData();
      startTransition(() => {
        setResumes(files.map((name, idx) => ({ id: idx, name })));
      });
    })();
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const saved = localStorage.getItem("generate_settings");
    if (!saved) return;
    try {
      const parsed = JSON.parse(saved) as Partial<{
        topK: number;
        bulletsPerRole: number;
        targetCompanyType: string;
        multiQuery: boolean;
        parseWithClaude: boolean;
        audit: boolean;
        domainRewrite: boolean;
        useExperienceInventory: boolean;
        maxRoles: number | null;
      }>;
      startTransition(() => {
        setTopK((prev: number) => parsed.topK ?? prev);
        setBulletsPerRole((prev: number) => parsed.bulletsPerRole ?? prev);
        setTargetCompanyType((prev: string) => parsed.targetCompanyType ?? prev);
        setMultiQuery((prev: boolean) => parsed.multiQuery ?? prev);
        setParseWithClaude((prev: boolean) => parsed.parseWithClaude ?? prev);
        setAudit((prev: boolean) => parsed.audit ?? prev);
        setDomainRewrite((prev: boolean) => parsed.domainRewrite ?? prev);
        setUseExperienceInventory((prev: boolean) => parsed.useExperienceInventory ?? prev);
        setMaxRoles((prev: number | null) => (parsed.maxRoles !== undefined ? parsed.maxRoles : prev));
      });
    } catch (err) {
      console.warn("Failed to parse generate settings", err);
    }
  }, []);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) {
      e.target.value = "";
      return;
    }
    setSelectedFiles((prev: File[]) => {
      const seen = new Set(prev.map((f: File) => `${f.name}-${f.size}-${f.lastModified}`));
      const merged = [...prev];
      files.forEach((f: File) => {
        const key = `${f.name}-${f.size}-${f.lastModified}`;
        if (!seen.has(key)) {
          merged.push(f);
          seen.add(key);
        }
      });
      return merged;
    });
    setError(null);
    setMessage(null);
    e.target.value = "";
  };

  const handleClearAll = (e?: React.MouseEvent<HTMLButtonElement>) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    setSelectedFiles([]);
  };

  const handleRemoveSelected = (index: number) => {
    setSelectedFiles((prev: File[]) => prev.filter((_: File, idx: number) => idx !== index));
  };

  const handleUpload = async () => {
    if (uploadDisabled) return;
    setLoading(true);
    setMessage(null);
    setError(null);
    setUploadStatus(null);
    setUploadError(null);
    setUploadWarning(null);
    setListStatus(null);
    setListError(null);
    const res = await api.uploadResumes(selectedFiles);
    if (!res.ok) {
      // If the request reached the server but the browser blocked the response (e.g., CORS), surface a softer hint.
      if (res.error?.toLowerCase().includes("failed to fetch")) {
        setUploadStatus("Upload request sent. Response blocked by the browser (likely CORS). Please check backend CORS and refresh.");
        setUploadWarning("Upload likely succeeded, but the response was blocked. Refresh the page after fixing CORS to see the list.");
        setLoading(false);
        return;
      }
      setLoading(false);
      setUploadError(res.error);
      return;
    }
    const uploadData = res.data as UploadResponse | undefined;
    const savedFiles = uploadData?.saved_files ?? selectedFiles.map((f: File) => f.name);
    //const indexedChunks = uploadData?.indexed_chunks ?? 0;
    setResumes((prev: { id: number; name: string }[]) => {
      const newItems = savedFiles.map((name: string, idx: number) => ({ id: Date.now() + idx, name }));
      return [...newItems, ...prev];
    });
    const { files: refreshedFiles, ok: refreshOk } = await loadResumesData();
    startTransition(() => {
      setResumes(refreshedFiles.map((name, idx) => ({ id: idx, name }))); // refresh list from backend if available
    });
    setLoading(false);
    setUploadStatus(`Uploaded successfully`);
    setSelectedFiles([]);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
    if (!refreshOk) {
      setUploadWarning("Upload succeeded, but the uploaded list could not refresh. You can refresh later.");
    }
  };

  const handleDeleteResume = async (name: string) => {
    setDeleting(name);
    setListStatus(null);
    setListError(null);
    const res = await api.deleteResume(name);
    if (!res.ok) {
      setDeleting(null);
      setListError(res.error);
      return;
    }
    const remaining = res.data.remaining_files || [];
    startTransition(() => {
      setResumes(remaining.map((n, idx) => ({ id: idx, name: n })));
    });
    setDeleting(null);
    setListStatus(`Deleted ${name}. Indexed ${res.data.indexed_chunks} chunks.`);
  };

  const handleGenerate = async () => {
    if (generateDisabled) return;
    if (!role.trim()) {
      setError("Role is required");
      return;
    }
    if (!jdText.trim()) {
      setError("Job description is required");
      return;
    }
    setGenerating(true);
    setError(null);
    setMessage(null);
    const payload = {
      jd_text: jdText,
      top_k: topK,
      multi_query: multiQuery,
      parse_with_claude: parseWithClaude,
      audit,
      domain_rewrite: domainRewrite,
      target_company_type: targetCompanyType || null,
      bullets_per_role: bulletsPerRole,
      use_experience_inventory: useExperienceInventory,
      max_roles: maxRoles,
      company_name: company || undefined,
      position_name: role || undefined,
    };
    localStorage.setItem("pending_generate_payload", JSON.stringify(payload));
    localStorage.setItem(
      "generate_settings",
      JSON.stringify({
        topK,
        bulletsPerRole,
        targetCompanyType,
        multiQuery,
        parseWithClaude,
        audit,
        domainRewrite,
        useExperienceInventory,
        maxRoles,
      })
    );
    localStorage.setItem("jd_text", jdText);
    if (company) {
      localStorage.setItem("company_name", company);
    }
    if (role) {
      localStorage.setItem("position_name", role);
    }
    router.push("/generating");
  };

  return (
    <div className="resume-input__container">
      <section className="resume-input__half resume-input__half--left">
        <div className="resume-left-stack">
          <div className="resume-input__card resume-input__card--source">
            <h2 className="resume-input__title">Resume Source</h2>
            <div className="resume-file-row">
              <div className="resume-file-label">
                <div className="resume-file-label-text">
                  {selectedFiles.length === 0 && (
                    <>
                      <div className="resume-file-label-title">Choose resume files</div>
                      <div className="resume-file-chosen">No files selected</div>
                    </>
                  )}
                  {selectedFiles.length > 0 && (
                    <div className="resume-file-inline-list">
                      <div className="resume-selected-chips">
                        {selectedFiles.map((file, idx) => (
                          <span key={`${file.name}-${idx}`} className="resume-selected-pill">
                            <span className="resume-selected-name">{file.name}</span>
                            <button
                              type="button"
                              className="resume-selected-remove"
                              onClick={(e) => {
                                e.preventDefault();
                                e.stopPropagation();
                                handleRemoveSelected(idx);
                              }}
                            >
                              ×
                            </button>
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
                <button
                  type="button"
                  className="resume-file-label-action"
                  onClick={(e) => {
                    e.preventDefault();
                    fileInputRef.current?.click();
                  }}
                >
                  Browse
                </button>
                <input
                  ref={fileInputRef}
                  className="resume-file-input"
                  type="file"
                  accept=".pdf,.doc,.docx,.txt"
                  multiple
                  onChange={handleFileChange}
                />
              </div>
              <div className="resume-file-bottom-row">
                <span className="resume-file-helper">Supports PDF, DOCX, TXT (Max 10MB each)</span>
                {selectedFiles.length > 0 && (
                  <button className="resume-selected-clear" onClick={handleClearAll}>
                    Clear all
                  </button>
                )}
              </div>
              {uploadStatus && <div className="resume-upload-status">{uploadStatus}</div>}
              {uploadError && <div className="resume-upload-error">{uploadError}</div>}
              {uploadWarning && !uploadError && <div className="resume-upload-warning">{uploadWarning}</div>}
              <div className="resume-upload-actions">
                <button className="resume-input__button" disabled={uploadDisabled || loading} onClick={handleUpload}>
                  {loading ? "Uploading..." : "Upload & Reindex"}
                </button>
              </div>
            </div>
          </div>

              <div className="resume-uploaded-list-card">
                <div className="resume-uploaded-list-title">Uploaded Resumes</div>
                {listStatus && <div className="resume-upload-status">{listStatus}</div>}
                {listError && <div className="resume-upload-error">{listError}</div>}
                {resumes.length === 0 ? (
                  <div className="resume-uploaded-empty">No resumes uploaded.</div>
                ) : (
                  <ul className="resume-uploaded-list">
                    {resumes.map((resume) => (
                      <li key={resume.id} className="resume-uploaded-item">
                        <span className="resume-uploaded-name" title={resume.name}>{resume.name}</span>
                        <button
                          className="resume-uploaded-remove"
                          disabled={deleting === resume.name}
                          onClick={() => handleDeleteResume(resume.name)}
                        >
                          {deleting === resume.name ? "Removing..." : "Remove"}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

          {/*
          {generateResponse && (
            <div className="resume-uploaded-list-card">
              <div className="resume-uploaded-list-title">Retrieved Context</div>
              <div className="resume-retrieved-list">
                {generateResponse.retrieved.slice(0, 5).map((item, idx) => (
                  <div key={idx} className="resume-retrieved-item">
                    <div className="resume-retrieved-meta">
                      <span className="resume-retrieved-type">{item.resume_type}</span>
                      <span className="resume-retrieved-source">{item.source_file}</span>
                    </div>
                    <div className="resume-retrieved-text">{item.text}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
          */}
        </div>
      </section>

      <section className="resume-input__half resume-input__half--right">
        <div className="resume-jobdetails-card">
          <div className="resume-jobdetails-header">
            <h2 className="resume-input__title" style={{ marginBottom: 0 }}>Job Details</h2>
            <button
              type="button"
              className="resume-settings-button"
              onClick={() => setSettingsOpen(true)}
              aria-label="Open generation settings"
            >
              ⚙️
            </button>
          </div>
          <label className="resume-input__label">Company Name (Optional)
            <input className="resume-input__input" type="text" placeholder="e.g., Google" value={company} onChange={(e) => setCompany(e.target.value)} />
          </label>
          <label className="resume-input__label">Role / Job Title
            <input className="resume-input__input" type="text" placeholder="e.g., Product Manager" value={role} onChange={(e) => setRole(e.target.value)} />
          </label>
          <label className="resume-input__label">Job Description
            <textarea className="resume-input__textarea" placeholder="Paste the job description here..." value={jdText} onChange={(e) => setJdText(e.target.value)} />
          </label>
          <button className="resume-input__button resume-input__button--primary" onClick={handleGenerate} disabled={generateDisabled}>
            {generating ? "Generating..." : "Generate Resume"}
          </button>
          {message && <div className="resume-success">{message}</div>}
          {error && <div className="resume-error">{error}</div>}
          {/*
          {generateResponse?.resume_text && (
            <div className="resume-preview-box">
              <div className="resume-preview-title">Resume Preview</div>
              <pre className="resume-preview-text">{generateResponse.resume_text}</pre>
            </div>
          )}
          */}
        </div>
      </section>

      {settingsOpen && (
        <div className="resume-settings-overlay" onClick={() => setSettingsOpen(false)}>
          <div className="resume-settings-modal" onClick={(e) => e.stopPropagation()}>
            <div className="resume-settings-header">
              <div className="resume-settings-title">Generation Settings</div>
              <button className="resume-settings-close" onClick={() => setSettingsOpen(false)}>×</button>
            </div>
            <div className="resume-settings-grid">
              <label className="resume-settings-field">
                <span>Top K</span>
                <input
                  type="number"
                  min={5}
                  max={60}
                  value={topK}
                  onChange={(e) => setTopK(Math.max(5, Math.min(60, Number(e.target.value) || 5)))}
                />
              </label>
              <label className="resume-settings-field">
                <span>Bullets per role</span>
                <input
                  type="number"
                  min={3}
                  max={30}
                  value={bulletsPerRole}
                  onChange={(e) => setBulletsPerRole(Math.max(3, Math.min(30, Number(e.target.value) || 3)))}
                />
              </label>
              <label className="resume-settings-field">
                <span>Max roles (optional)</span>
                <input
                  type="number"
                  min={1}
                  max={15}
                  value={maxRoles ?? ""}
                  onChange={(e) => {
                    const val = e.target.value === "" ? null : Number(e.target.value);
                    setMaxRoles(val === null ? null : Math.max(1, Math.min(15, val)));
                  }}
                />
              </label>
              <label className="resume-settings-field">
                <span>Target company type</span>
                <input
                  type="text"
                  placeholder="e.g., enterprise, startup"
                  value={targetCompanyType}
                  onChange={(e) => setTargetCompanyType(e.target.value)}
                />
              </label>
              <label className="resume-settings-toggle">
                <input type="checkbox" checked={multiQuery} onChange={(e) => setMultiQuery(e.target.checked)} />
                <span>Enable multi-query retrieval</span>
              </label>
              <label className="resume-settings-toggle">
                <input type="checkbox" checked={parseWithClaude} onChange={(e) => setParseWithClaude(e.target.checked)} />
                <span>Use Claude to parse JD</span>
              </label>
              <label className="resume-settings-toggle">
                <input type="checkbox" checked={domainRewrite} onChange={(e) => setDomainRewrite(e.target.checked)} />
                <span>Rewrite context for target domain</span>
              </label>
              <label className="resume-settings-toggle">
                <input type="checkbox" checked={audit} onChange={(e) => setAudit(e.target.checked)} />
                <span>Return audit</span>
              </label>
              <label className="resume-settings-toggle">
                <input type="checkbox" checked={useExperienceInventory} onChange={(e) => setUseExperienceInventory(e.target.checked)} />
                <span>Use experience inventory</span>
              </label>
            </div>
            <div className="resume-settings-actions">
              <button className="resume-settings-save" onClick={() => setSettingsOpen(false)}>Done</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
