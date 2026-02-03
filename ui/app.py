import os
import subprocess
import sys
from pathlib import Path
import streamlit as st

from api_client import ApiClient
from utils import role_options, extract_resume_text


st.set_page_config(page_title="Resume RAG UI", layout="wide")


def _init_state():
    defaults = {
        "backend_url": os.getenv("BACKEND_URL", "http://127.0.0.1:8000"),
        "jd_text": "",
        "company_name": "",
        "position_name": "",
        "job_id": "",
        "truth_mode": "balanced",
        "top_k": 25,
        "multi_query": False,
        "parse_with_claude": False,
        "domain_rewrite": False,
        "target_company_type": "",
        "bullets_per_role": 15,
        "resume_id": "",
        "resume_text_preview": "",
        "resume_state": None,
        "retrieved_chunks": None,
        "ats_report": None,
        "blocked_plan": None,
        "suggested_patches": None,
        "blocked_suggestions": None,
        "overrides_saved_count": 0,
        "last_export_data": None,
        "status_export": "",
        "status_load": "",
        "status_generate": "",
        "status_apply": "",
        "status_open": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


_init_state()

client = ApiClient(st.session_state.backend_url)


def _get_export_open_target(export_data: dict | None) -> str | None:
    if not export_data:
        return None
    for key in ("final_resume_docx_path", "resume_docx_path", "final_saved_dir", "saved_dir"):
        value = export_data.get(key)
        if value:
            return str(value)
    return None


def _open_path_in_file_manager(path_value: str) -> tuple[bool, str]:
    try:
        target = Path(path_value)
        if not target.exists():
            return False, f"Path does not exist: {target}"
        if os.name == "nt":
            if target.is_file():
                subprocess.Popen(["explorer", f"/select,{target}"])
            else:
                os.startfile(str(target))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(target)] if target.is_file() else ["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target.parent if target.is_file() else target)])
        return True, "Opened saved resume location."
    except Exception as exc:
        return False, str(exc)


def _export_docx_from_preview() -> bool:
    """Export using the edited preview text (no resume_id needed)."""
    # reset status each attempt
    st.session_state.status_export = ""
    st.session_state.status_export_error = ""
    if not st.session_state.company_name or not st.session_state.position_name:
        st.session_state.status_export = "err"
        st.session_state.status_export_error = "company_name and position_name are required"
        return False
    if not st.session_state.jd_text.strip():
        st.session_state.status_export = "err"
        st.session_state.status_export_error = "Job description is required"
        return False
    preview_text = (st.session_state.resume_text_preview or "").strip()
    if not preview_text:
        st.session_state.status_export = "err"
        st.session_state.status_export_error = "Nothing to export"
        return False

    payload = {
        "company_name": st.session_state.company_name,
        "position_name": st.session_state.position_name,
        "job_id": st.session_state.job_id or None,
        "jd_text": st.session_state.jd_text,
        "resume_text": preview_text,
    }
    res = client.post("/export-docx-from-text", json_body=payload)
    if res.get("ok"):
        st.session_state.last_export_data = res["data"]
        st.session_state.status_export = "ok"
        st.session_state.status_export_error = ""
        return True

    st.session_state.status_export = "err"
    st.session_state.status_export_error = res.get("error", "Export failed")
    return False


def _apply_edits_to_resume(preview_text: str) -> bool:
    if not st.session_state.resume_id:
        st.session_state.status_apply = "err"
        st.session_state.status_apply_error = "resume_id required to persist edits"
        return False
    if not preview_text.strip():
        st.session_state.status_apply = "err"
        st.session_state.status_apply_error = "Edited text is empty"
        return False
    payload = {"resume_text": preview_text, "jd_text": st.session_state.jd_text}
    res = client.post(f"/resumes/{st.session_state.resume_id}/replace-text", json_body=payload)
    if res.get("ok"):
        st.session_state.status_apply = "ok"
        st.session_state.status_apply_error = ""
        return True
    st.session_state.status_apply = "err"
    st.session_state.status_apply_error = res.get("error", "Failed to persist edits")
    return False


st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Sora:wght@400;500;600&display=swap');
:root {
  --bg: #0f1116;
  --panel: #171b22;
  --panel-2: #1d222b;
  --border: #2a2f3a;
  --text: #e7ebf2;
  --muted: #9aa4b2;
  --accent: #ffb347;
}
html, body, [class*='css'] {
  font-family: 'Sora', sans-serif;
}
.stApp {
  background: radial-gradient(1200px 800px at 10% 10%, #1b2230 0%, #0f1116 45%, #0b0d12 100%);
  color: var(--text);
}
.stApp header[data-testid="stHeader"] {
  display: none;
}
[data-testid="stToolbar"] {
  display: none;
}
[data-testid="stDecoration"] {
  display: none;
}
[data-testid="stStatusWidget"] {
  display: none;
}
#MainMenu {
  visibility: hidden;
}
.block-container { padding-top: 0.9rem; padding-bottom: 2rem; }
.section-label {
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted);
}
.preview-box {
  background: #0b0d12;
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1rem;
}
.copy-btn-inline {
  background: var(--panel-2);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 4px 10px;
  font-size: 0.9rem;
  cursor: pointer;
}
.copy-btn-inline:hover {
  background: #252b36;
}
/* Tighten vertical spacing between headings/sections */
h1, h2, h3, h4, h5, h6 {
  margin-bottom: 0.35rem;
  margin-top: 0.35rem;
}
.stMarkdown { margin-bottom: 0.25rem; }
button[aria-label="Apply Edits to Resume"] {
  padding: 0.45rem 0.95rem !important;
  font-size: 0.95rem !important;
  font-weight: 600;
}
</style>""", unsafe_allow_html=True)

@st.dialog("Test")
def _backend_url_dialog():
    current = st.session_state.backend_url
    st.text_input("Test", key="backend_url_dialog", value=current)
    candidate = (st.session_state.get("backend_url_dialog") or "").strip()

    action_cols = st.columns(2, gap="small")
    with action_cols[0]:
        if st.button("Save URL", key="save_backend_url_dialog"):
            if not candidate:
                st.error("Test cannot be empty")
            else:
                st.session_state.backend_url = candidate
                st.success("Test updated")
                st.rerun()
    with action_cols[1]:
        if st.button("Save + Health Check", key="save_health_backend_url_dialog"):
            if not candidate:
                st.error("Test cannot be empty")
            else:
                st.session_state.backend_url = candidate
                probe_client = ApiClient(candidate)
                health = probe_client.get("/health")
                if health["ok"]:
                    st.success("Connected")
                    st.json(health["data"])
                else:
                    st.error(f"Health check failed: {health['error']}")


@st.dialog("Load")
def _load_resume_dialog():
    st.text_input("Existing resume_id", value=st.session_state.resume_id, key="resume_id_input")
    if st.button("Load State", key="load_resume_dialog"):
        resume_id_input = (st.session_state.get("resume_id_input") or "").strip()
        if not resume_id_input:
            st.error("Please enter a resume_id")
        else:
            res = client.get(f"/resumes/{resume_id_input}")
            if res["ok"]:
                st.session_state.resume_id = resume_id_input
                st.session_state.resume_state = res["data"].get("state")
                st.session_state.resume_text_preview = extract_resume_text(st.session_state.resume_state)
                jd_loaded = res["data"].get("jd_text")
                if jd_loaded:
                    st.session_state.jd_text = jd_loaded
                st.success("Loaded resume state")
                st.rerun()
            else:
                st.error(res["error"])


@st.dialog("ATS Score + Skill Gaps")
def _ats_score_dialog():
    st.text_area("JD text (required for ATS)", key="jd_text_ats_popup", height=180, value=st.session_state.jd_text)
    jd_ats = (st.session_state.get("jd_text_ats_popup") or "").strip()
    if jd_ats:
        st.session_state.jd_text = jd_ats

    if st.button("Run ATS Score", key="run_ats_score_popup"):
        if not st.session_state.resume_id:
            st.error("resume_id required")
        elif not st.session_state.jd_text.strip():
            st.error("JD text is required")
        else:
            payload = {
                "jd_text": st.session_state.jd_text,
                "resume_id": st.session_state.resume_id,
                "top_n_skills": 25,
                "strict_mode": True,
            }
            resp = client.post("/ats-score", json_body=payload)
            if resp["ok"]:
                st.session_state.ats_report = resp["data"]
                st.success("ATS score computed")
            else:
                st.error(resp["error"])

    if not st.session_state.ats_report:
        st.info("Run ATS Score to view skill gaps.")
        return

    report = st.session_state.ats_report
    st.metric("ATS Score", report.get("ats_score", 0))

    required_rows = []
    for item in report.get("required", []):
        ev = item.get("evidence", [])
        ev_str = ", ".join(
            [f"{e.get('section')}:{e.get('role_id','')}/{e.get('bullet_index','')}" for e in ev]
        )
        required_rows.append({"skill": item.get("skill"), "status": item.get("status"), "evidence": ev_str})

    preferred_rows = []
    for item in report.get("preferred", []):
        ev = item.get("evidence", [])
        ev_str = ", ".join(
            [f"{e.get('section')}:{e.get('role_id','')}/{e.get('bullet_index','')}" for e in ev]
        )
        preferred_rows.append({"skill": item.get("skill"), "status": item.get("status"), "evidence": ev_str})

    st.subheader("Required Skills")
    st.dataframe(required_rows, use_container_width=True, height=220)
    st.subheader("Preferred Skills")
    st.dataframe(preferred_rows, use_container_width=True, height=220)

    missing_required = report.get("missing_required", [])
    missing_preferred = report.get("missing_preferred", [])
    if missing_required:
        st.write("Missing Required:", missing_required)
    if missing_preferred:
        st.write("Missing Preferred:", missing_preferred)

    if not (missing_required or missing_preferred):
        st.info("All required skills are covered. Score may be capped if preferred skills are not detected.")
        return

    st.subheader("Include Missing Skills")
    if not st.session_state.resume_state:
        state_res = client.get(f"/resumes/{st.session_state.resume_id}")
        if state_res["ok"]:
            st.session_state.resume_state = state_res["data"].get("state")
    roles = role_options(st.session_state.resume_state or {})
    role_labels = [r[0] for r in roles]
    role_ids = [r[1] for r in roles]

    selected_items = []
    all_missing = list(missing_required) + list(missing_preferred)
    for idx, skill in enumerate(all_missing):
        include_key = f"ats_popup_include_skill_{idx}"
        role_key = f"ats_popup_include_role_{idx}"
        level_key = f"ats_popup_include_level_{idx}"
        bullet_key = f"ats_popup_include_bullet_{idx}"

        if st.checkbox(f"Include: {skill}", key=include_key):
            if roles:
                role_choice = st.selectbox(
                    f"Target Role for {skill}",
                    role_labels,
                    key=role_key,
                )
                role_id = role_ids[role_labels.index(role_choice)]
            else:
                role_id = ""
                st.warning("No roles available in resume state.")

            level = st.selectbox(
                f"Evidence Level for {skill}",
                options=["hands_on", "worked_with", "exposure"],
                key=level_key,
            )
            proof = st.text_area(
                f"Proof bullet for {skill} (optional)",
                key=bullet_key,
                placeholder="Optional: add context. Leave blank to auto-generate.",
            )
            selected_items.append(
                {
                    "skill": skill,
                    "level": level,
                    "role_id": role_id,
                    "proof_bullet": proof,
                }
            )

    if st.button("Include Selected Skills", key="include_selected_skills_ats_popup"):
        if not selected_items:
            st.error("Select at least one skill to include")
        else:
            invalid = [item for item in selected_items if not item["role_id"]]
            if invalid:
                st.error("Each selected skill needs a role")
            else:
                payload = {
                    "items": selected_items,
                    "jd_text": st.session_state.jd_text,
                    "truth_mode": st.session_state.truth_mode,
                    "strict_mode": True,
                    "rewrite_overrides_with_claude": True,
                    "export_docx": False,
                }
                res = client.post(
                    f"/resumes/{st.session_state.resume_id}/include-skills",
                    json_body=payload,
                )
                if res["ok"]:
                    st.success("Skills added to resume")
                    state_res = client.get(f"/resumes/{st.session_state.resume_id}")
                    if state_res["ok"]:
                        st.session_state.resume_state = state_res["data"].get("state")
                    else:
                        st.session_state.resume_state = res["data"].get("state")
                    if st.session_state.resume_state:
                        st.session_state.resume_text_preview = extract_resume_text(st.session_state.resume_state)
                else:
                    st.error(res["error"])


header_left, header_right = st.columns([1.6, 1.4], gap="large")
with header_left:
    st.markdown("""<div style='font-size:1.6rem;font-weight:600;'>Resume Generator</div>
