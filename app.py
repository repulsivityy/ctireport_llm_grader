import os
import re
import uuid
import datetime
import streamlit as st
import pandas as pd
from dotenv import load_dotenv

from schemas import GradingResult, MultiStageGradingResult, SubmissionRecord
from parser import extract_text_from_bytes, validate_report_content, sanitize_report_text, DocumentParsingError
from grader import CTIGrader
import storage

load_dotenv()

st.set_page_config(
    page_title="CTI Report Grader",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Allowed Instructor Emails (loaded purely from environment variable INSTRUCTOR_EMAILS)
RAW_INSTRUCTOR_EMAILS = os.getenv("INSTRUCTOR_EMAILS", "")
INSTRUCTOR_EMAILS = [e.strip().lower() for e in re.split(r'[,;|\s]+', RAW_INSTRUCTOR_EMAILS) if e.strip()]

# Custom CSS Styling
st.markdown("""
<style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1E293B;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        font-size: 1.05rem;
        color: #64748B;
        margin-bottom: 1.5rem;
    }
    .score-card {
        background: linear-gradient(135deg, #0F172A 0%, #1E293B 100%);
        color: #FFFFFF;
        padding: 1.5rem;
        border-radius: 12px;
        text-align: center;
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }
    .score-number {
        font-size: 3.5rem;
        font-weight: 800;
        color: #38BDF8;
        line-height: 1;
    }
    .grade-badge {
        font-size: 1.5rem;
        font-weight: 700;
        padding: 0.2rem 1rem;
        border-radius: 8px;
        background: rgba(255, 255, 255, 0.15);
        display: inline-block;
        margin-top: 0.5rem;
    }
    .rubric-box {
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 1.2rem;
        margin-bottom: 1rem;
    }
    .metric-title {
        font-size: 1.05rem;
        font-weight: 600;
        color: #0F172A;
    }
    .author-question-box {
        background-color: #EFF6FF;
        border-left: 4px solid #3B82F6;
        padding: 1rem;
        border-radius: 6px;
        margin-bottom: 0.75rem;
    }
    .history-card {
        background-color: #F1F5F9;
        border: 1px solid #CBD5E1;
        border-radius: 8px;
        padding: 0.8rem 1rem;
        margin-bottom: 0.5rem;
    }
    .delta-badge-pos {
        color: #16A34A;
        font-weight: 700;
    }
    .delta-badge-neg {
        color: #DC2626;
        font-weight: 700;
    }
    .report-preview-box {
        background-color: #0F172A;
        color: #F8FAFC;
        padding: 1.2rem;
        border-radius: 8px;
        font-family: monospace;
        font-size: 0.9rem;
        max-height: 450px;
        overflow-y: auto;
        white-space: pre-wrap;
    }
</style>
""", unsafe_allow_html=True)


def init_session_state():
    if "user_email" not in st.session_state:
        st.session_state.user_email = ""
    if "current_result" not in st.session_state:
        st.session_state.current_result = None
    if "current_stage_result" not in st.session_state:
        st.session_state.current_stage_result = None
    if "current_submission_id" not in st.session_state:
        st.session_state.current_submission_id = None
    if "current_attempt" not in st.session_state:
        st.session_state.current_attempt = 1


init_session_state()

# Auto-detect Cloud IAP identity if deployed behind Google Identity-Aware Proxy
if hasattr(st, "experimental_user") and getattr(st.experimental_user, "is_logged_in", False):
    st.session_state.user_email = st.experimental_user.email.strip().lower()

# Check if current user email is Instructor
is_instructor = st.session_state.user_email.strip().lower() in INSTRUCTOR_EMAILS

# Sidebar Navigation
with st.sidebar:
    st.image("https://img.icons8.com/color/96/cyber-security.png", width=64)
    st.title("CTI Grader Control")
    
    st.subheader("👤 User Identity")
    email_input = st.text_input(
        "Your Email Address *",
        value=st.session_state.user_email,
        placeholder="e.g. student@domain.com",
        help="Used to track your submissions and revision history. No sign-up required."
    )
    if email_input.strip().lower() != st.session_state.user_email:
        st.session_state.user_email = email_input.strip().lower()
        st.session_state.current_result = None
        st.rerun()

    # Role badge
    if st.session_state.user_email:
        if is_instructor:
            st.success(f"👨‍🏫 **Instructor Mode Enabled**\n`{st.session_state.user_email}`")
        else:
            st.info(f"🎓 **Student Identity:**\n`{st.session_state.user_email}`")
    
    st.divider()

    # Dynamic Navigation Tabs based on Role
    nav_options = ["📝 Submit & Grade Report", "📖 Rubric Reference"]
    if is_instructor:
        nav_options.insert(1, "📊 Instructor Gradebook")
        
    app_mode = st.radio("Navigation", nav_options, index=0)


# ==============================================================================
# TAB 1: SUBMIT & GRADE REPORT (Students + Instructors)
# ==============================================================================
if app_mode == "📝 Submit & Grade Report":
    st.markdown('<div class="main-title">🛡️ Cyber Threat Intelligence Report Grader</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">Submit your CTI report to be evaluated on a 100-point scale (4 criteria × 25 pts each). Revisions are tracked automatically by your email.</div>', unsafe_allow_html=True)

    if not st.session_state.user_email:
        st.warning("👈 Please enter your **Email Address** in the sidebar to start submitting reports.")
        st.stop()

    past_attempts = storage.get_student_submissions(st.session_state.user_email)
    next_attempt_num = len(past_attempts) + 1
    
    # Display Past Attempts Summary
    if past_attempts:
        with st.expander(f"📜 Your Submission History for {st.session_state.user_email} ({len(past_attempts)} previous attempt{'s' if len(past_attempts)>1 else ''})", expanded=True):
            cols = st.columns(min(len(past_attempts), 3))
            for idx, att in enumerate(past_attempts[-3:]):
                col_target = cols[idx if idx < len(cols) else 0]
                with col_target:
                    st.markdown(f"""
                    <div class="history-card">
                        <strong>Attempt #{att.attempt_number}</strong> (Grade {att.letter_grade})<br>
                        <span style="font-size: 1.3rem; font-weight:700; color:#0284C7;">{att.total_score} / 100</span><br>
                        <small style="color:#475569;"><strong>{att.report_type}</strong></small><br>
                        <small style="color:#64748B;">{att.timestamp}</small><br>
                        <small>Act: {att.actionability_score}/25 | Scope: {att.clarity_of_scope_score}/25<br>Evid: {att.evidence_and_attribution_score}/25 | Meth: {att.methodology_score}/25</small>
                    </div>
                    """, unsafe_allow_html=True)

    col1, col2 = st.columns([1, 1])
    with col1:
        student_display_name = st.text_input(
            "Student Name (Optional)",
            value=st.session_state.user_email.split("@")[0].replace(".", " ").title(),
            help="Display name for the scorecard. Defaults to your email username."
        )
    with col2:
        report_title = st.text_input(
            "Report Title (Optional)",
            placeholder="e.g. Singapore Cyber Threat Landscape 2026",
            help="If left blank, will be extracted from your report content."
        )

    # 2. Report Type Selector to Calibrate Rubric (3 Types)
    report_type_options = [
        "1) 🕵️ Threat Actor Deep Dive Report (Actor TTPs, Campaigns & Infrastructure)",
        "2) 🌐 Country Threat Landscape (National / Regional Geopolitical Macro-Overview)",
        "3) 🛡️ CVE Strategic Reporting (Vulnerability Impact, Risk & Strategic Mitigations)"
    ]
    selected_type_raw = st.selectbox(
        "Select Report Type *",
        report_type_options,
        index=0,
        help="Calibrates the evaluation rubric to the report type. For example, a Country Threat Landscape is evaluated on executive strategy and does not require atomic IoCs or YARA rules."
    )
    
    if "Threat Actor" in selected_type_raw:
        report_type_clean = "Threat Actor Deep Dive Report"
    elif "Country" in selected_type_raw:
        report_type_clean = "Country Threat Landscape"
    else:
        report_type_clean = "CVE Strategic Reporting"

    st.info("📌 **Accepted Formats:** PDF (`.pdf`), Markdown (`.md`), or Plain Text (`.txt`). *(Word `.docx` is not accepted)*")
    
    input_tab1, input_tab2 = st.tabs(["📁 Upload File (.pdf, .md, .txt)", "✍️ Paste Report Text Directly"])
    
    report_content = ""
    file_name = None
    file_type = "direct_text"
    
    with input_tab1:
        uploaded_file = st.file_uploader(
            "Choose a Threat Intel Report file",
            type=["pdf", "md", "markdown", "txt"],
            help="Upload your completed CTI advisory."
        )
        if uploaded_file is not None:
            file_name = uploaded_file.name
            try:
                bytes_data = uploaded_file.read()
                report_content, file_type = extract_text_from_bytes(bytes_data, uploaded_file.name)
                st.success(f"✅ Successfully extracted and sanitized **{uploaded_file.name}** ({file_type.upper()}, {len(report_content):,} characters)")
            except DocumentParsingError as e:
                st.error(f"❌ File Parsing Error: {str(e)}")
            except Exception as e:
                st.error(f"❌ Unexpected Error: {str(e)}")

    with input_tab2:
        pasted_text = st.text_area(
            "Paste Markdown or Plain Text Report Content",
            height=280,
            placeholder="# Threat Intelligence Report\n\n## Executive Summary\n..."
        )
        if pasted_text.strip() and not uploaded_file:
            report_content = sanitize_report_text(pasted_text.strip())
            file_type = "pasted_text"
            file_name = "pasted_submission.md"

    if report_content:
        with st.expander("📄 Preview Extracted Content", expanded=False):
            st.text(report_content[:3000] + ("\n... [Truncated for preview]" if len(report_content) > 3000 else ""))
            st.caption(f"Total Characters: {len(report_content):,} | Words: ~{len(report_content.split()):,}")

    st.write("")
    btn_label = f"🚀 Score & Critique Attempt #{next_attempt_num}"
    grade_button = st.button(btn_label, type="primary", use_container_width=True)

    if grade_button:
        if not report_content.strip():
            st.error("⚠️ Please upload a valid report file or paste report text to evaluate.")
        else:
            is_valid, validation_msg = validate_report_content(report_content)
            if not is_valid:
                st.error(f"⚠️ Validation Error: {validation_msg}")
            else:
                with st.spinner("🔍 Senior CTI Analyst is evaluating the report against the calibrated criteria..."):
                    try:
                        grader = CTIGrader()
                        stage_result: MultiStageGradingResult = grader.grade_report(
                            student_name=student_display_name.strip(),
                            report_text=report_content,
                            selected_report_type=report_type_clean,
                            dual_review=True
                        )
                        result: GradingResult = stage_result.final_result
                        result.student_email = st.session_state.user_email
                        if stage_result.level_1_result:
                            stage_result.level_1_result.student_email = st.session_state.user_email
                        
                        attempt_num = storage.get_next_attempt_number(st.session_state.user_email)
                        sub_id = str(uuid.uuid4())[:8]
                        
                        record = SubmissionRecord(
                            submission_id=sub_id,
                            timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            student_name=student_display_name.strip(),
                            student_email=st.session_state.user_email,
                            attempt_number=attempt_num,
                            report_title=report_title.strip() if report_title.strip() else result.report_title,
                            report_type=result.report_type if result.report_type else report_type_clean,
                            filename=file_name,
                            file_type=file_type,
                            report_content=report_content,
                            total_score=result.total_score,
                            percentage_score=result.percentage_score,
                            letter_grade=result.letter_grade,
                            actionability_score=result.actionability.score,
                            clarity_of_scope_score=result.clarity_of_scope.score,
                            evidence_and_attribution_score=result.evidence_and_attribution.score,
                            methodology_score=result.methodology.score,
                            primary_model_used=stage_result.primary_model_used,
                            final_model_used=stage_result.final_model_used,
                            level_1_result=stage_result.level_1_result,
                            result=result
                        )
                        storage.save_submission(record)
                        
                        st.session_state.current_result = result
                        st.session_state.current_stage_result = stage_result
                        st.session_state.current_submission_id = sub_id
                        st.session_state.current_attempt = attempt_num
                        st.success(f"🎉 Evaluation Complete! Saved as **Attempt #{attempt_num}** (ID: `{sub_id}`)")
                    except Exception as e:
                        st.error(f"❌ Grading Failed: {str(e)}")

    # Display Grading Results Scorecard (No download buttons as requested)
    if st.session_state.current_result:
        res: GradingResult = st.session_state.current_result
        st.write("---")
        st.subheader(f"📊 Assessment Scorecard for {res.student_name} (Attempt #{st.session_state.current_attempt})")
        st.caption(f"Evaluated as: **{res.report_type}** | Topic: *{res.report_title}*")
        
        # Score Delta Comparison
        if len(past_attempts) > 0:
            last_att = past_attempts[-1]
            diff_total = res.total_score - last_att.total_score
            diff_str = f"+{diff_total}" if diff_total > 0 else f"{diff_total}"
            delta_cls = "delta-badge-pos" if diff_total >= 0 else "delta-badge-neg"
            st.markdown(f"📈 **Progression vs Attempt #{last_att.attempt_number}:** <span class='{delta_cls}'>{diff_str} points</span> ({last_att.total_score}/100 ➔ **{res.total_score}/100**)", unsafe_allow_html=True)
            st.write("")

        # Hero Scorecard
        col_score1, col_score2 = st.columns([1, 2])
        with col_score1:
            st.markdown(f"""
            <div class="score-card">
                <div style="font-size: 1.05rem; opacity: 0.8; margin-bottom: 0.3rem;">TOTAL GRADE SCORE</div>
                <div class="score-number">{res.total_score}<span style="font-size: 1.8rem; color: #94A3B8;">/100</span></div>
                <div class="grade-badge">Grade {res.letter_grade}</div>
            </div>
            """, unsafe_allow_html=True)
            
        with col_score2:
            st.markdown("#### 🎯 Senior Analyst Overall Critique")
            st.info(res.overall_critique)

        st.markdown("### 📋 4 Core Evaluation Criteria (0–25 Scale Each)")
        
        criteria_list = [
            ("1. Actionability (Can stakeholders/defenders take action?)", res.actionability),
            ("2. Clarity of Scope (Are targeted sectors, regions, or systems defined?)", res.clarity_of_scope),
            ("3. Evidence and Attribution (Are claims grounded in solid data/telemetry?)", res.evidence_and_attribution),
            ("4. Methodology (Does the report explain how data was gathered and analyzed?)", res.methodology),
        ]
        
        for title, item in criteria_list:
            with st.container():
                st.markdown(f"""
                <div class="rubric-box">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span class="metric-title">{title}</span>
                        <span style="font-size: 1.3rem; font-weight: 700; color: #0284C7;">{item.score} / 25</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                st.progress(item.score / 25.0)
                st.markdown(f"**Explanation:** {item.explanation}")
                st.write("")

        # Gaps & Logical Fallacies Section
        st.markdown("### ⚠️ Gaps, Logical Fallacies & Missing Context")
        if res.gaps_and_logical_fallacies:
            for gap in res.gaps_and_logical_fallacies:
                st.warning(f"• {gap}")
        else:
            st.success("✅ No major gaps or logical fallacies detected in this report.")

        # Three Questions for the Author
        st.markdown("### ❓ Three Questions to Ask the Report's Author")
        for i, q in enumerate(res.questions_for_author, 1):
            st.markdown(f"""
            <div class="author-question-box">
                <strong>Question {i}:</strong> {q}
            </div>
            """, unsafe_allow_html=True)


# ==============================================================================
# TAB 2: INSTRUCTOR GRADEBOOK (Strictly Restricted to Authorized Instructors)
# ==============================================================================
elif app_mode == "📊 Instructor Gradebook" and is_instructor:
    st.markdown('<div class="main-title">📊 Instructor Gradebook & Submissions Archive</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">Restricted to authorized instructors. Inspect uploaded report contents and multi-level model evaluations.</div>', unsafe_allow_html=True)
    
    df = storage.get_submissions_dataframe()
    all_submissions = storage.get_all_submissions()
    
    if df.empty:
        st.info("No submissions recorded in Firestore yet.")
    else:
        unique_students = len(set(df['Email']))
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Submissions", len(df))
        m2.metric("Unique Students", unique_students)
        m3.metric("Class Average", f"{df['Total Score (100)'].mean():.1f} / 100")
        m4.metric("Highest Score", f"{df['Total Score (100)'].max()} / 100")
        
        st.write("---")
        st.subheader("📋 Submissions Log (All Attempts)")
        st.dataframe(df, use_container_width=True)
        
        st.write("---")
        st.subheader("🔍 Inspect Student Submission & Uploaded Report")
        submission_options = {
            f"{s.student_name} ({s.student_email}) | Attempt #{s.attempt_number} [{s.report_type}] - {s.total_score}/100 ({s.letter_grade}) - {s.timestamp}": s 
            for s in all_submissions
        }
        chosen_key = st.selectbox("Select a submission record to inspect:", list(submission_options.keys()))
        
        if chosen_key:
            selected_sub = submission_options[chosen_key]
            st.markdown(f"### Submission: **{selected_sub.student_name}** (`{selected_sub.student_email}`) — Attempt #{selected_sub.attempt_number}")
            st.write(f"**Report Title:** {selected_sub.report_title} | **Type:** `{selected_sub.report_type}` | **File:** `{selected_sub.filename or 'Direct Paste'}` | **Submitted At:** {selected_sub.timestamp}")
            st.write(f"**Score:** {selected_sub.total_score}/100 (Grade {selected_sub.letter_grade})")

            insp_tab1, insp_tab2, insp_tab3 = st.tabs([
                "📄 Uploaded Report Content",
                "🏆 Final Evaluation Scorecard",
                "📝 Level 1 Preliminary Review"
            ])

            with insp_tab1:
                st.markdown("**Original Uploaded / Submitted Text:**")
                st.markdown(f'<div class="report-preview-box">{selected_sub.report_content}</div>', unsafe_allow_html=True)

            with insp_tab2:
                st.info(selected_sub.result.overall_critique)
                st.write(f"- **Actionability ({selected_sub.actionability_score}/25):** {selected_sub.result.actionability.explanation}")
                st.write(f"- **Clarity of Scope ({selected_sub.clarity_of_scope_score}/25):** {selected_sub.result.clarity_of_scope.explanation}")
                st.write(f"- **Evidence & Attribution ({selected_sub.evidence_and_attribution_score}/25):** {selected_sub.result.evidence_and_attribution.explanation}")
                st.write(f"- **Methodology ({selected_sub.methodology_score}/25):** {selected_sub.result.methodology.explanation}")
                
                if selected_sub.result.gaps_and_logical_fallacies:
                    st.markdown("**Identified Gaps & Fallacies:**")
                    for g in selected_sub.result.gaps_and_logical_fallacies:
                        st.write(f"- {g}")
                            
                if selected_sub.result.questions_for_author:
                    st.markdown("**3 Questions for Author:**")
                    for idx, q in enumerate(selected_sub.result.questions_for_author, 1):
                        st.write(f"{idx}. {q}")

            with insp_tab3:
                if selected_sub.level_1_result:
                    st.info(selected_sub.level_1_result.overall_critique)
                    st.write(f"- **Actionability ({selected_sub.level_1_result.actionability.score}/25):** {selected_sub.level_1_result.actionability.explanation}")
                    st.write(f"- **Clarity of Scope ({selected_sub.level_1_result.clarity_of_scope.score}/25):** {selected_sub.level_1_result.clarity_of_scope.explanation}")
                    st.write(f"- **Evidence & Attribution ({selected_sub.level_1_result.evidence_and_attribution.score}/25):** {selected_sub.level_1_result.evidence_and_attribution.explanation}")
                    st.write(f"- **Methodology ({selected_sub.level_1_result.methodology.score}/25):** {selected_sub.level_1_result.methodology.explanation}")
                else:
                    st.caption("No separate Level 1 preliminary evaluation recorded for this entry.")


# ==============================================================================
# TAB 3: RUBRIC REFERENCE
# ==============================================================================
elif app_mode == "📖 Rubric Reference":
    st.markdown('<div class="main-title">📖 Senior CTI Analyst Grading Rubric (0–25 Scale, 100 Max)</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">Evaluation criteria dynamically calibrated by report category.</div>', unsafe_allow_html=True)
    
    st.markdown("""
    ### 🕵️ 1. Threat Actor Deep Dive Report
    *Comprehensive profiling of a specific threat actor, APT cluster, or cybercrime syndicate.*
    - **Clarity of Scope (0–25):** 
      - *Identity & Alias Hygiene:* Primary designation stated, vendor aliases mapped, naming conflicts acknowledged, cluster boundaries defined. *(Undifferentiated alias soup = max 5/25)*.
      - *Victimology & Targeting Logic:* Granular sectors, geographies, organization profile, time-bounded, and reasoning for what drives target selection. *(Sector list with no reasoning = max 7/25)*.
    - **Evidence & Attribution (0–25):** 
      - *Attribution Basis:* Visible evidence chain (technical, infrastructure, temporal, linguistic). Stated confidence must be justified. *(State-sponsorship asserted without evidence chain = hard cap at 8/25)*.
      - *Infrastructure & Tooling:* Malware families, loaders, C2 patterns, hosting/registration habits, distinguishing bespoke from commodity tooling.
    - **Methodology (0–25):** 
      - *TTP Depth & ATT&CK Mapping:* Technique-level with sub-techniques tied to specific observed campaigns; full lifecycle from initial access to impact. *(Tactic names only = max 5/25)*.
      - *Analytic Tradecraft:* Diamond Model / Kill Chain analysis, intelligence sourcing, BLUF, and non-repetitive structure.
    - **Actionability (0–25):** 
      - *Detection & Hunting Value:* Behavioral detection opportunities and named log sources/telemetry (Sysmon, Zeek, Windows Event IDs). *(IOC list / hash dump alone = max 5/25)*.
      - *Forecast & Defensive Posture:* Where the actor is heading and proactive hardening guidance.

    ---

    ### 🌐 2. Country Threat Landscape
    *Macro overview of the cyber threat environment facing a nation or region (e.g. Singapore Cyber Threat Landscape).*
    - **Clarity of Scope (0–25):** 
      - *Scope & Framing:* Country, time window, sectors in/out of scope, clearly separates "threats to" vs "threats from".
      - *Geopolitical & Regulatory Context:* Why this country, why now; relevant regulation or policy shaping the threat or response. *(Generic geopolitical commentary = max 5/25)*.
    - **Evidence & Attribution (0–25):** 
      - *Sector Targeting Evidence:* Grounded in actual in-country incidents or telemetry, not inferred from the country's economic profile/GDP.
      - *Actor Coverage Balance:* State-nexus, cybercrime, and hacktivism proportionate to in-country reality, not imported from global reputation.
    - **Methodology (0–25):** 
      - *Analytic Rigour:* ICD 203 estimative probability language, confidence tied to sourcing, alternative explanations considered, zero nation-state hype.
      - *Data & Trend Validity:* Baseline/prior-period comparisons, stated denominators, local vs global dataset distinction.
    - **Actionability (0–25):** 
      - *So-What & Recommendations:* Actionable for defenders operating specifically in that national jurisdiction.
      - *(Note: Atomic IoCs and low-level YARA/Sigma rules are **NOT** expected or required).*

    ---

    ### 🛡️ 3. CVE Strategic Reporting
    *Strategic and technical assessment of a critical vulnerability or emerging exploitation trend.*
    - **Actionability (0–25):** 
      - *Decision Framing:* Opens with the concrete decision being asked for (Emergency patch / Scheduled patch / Accept risk / Monitor). *(Opening with technical details instead of the decision = max 5/25)*.
      - *Remediation Path & Tradeoffs:* Realistic patch timeline, downtime/compatibility costs, interim compensating controls, named owner. *("Apply vendor patch" alone without tradeoffs = max 5/25)*.
    - **Clarity of Scope (0–25):** 
      - *Exposure Assessment:* Do we run it, where, how many instances, internet-facing? *(Silence on exposure = max 5/25; honest "exposure unknown, here is how we find out" scores higher)*.
      - *Business Impact Articulated:* Operational and financial consequences translated for executives. *(Raw CIA-triad jargon without translation = max 5/25)*.
    - **Evidence & Attribution (0–25):** 
      - *Prioritisation Rationale:* Why this CVE ahead of everything else (exploitation likelihood, CISA KEV status, EPSS score, asset criticality). *(CVSS severity score as sole argument = max 5/25)*.
      - *Exploitation Status Precision:* Clearly separates Exploitable vs Public PoC vs Active In-The-Wild Exploitation with dated and sourced claims.
    - **Methodology (0–25):** 
      - *Technical Depth Calibration:* Calibrated for decision-makers (enough to be credible, no excess). *(Penalize raw technical exploit dump wearing a strategic label)*.
      - *Analytic Synthesis:* Structured risk rationale, clear executive summary, coherent trade-off analysis.

    ---
    ### Grade Scale
    - **90 – 100:** Grade A (Outstanding / Production Ready)
    - **80 – 89:** Grade B (Solid professional report)
    - **70 – 79:** Grade C (Acceptable, noticeable tradecraft gaps)
    - **60 – 69:** Grade D (Substandard / hits multiple hard caps)
    - **Below 60:** Grade F (Failed / Inadequate)
    """)
