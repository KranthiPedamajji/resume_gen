"use client";

import { useEffect, useMemo, useState, useCallback, startTransition } from "react";
import { useSearchParams } from "next/navigation";
import styles from "./ResumeEditor.module.css";
import { api } from "@/lib/api";
import {
  ResumeStateResponse,
  AtsScoreResponse,
  ExperienceRole,
  BulletRewriteResponse,
  SuggestPatchesResponse,
} from "@/lib/types";

export default function ResumeEditorPage() {
  const searchParams = useSearchParams();
  const [resumeId, setResumeId] = useState<string>("");
  const [data, setData] = useState<ResumeStateResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ats, setAts] = useState<AtsScoreResponse | null>(null);
  const [jdText, setJdText] = useState<string>("");
  const [activeRole, setActiveRole] = useState<ExperienceRole | null>(null);
  const [activeBulletIndex, setActiveBulletIndex] = useState<number | null>(null);
  const [bulletDraft, setBulletDraft] = useState<string>("");
  const [rewriteResult, setRewriteResult] = useState<BulletRewriteResponse | null>(null);
  const [patches, setPatches] = useState<SuggestPatchesResponse | null>(null);
  const [regenStatus, setRegenStatus] = useState<string | null>(null);
  const [companyName, setCompanyName] = useState<string>("");
  const [positionName, setPositionName] = useState<string>("");
  const [jobId, setJobId] = useState<string>("");
  const [exportStatus, setExportStatus] = useState<string | null>(null);

  const loadResume = useCallback(async (id: string) => {
    setLoading(true);
    setError(null);
    const res = await api.getResume(id);
    setLoading(false);
    if (!res.ok) {
      setError(res.error);
      return;
    }
    setData(res.data);
    setJdText(res.data.jd_text || localStorage.getItem("jd_text") || "");
  }, []);

  useEffect(() => {
    void (async () => {
      const idFromUrl = searchParams.get("resumeId") || "";
      const storedId = typeof window !== "undefined" ? localStorage.getItem("resume_id") || "" : "";
      const resolvedId = idFromUrl || storedId;
      if (resolvedId) {
        startTransition(() => setResumeId(resolvedId));
        await loadResume(resolvedId);
      } else {
        startTransition(() => setError("No resume_id found. Generate a resume first."));
      }
    })();
  }, [searchParams, loadResume]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const company = localStorage.getItem("company_name") || "";
    const position = localStorage.getItem("position_name") || "";
    const job = localStorage.getItem("job_id") || "";
    // Batch state updates to avoid cascading renders
    startTransition(() => {
      setCompanyName(company);
      setPositionName(position);
      setJobId(job);
    });
  }, []);

  const handleRegenerate = async () => {
    if (!jdText.trim()) {
      setError("Job description is required to regenerate.");
      return;
    }
    setLoading(true);
    setError(null);
    setRegenStatus("Regenerating resume...");
    const payload = {
      jd_text: jdText,
      top_k: 25,
      multi_query: false,
      parse_with_claude: false,
      audit: false,
      domain_rewrite: false,
      target_company_type: null as string | null,
      bullets_per_role: 15,
      use_experience_inventory: true,
      max_roles: null as number | null,
    };
    const res = await api.generate(payload);
    setLoading(false);
    if (!res.ok) {
      setRegenStatus(null);
      setError(res.error);
      return;
    }
    const newId = res.data.resume_id || "";
    if (newId) {
      localStorage.setItem("resume_id", newId);
      localStorage.setItem("jd_text", jdText);
      setResumeId(newId);
      setRegenStatus("Resume regenerated. Loading latest version...");
      await loadResume(newId);
      setRegenStatus("Resume regenerated.");
      setAts(null);
      setPatches(null);
      setActiveRole(null);
      setActiveBulletIndex(null);
      setRewriteResult(null);
      setBulletDraft("");
    } else {
      setRegenStatus("Resume regenerated, but no resume_id returned.");
    }
  };

  const handleExportDocx = async () => {
    if (!resumeId) {
      setError("No resume loaded to export.");
      return;
    }
    if ((companyName && !positionName) || (!companyName && positionName)) {
      setError("Provide both company and role to export to the designated folder.");
      return;
    }
    setLoading(true);
    setError(null);
    setExportStatus("Saving DOCX...");
    const payload: {
      resume_id: string;
      jd_text: string | null;
      company_name?: string;
      position_name?: string;
      job_id?: string;
    } = {
      resume_id: resumeId,
      jd_text: jdText || null,
    };
    if (companyName && positionName) {
      payload.company_name = companyName;
      payload.position_name = positionName;
      if (jobId) {
        payload.job_id = jobId;
      }
      localStorage.setItem("company_name", companyName);
      localStorage.setItem("position_name", positionName);
      if (jobId) {
        localStorage.setItem("job_id", jobId);
      }
    }
    const res = await api.exportDocx(payload);
    setLoading(false);
    if (!res.ok) {
      setExportStatus(null);
      setError(res.error);
      return;
    }
    const { final_resume_docx_path, resume_docx_path } = res.data;
    const targetPath = final_resume_docx_path || resume_docx_path;
    setExportStatus(targetPath ? `Saved to ${targetPath}` : "DOCX saved.");
  };

  const handleSelectBullet = (role: ExperienceRole, idx: number) => {
    setActiveRole(role);
    setActiveBulletIndex(idx);
    setBulletDraft(role.bullets[idx]);
    setRewriteResult(null);
  };

  const handleSaveBullet = async () => {
    if (!resumeId || !activeRole || activeBulletIndex === null) return;
    setLoading(true);
    const res = await api.editBullet(resumeId, {
      role_selector: { role_id: activeRole.role_id },
      bullet_index: activeBulletIndex,
      new_bullet: bulletDraft,
      export_docx: false,
    });
    setLoading(false);
    if (!res.ok) {
      setError(res.error);
      return;
    }
    setError(null);
    await loadResume(resumeId);
  };

  const handleRewrite = async () => {
    if (!resumeId || !activeRole || activeBulletIndex === null) return;
    setLoading(true);
    const res = await api.rewriteBullet(resumeId, {
      role_selector: { role_id: activeRole.role_id },
      bullet_index: activeBulletIndex,
      jd_text: jdText || null,
    });
    setLoading(false);
    if (!res.ok) {
      setError(res.error);
      return;
    }
    setRewriteResult(res.data);
    setBulletDraft(res.data.rewritten_bullet);
  };

  const handleAts = async () => {
    if (!resumeId || !jdText.trim()) {
      setError("JD text required for ATS scoring.");
      return;
    }
    setLoading(true);
    const res = await api.atsScore({ jd_text: jdText, resume_id: resumeId, top_n_skills: 25, strict_mode: true });
    setLoading(false);
    if (!res.ok) {
      setError(res.error);
      return;
    }
    setAts(res.data);
    setError(null);
  };

  const handleSuggestPatches = async () => {
    if (!resumeId || !jdText.trim()) return;
    setLoading(true);
    const res = await api.suggestPatches(resumeId, { jd_text: jdText, strict_mode: true, apply_overrides: true, truth_mode: "balanced" });
    setLoading(false);
    if (!res.ok) {
      setError(res.error);
      return;
    }
    setPatches(res.data);
  };

  const handleApplyPatch = async (patch: SuggestPatchesResponse["suggested_patches"][number]) => {
    if (!resumeId) return;
    setLoading(true);
    const res = await api.applyPatches(resumeId, { patches: [patch], export_docx: false, truth_mode: "balanced" });
    setLoading(false);
    if (!res.ok) {
      setError(res.error);
      return;
    }
    await loadResume(resumeId);
    setError(null);
  };

  const summaryLines = useMemo(() => (data?.state.sections.professional_summary || "").split("\n").filter(Boolean), [data]);

  return (
    <div className={styles.page}>
      <div className={styles.container}>
        <section className={styles.main}>
          <div className={styles.previewCard}>
            <h2 className={styles.previewTitle}>Resume Preview {resumeId ? `• ${resumeId}` : ""}</h2>
            <div className={styles.previewContent}>
              {!data && !error && <div>Load a resume to begin.</div>}
              {loading && <div>Loading...</div>}
              {error && <div style={{ color: "#dc2626" }}>{error}</div>}
              {data && (
                <div className={styles.previewSections}>
                  <div className={styles.previewSectionBlock}>
                    <h3 className={styles.previewSectionTitle}>Professional Summary</h3>
                    {summaryLines.map((line, idx) => (
                      <p key={idx} className={styles.previewSectionText}>{line}</p>
                    ))}
                  </div>
                  <div className={styles.previewSectionBlock}>
                    <h3 className={styles.previewSectionTitle}>Technical Skills</h3>
                    <p className={styles.previewSectionText}>{data.state.sections.technical_skills.join(" • ")}</p>
                  </div>
                  {data.state.sections.experience.map((role) => (
                    <div key={role.role_id} className={styles.previewSectionBlock}>
                      <h3 className={styles.previewSectionTitle}>
                        {role.company} {role.title ? `• ${role.title}` : ""} {role.dates ? ` (${role.dates})` : ""}
                      </h3>
                      <ul style={{ paddingLeft: "1.2rem", margin: 0 }}>
                        {role.bullets.map((b, idx) => (
                          <li key={idx} style={{ marginBottom: 8 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                              <span style={{ flex: 1 }}>{b}</span>
                              <button
                                className={styles.actionButton + " secondary"}
                                onClick={() => handleSelectBullet(role, idx)}
                              >
                                Edit
                              </button>
                            </div>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </section>

        <aside className={styles.actions}>
          <div className={styles.actionsTitle}>AI Actions</div>
          <div className={styles.actionsStack}>
            {/* Company, Role, Job ID fields removed from editor page to prevent user changes */}
            {/* JD field removed from editor page to prevent user changes */}
            <button className={styles.actionButton} onClick={handleExportDocx} disabled={loading || !resumeId}>
              {loading ? "Working..." : "Save as DOCX"}
            </button>
            <button className={styles.actionButton} onClick={handleRegenerate} disabled={loading || !jdText.trim()}>
              {loading ? "Working..." : "Regenerate Resume"}
            </button>
            <button className={styles.actionButton} onClick={handleAts} disabled={loading}>Run ATS Score</button>
            <button className={styles.actionButton} onClick={handleSuggestPatches} disabled={loading}>Suggest Patches</button>
            {exportStatus && <div style={{ color: "#0f172a", fontSize: 14 }}>{exportStatus}</div>}
            {regenStatus && <div style={{ color: "#0f172a", fontSize: 14 }}>{regenStatus}</div>}

            {ats && (
              <div className={styles.atsPanel}>
                <div className={styles.atsPanelHeader}>ATS Score</div>
                <div className={styles.atsScoreRow}>
                  <span className={styles.atsScoreValue}>{ats.ats_score}</span>
                  <span className={styles.atsScoreSuffix}>/100</span>
                </div>
                <div className={styles.atsBarTrack}>
                  <div className={styles.atsBarFill} style={{ width: `${ats.ats_score}%` }} />
                </div>
                <div className={styles.atsHint}>Missing required: {ats.missing_required.join(", ") || "None"}</div>
              </div>
            )}

            {patches?.suggested_patches?.length ? (
              <div className={styles.atsPanel}>
                <div className={styles.atsPanelHeader}>Suggested Patches</div>
                {patches.suggested_patches.slice(0, 5).map((p, idx) => (
                  <div key={idx} style={{ marginBottom: 10 }}>
                    <div style={{ fontWeight: 600 }}>{p.action} • {p.section}</div>
                    <div style={{ fontSize: 14, color: "#334155" }}>{p.new_bullet}</div>
                    <button className={styles.actionButton} style={{ marginTop: 6 }} onClick={() => handleApplyPatch(p)} disabled={loading}>Apply</button>
                  </div>
                ))}
              </div>
            ) : null}

            {activeRole && activeBulletIndex !== null && (
              <div className={styles.atsPanel}>
                <div className={styles.atsPanelHeader}>Edit Bullet</div>
                <div style={{ fontWeight: 600, marginBottom: 6 }}>
                  {activeRole.company} • {activeRole.title || ""}
                </div>
                <textarea
                  value={bulletDraft}
                  onChange={(e) => setBulletDraft(e.target.value)}
                  style={{ minHeight: 100, width: "100%", resize: "vertical", borderRadius: 8, border: "1px solid #e5e7eb", padding: 10 }}
                />
                {rewriteResult && (
                  <div style={{ color: "#16a34a", fontWeight: 600, marginTop: 6 }}>
                    AI rewrite ready. Review and Save.
                  </div>
                )}
                <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                  <button className={styles.actionButton} onClick={handleSaveBullet} disabled={loading}>Save Bullet</button>
                  <button className={styles.actionButton + " secondary"} onClick={handleRewrite} disabled={loading}>Rewrite with AI</button>
                </div>
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