<div style='color:#9aa4b2;margin-bottom:1rem;'>JD-driven resume builder with skill confirmation</div>""", unsafe_allow_html=True)
with header_right:
    top_right_controls = st.columns([1, 1, 1, 1, 1], gap="small")
    with top_right_controls[0]:
        if st.button("Backend URL", key="backend_url_top"):
            _backend_url_dialog()
    with top_right_controls[1]:
        if st.button("Load Resume", key="load_resume_top"):
            _load_resume_dialog()
    with top_right_controls[2]:
        save_label = "Save DOCX + JD"
        if st.session_state.status_export == "ok":
            save_label = "✓ Saved"
        elif st.session_state.status_export == "err":
            save_label = "✕ Save failed"
        if st.button(save_label, key="save_docx_quick_top"):
            _export_docx_from_preview()
    with top_right_controls[3]:
        export_target_top = _get_export_open_target(st.session_state.get("last_export_data"))
        open_disabled = not bool(export_target_top)
        open_label = "Open Folder"
        if st.session_state.status_open == "ok":
            open_label = "✓ Opened"
        elif st.session_state.status_open == "err":
            open_label = "✕ Open failed"
        if st.button(open_label, key="open_saved_resume_location_top", disabled=open_disabled):
            ok, msg = _open_path_in_file_manager(export_target_top or "")
            if ok:
                st.session_state.status_open = "ok"
            else:
                st.session_state.status_open = "err"
                st.session_state.status_open_error = msg
    with top_right_controls[4]:
        if st.button("ATS Popup", key="open_ats_popup_top"):
            _ats_score_dialog()
    if st.session_state.status_export == "ok":
        st.markdown("<span style='color:#48c774;font-size:0.9rem;'>✓ DOCX + JD saved</span>", unsafe_allow_html=True)
    elif st.session_state.status_export == "err":
        err_msg = st.session_state.get("status_export_error", "Save failed")
        st.markdown(f"<span style='color:#ff4d4f;font-size:0.9rem;'>✕ {err_msg}</span>", unsafe_allow_html=True)

col_left, col_right = st.columns([1, 1.15], gap='large')

with col_left:
    top_controls = st.columns([2.1, 2.1, 1.2], gap="small")
    with top_controls[0]:
        st.text_input("Company Name", key="company_name", label_visibility="visible")
    with top_controls[1]:
        st.text_input("Position Name", key="position_name", label_visibility="visible")
    with top_controls[2]:
        st.text_input("Job ID (optional)", key="job_id", label_visibility="visible")

    st.text_area("Job Description", key="jd_text", height=160)

    # B) Generation Controls
    with st.container(border=True):
        st.markdown("#### Generation Controls")
        with st.expander("Advanced Options", expanded=False):
            st.selectbox("Truth Mode", options=["off", "balanced", "strict"], key="truth_mode")
            st.number_input("Top K", min_value=5, max_value=60, key="top_k")
            st.checkbox("Multi Query Retrieval", key="multi_query")
            st.checkbox("Parse JD with Claude", key="parse_with_claude")
            st.checkbox("Domain Rewrite", key="domain_rewrite")
            st.selectbox(
                "Target Company Type",
                options=["", "startup", "enterprise", "regulated", "bigtech"],
                key="target_company_type",
            )
            st.number_input("Bullets per Role", min_value=5, max_value=25, key="bullets_per_role")

        action_row = st.columns([1.1, 1.1, 1], gap="small")
        with action_row[0]:
            if st.button("Generate Preview"):
                if not st.session_state.jd_text.strip():
                    st.error("JD text is required")
                else:
                    payload = {
                        "jd_text": st.session_state.jd_text,
                        "top_k": st.session_state.top_k,
                        "multi_query": st.session_state.multi_query,
                        "parse_with_claude": st.session_state.parse_with_claude,
                        "audit": False,
                        "domain_rewrite": st.session_state.domain_rewrite,
                        "target_company_type": st.session_state.target_company_type or None,
                        "bullets_per_role": st.session_state.bullets_per_role,
                    }
                    resp = client.post("/generate", json_body=payload)
                    if resp["ok"]:
                        data = resp["data"]
                        st.session_state.resume_id = data.get("resume_id", "")
                        st.session_state.resume_text_preview = data.get("resume_text", "")
                        st.session_state.retrieved_chunks = data.get("retrieved", [])
                        st.session_state.ats_report = None
                        st.session_state.blocked_plan = None
                        st.session_state.suggested_patches = None
                        st.success(f"Generated. resume_id={st.session_state.resume_id}")
                    else:
                        st.error(resp["error"])
        with action_row[1]:
            if st.button("Load Latest State"):
                if not st.session_state.resume_id:
                    st.error("resume_id required")
                else:
                    res = client.get(f"/resumes/{st.session_state.resume_id}")
                    if res["ok"]:
                        st.session_state.resume_state = res["data"].get("state")
                        st.session_state.resume_text_preview = extract_resume_text(st.session_state.resume_state)
                        st.success("State refreshed")
                    else:
                        st.error(res["error"])
        with action_row[2]:
            if st.button("ATS Popup", key="open_ats_popup_left_controls"):
                _ats_score_dialog()

    # C) ATS Score + Skill Gaps
    with st.expander("ATS Score + Skill Gaps", expanded=False):
        st.caption("Use the ATS popup for scoring, gap analysis, and skill include flow.")
        if st.button("Open ATS Popup", key="open_ats_popup_left"):
            _ats_score_dialog()

    # D) Blocked Plan + Overrides
    with st.expander("Blocked Plan + Overrides (Remediation)", expanded=False):
        if st.session_state.truth_mode == "off":
            st.info("Enable truth_mode to use blocked plan.")
        elif not st.session_state.resume_id:
            st.info("Generate or load a resume_id first.")
        else:
            top_n = st.number_input("Top N blocked", min_value=1, max_value=50, value=10)
            if st.button("Get Blocked Plan"):
                payload = {
                    "jd_text": st.session_state.jd_text,
                    "truth_mode": st.session_state.truth_mode,
                    "top_n": top_n,
                    "strict_mode": True,
                }
                resp = client.post(f"/resumes/{st.session_state.resume_id}/blocked-plan", json_body=payload)
                if resp["ok"]:
                    st.session_state.blocked_plan = resp["data"].get("blocked", [])
                    st.success("Blocked plan ready")
                else:
                    st.error(resp["error"])

            if st.session_state.blocked_plan:
                if not st.session_state.resume_state:
                    res = client.get(f"/resumes/{st.session_state.resume_id}")
                    if res["ok"]:
                        st.session_state.resume_state = res["data"].get("state")
                roles = role_options(st.session_state.resume_state or {})
                role_labels = [r[0] for r in roles]
                role_ids = [r[1] for r in roles]

                for idx, item in enumerate(st.session_state.blocked_plan):
                    skill = item.get("skill", "")
                    reason = item.get("reason", "")
                    suggested = item.get("suggested_role_ids", [])
                    example = item.get("example_override_payload") or {}
                    example_bullet = ""
                    try:
                        example_bullet = example.get("skills", [])[0].get("proof_bullets", [""])[0]
                    except (IndexError, AttributeError):
                        example_bullet = ""

                    st.markdown(f"**{skill}** - {reason}")
                    if roles:
                        default_idx = 0
                        if suggested:
                            for sid in suggested:
                                if sid in role_ids:
                                    default_idx = role_ids.index(sid)
                                    break
                        role_choice = st.selectbox(
                            f"Target Role for {skill}",
                            role_labels,
                            index=default_idx,
                            key=f"blocked_role_{idx}",
                        )
                        role_id = role_ids[role_labels.index(role_choice)]
                    else:
                        role_id = ""
                        st.warning("No roles available in resume state.")

                    confirm = st.checkbox("I confirm hands-on experience", key=f"blocked_confirm_{idx}")
                    level = "hands_on" if confirm else "worked_with"
                    bullet_text = st.text_area(
                        f"Proof Bullet for {skill} (optional)",
                        value=example_bullet,
                        key=f"blocked_bullet_{idx}",
                    )

                    if st.button(f"Save Override for {skill}"):
                        if not role_id:
                            st.error("Role is required")
                        else:
                            payload = {
                                "items": [
                                    {
                                        "skill": skill,
                                        "level": level,
                                        "role_id": role_id,
                                        "proof_bullet": bullet_text,
                                    }
                                ],
                                "jd_text": st.session_state.jd_text,
                                "truth_mode": st.session_state.truth_mode,
                                "strict_mode": True,
                                "rewrite_overrides_with_claude": True,
                                "export_docx": False,
                            }
                            res = client.post(
                                f"/resumes/{st.session_state.resume_id}/include-skills",
                                json_body=payload,
                            )
                            if res["ok"]:
                                st.session_state.overrides_saved_count += 1
                                st.success("Skill added to resume")
                                state_res = client.get(f"/resumes/{st.session_state.resume_id}")
                                if state_res["ok"]:
                                    st.session_state.resume_state = state_res["data"].get("state")
                                else:
                                    st.session_state.resume_state = res["data"].get("state")
                                if st.session_state.resume_state:
                                    st.session_state.resume_text_preview = extract_resume_text(
                                        st.session_state.resume_state
                                    )
                            else:
                                st.error(res["error"])

                st.write(f"Overrides Saved: {st.session_state.overrides_saved_count}")

                st.markdown("---")
                st.subheader("Add Override Manually")
                manual_skill = st.text_input("Skill", key="manual_override_skill")
                manual_level = st.selectbox(
                    "Level",
                    options=["hands_on", "worked_with", "exposure"],
                    key="manual_override_level",
                )
                if not st.session_state.resume_state:
                    res_state = client.get(f"/resumes/{st.session_state.resume_id}")
                    if res_state["ok"]:
                        st.session_state.resume_state = res_state["data"].get("state")
                roles = role_options(st.session_state.resume_state or {})
                role_labels = [r[0] for r in roles]
                role_ids = [r[1] for r in roles]
                if roles:
                    manual_role_label = st.selectbox("Target Role", role_labels, key="manual_override_role")
                    manual_role_id = role_ids[role_labels.index(manual_role_label)]
                else:
                    manual_role_id = ""
                    st.warning("No roles available in resume state.")
                manual_bullet = st.text_area(
                    "Proof Bullet",
                    key="manual_override_bullet",
                    height=80,
                )
                if st.button("Save Manual Override"):
                    if not manual_skill.strip():
                        st.error("Skill is required")
                    elif not manual_role_id:
                        st.error("Role is required")
                    elif not manual_bullet.strip():
                        st.error("Proof bullet is required")
                    else:
                        payload = {
                            "items": [
                                {
                                    "skill": manual_skill.strip(),
                                    "level": manual_level,
                                    "role_id": manual_role_id,
                                    "proof_bullet": manual_bullet.strip(),
                                }
                            ],
                            "jd_text": st.session_state.jd_text,
                            "truth_mode": st.session_state.truth_mode,
                            "strict_mode": True,
                            "rewrite_overrides_with_claude": True,
                            "export_docx": False,
                        }
                        res = client.post(
                            f"/resumes/{st.session_state.resume_id}/include-skills",
                            json_body=payload,
                        )
                        if res["ok"]:
                            st.session_state.overrides_saved_count += 1
                            st.success("Skill added to resume")
                            state_res = client.get(f"/resumes/{st.session_state.resume_id}")
                            if state_res["ok"]:
                                st.session_state.resume_state = state_res["data"].get("state")
                            else:
                                st.session_state.resume_state = res["data"].get("state")
                            if st.session_state.resume_state:
                                st.session_state.resume_text_preview = extract_resume_text(
                                    st.session_state.resume_state
                                )
                        else:
                            st.error(res["error"])

    # F) Manual Bullet Edit
    with st.expander("Manual Bullet Edit", expanded=False):
        if st.button("Refresh Resume State"):
            if st.session_state.resume_id:
                res = client.get(f"/resumes/{st.session_state.resume_id}")
                if res["ok"]:
                    st.session_state.resume_state = res["data"].get("state")
                    st.session_state.resume_text_preview = extract_resume_text(st.session_state.resume_state)
                    st.success("State refreshed")
                else:
                    st.error(res["error"])

        if st.session_state.resume_state:
            roles = role_options(st.session_state.resume_state)
            labels = [r[0] for r in roles]
            if roles:
                role_choice = st.selectbox("Role", labels, key="manual_role")
                role = roles[labels.index(role_choice)][2]
                role_id = role.get("role_id")
                bullets = role.get("bullets", [])
                if bullets:
                    idx = st.selectbox("Bullet Index", list(range(len(bullets))), key="manual_bullet_index")
                    new_bullet = st.text_area("Edit Bullet", value=bullets[idx], key="manual_bullet_text")
                    if st.button("Save Bullet"):
                        updated_bullet = new_bullet
                        if len(updated_bullet.strip()) < 10:
                            st.error("Bullet too short (min 10 chars)")
                        else:
                            payload = {
                                "role_selector": {"role_id": role_id},
                                "bullet_index": idx,
                                "new_bullet": updated_bullet,
                                "export_docx": False,
                            }
                            res = client.patch(f"/resumes/{st.session_state.resume_id}/bullet", json_body=payload)
                            if res["ok"]:
                                st.success("Bullet updated")
                                state = client.get(f"/resumes/{st.session_state.resume_id}")
                                if state["ok"]:
                                    st.session_state.resume_state = state["data"].get("state")
                                    st.session_state.resume_text_preview = extract_resume_text(st.session_state.resume_state)
                            else:
                                st.error(res["error"])
                else:
                    st.info("No bullets found")
            else:
                st.info("No roles available")

with col_right:
    header_cols = st.columns([5, 1])
    with header_cols[0]:
        if st.session_state.resume_id:
            st.markdown(
                f"<div style='font-size:1.1rem;font-weight:600;'>Resume Preview — Resume ID: <code>{st.session_state.resume_id}</code></div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown("<div style='font-size:1.1rem;font-weight:600;'>Resume Preview</div>", unsafe_allow_html=True)
    with header_cols[1]:
        if st.session_state.resume_text_preview:
            btn_label = "✅" if st.session_state.status_apply == "ok" else ("❌" if st.session_state.status_apply == "err" else "Apply Edits")
            if st.button(btn_label, key="persist_preview_edits"):
                _apply_edits_to_resume(st.session_state.resume_text_preview)
        elif st.session_state.status_apply == "err":
            st.markdown("<span style='color:#ff4d4f; font-size:0.9rem;'>❌ Edit failed</span>", unsafe_allow_html=True)

    if st.session_state.ats_report:
        report = st.session_state.ats_report
        st.metric("ATS Score", report.get('ats_score', 0))
        missing_required = report.get('missing_required', [])
        missing_preferred = report.get('missing_preferred', [])
        if missing_required:
            st.write('Missing Required:', missing_required)
        if missing_preferred:
            st.write('Missing Preferred:', missing_preferred)

    if st.session_state.resume_text_preview:
        copy_row = st.columns([5, 1])
        with copy_row[0]:
            st.markdown("**Resume Preview (editable)**")
        with copy_row[1]:
            st.markdown(
                """
                <div style="display:flex; justify-content:flex-end;">
                  <button class="copy-btn-inline" aria-label="Copy resume" onclick="
                    const ta = document.querySelector('textarea[aria-label=\\\\\"resume_preview_editor\\\\\"]');
                    if (ta) {
                      navigator.clipboard.writeText(ta.value).then(() => {
                        this.innerText='✓';
                        setTimeout(()=>{this.innerText='📋';},1200);
                      }).catch(() => {
                        this.innerText='✕';
                        setTimeout(()=>{this.innerText='📋';},1200);
                      });
                    } else {
                      this.innerText='✕';
                      setTimeout(()=>{this.innerText='📋';},1200);
                    }
                  ">📋</button>
                </div>
                """,
                unsafe_allow_html=True,
            )
        edited = st.text_area(
            "resume_preview_editor",
            value=st.session_state.resume_text_preview,
            height=500,
            key="resume_preview_editor",
            label_visibility="collapsed",
        )
        # Keep latest edits in session state
        st.session_state.resume_text_preview = edited
        st.caption("Use top Save DOCX button to export the edited text; apply edits persists to stored resume.")
    else:
        st.info('Generate or load a resume to see the preview.')

    if st.session_state.retrieved_chunks:
        with st.expander('Retrieved Chunks', expanded=False):
            st.json(st.session_state.retrieved_chunks)
