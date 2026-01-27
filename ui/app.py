import os
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
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


_init_state()

client = ApiClient(st.session_state.backend_url)



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
.block-container { padding-top: 2.6rem; padding-bottom: 2rem; }
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
</style>""", unsafe_allow_html=True)

st.markdown("""<div style='font-size:1.6rem;font-weight:600;'>Resume Generator</div>
<div style='color:#9aa4b2;margin-bottom:1rem;'>JD-driven resume builder with skill confirmation</div>""", unsafe_allow_html=True)

col_left, col_right = st.columns([1, 1.15], gap='large')

with col_left:
    # A) Connection / Health
    with st.expander("Connection / Health", expanded=True):
        st.text_input("Backend URL", key="backend_url")
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("Health Check"):
                health = client.get("/health")
                if health["ok"]:
                    st.success("Connected")
                    st.json(health["data"])
                else:
                    st.error(f"Health check failed: {health['error']}")
        with col2:
            st.write("Backend URL can be changed and reloaded anytime.")

    # Load existing resume_id
    with st.expander("Load Existing Resume ID", expanded=False):
        resume_id_input = st.text_input("Existing resume_id", value=st.session_state.resume_id)
        if st.button("Load Resume State"):
            if not resume_id_input.strip():
                st.error("Please enter a resume_id")
            else:
                res = client.get(f"/resumes/{resume_id_input.strip()}")
                if res["ok"]:
                    st.session_state.resume_id = resume_id_input.strip()
                    st.session_state.resume_state = res["data"].get("state")
                    st.session_state.resume_text_preview = extract_resume_text(st.session_state.resume_state)
                    jd_loaded = res["data"].get("jd_text")
                    if jd_loaded:
                        st.session_state.jd_text = jd_loaded
                    st.success("Loaded resume state")
                else:
                    st.error(res["error"])

    # B) Job Info + Generation
    with st.expander("Job Info + Generation", expanded=True):
        st.text_input("Company Name", key="company_name")
        st.text_input("Position Name", key="position_name")
        st.text_input("Job ID (optional)", key="job_id")
        st.text_area("Job Description", key="jd_text", height=200)

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

        if st.session_state.resume_id:
            if st.button("Load Latest State"):
                res = client.get(f"/resumes/{st.session_state.resume_id}")
                if res["ok"]:
                    st.session_state.resume_state = res["data"].get("state")
                    st.session_state.resume_text_preview = extract_resume_text(st.session_state.resume_state)
                    st.success("State refreshed")
                else:
                    st.error(res["error"])

    # C) ATS Score + Skill Gaps
    with st.expander("ATS Score + Skill Gaps", expanded=False):
        if not st.session_state.jd_text.strip():
            st.text_area("JD text (required for ATS)", key="jd_text_ats", height=140)
            if st.session_state.get("jd_text_ats"):
                st.session_state.jd_text = st.session_state.jd_text_ats

        if st.button("Run ATS Score"):
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

        if st.session_state.ats_report:
            report = st.session_state.ats_report
            st.metric("ATS Score", report.get("ats_score", 0))
            required_rows = []
            for item in report.get("required", []):
                ev = item.get("evidence", [])
                ev_str = ", ".join(
                    [
                        f"{e.get('section')}:{e.get('role_id','')}/{e.get('bullet_index','')}"
                        for e in ev
                    ]
                )
                required_rows.append({"skill": item.get("skill"), "status": item.get("status"), "evidence": ev_str})
            preferred_rows = []
            for item in report.get("preferred", []):
                ev = item.get("evidence", [])
                ev_str = ", ".join(
                    [
                        f"{e.get('section')}:{e.get('role_id','')}/{e.get('bullet_index','')}"
                        for e in ev
                    ]
                )
                preferred_rows.append({"skill": item.get("skill"), "status": item.get("status"), "evidence": ev_str})

            st.subheader("Required Skills")
            st.dataframe(required_rows, use_container_width=True, height=240)
            st.subheader("Preferred Skills")
            st.dataframe(preferred_rows, use_container_width=True, height=240)
            missing_required = report.get("missing_required", [])
            missing_preferred = report.get("missing_preferred", [])
            st.write("Missing Required:", missing_required)

            if missing_required or missing_preferred:
                st.subheader("Why score is low")
                if missing_required:
                    st.write("Missing Required:", missing_required)
                if missing_preferred:
                    st.write("Missing Preferred:", missing_preferred)

                with st.expander("Include excluded skills (I have this skill)", expanded=False):
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
                        include_key = f"include_skill_{idx}"
                        role_key = f"include_role_{idx}"
                        level_key = f"include_level_{idx}"
                        bullet_key = f"include_bullet_{idx}"

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

                            selected_items.append({
                                "skill": skill,
                                "level": level,
                                "role_id": role_id,
                                "proof_bullet": proof,
                            })

                    if st.button("Include Selected Skills"):
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
                                        st.session_state.resume_text_preview = extract_resume_text(
                                            st.session_state.resume_state
                                        )
                                else:
                                    st.error(res["error"])
            else:
                st.info("All required skills are covered. Score may be capped if preferred skills are not detected.")

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

    # G) Final Save to Folder (DOCX Export)
    with st.expander("Final Save to Folder (DOCX Export)", expanded=False):
        if st.button("Save DOCX + JD"):
            if not st.session_state.resume_id:
                st.error("resume_id required")
            elif not st.session_state.company_name or not st.session_state.position_name:
                st.error("company_name and position_name are required")
            else:
                payload = {
                    "resume_id": st.session_state.resume_id,
                    "company_name": st.session_state.company_name,
                    "position_name": st.session_state.position_name,
                    "job_id": st.session_state.job_id or None,
                    "jd_text": st.session_state.jd_text or None,
                }
                res = client.post("/export-docx", json_body=payload)
                if res["ok"]:
                    st.success("Export complete")
                    st.json(res["data"])
                else:
                    st.error(res["error"])

with col_right:
    st.markdown("### Resume Preview")
    if st.session_state.resume_id:
        st.markdown(f"**Resume ID:** `{st.session_state.resume_id}`")
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
        st.code(st.session_state.resume_text_preview, language='')
    else:
        st.info('Generate or load a resume to see the preview.')
    if st.session_state.retrieved_chunks:
        with st.expander('Retrieved Chunks', expanded=False):
            st.json(st.session_state.retrieved_chunks)
