import os
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
INSTRUCTOR_EMAILS = [e.strip().lower() for e in RAW_INSTRUCTOR_EMAILS.split(",") if e.strip()]

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
    
    st.divider()
    
    # Model Configuration
    st.subheader("Judge Models Configuration")
    env_key = os.getenv("GEMINI_API_KEY", "")
    api_key_input = st.text_input(
        "Gemini API Key",
        value=env_key,
        type="password",
        help="Defaults to GEMINI_API_KEY from Secret Manager or environment."
    )
    
    col_m1, col_m2 = st.columns(2)
    with col_m1:
        primary_model = st.text_input(
            "Level 1 Model",
            value=os.getenv("PRIMARY_MODEL", "gemini-3.5-flash-lite"),
            help="First level preliminary critique model."
        )
    with col_m2:
        final_model = st.text_input(
            "Final Evaluator",
            value=os.getenv("META_MODEL", "gemini-3.7-flash"),
            help="Final arbitration and synthesis model."
        )
        
    enable_dual = st.checkbox(
        "Enable 2-Level Evaluation",
        value=True,
        help="Level 1 (gemini-3.5-flash-lite) generates initial review -> Level 2 (gemini-3.7-flash) cross-examines and finalizes the score."
    )
    
    st.divider()
    st.caption("🛡️ Protected with XML Tag Sanitization & Structural Guardrails.")


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
            placeholder="e.g. Threat Advisory: Ransomware Campaign Targeting FinTech",
            help="If left blank, will be extracted from your report content."
        )

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
    btn_label = f"🚀 Score & Critique Attempt #{next_attempt_num} (Level 1: {primary_model} ➔ Final: {final_model})" if enable_dual else f"🚀 Score & Critique Attempt #{next_attempt_num}"
    grade_button = st.button(btn_label, type="primary", use_container_width=True)

    if grade_button:
        if not report_content.strip():
            st.error("⚠️ Please upload a valid report file or paste report text to evaluate.")
        elif not api_key_input:
            st.error("⚠️ Gemini API Key is required. Please provide it in the sidebar or Secret Manager.")
        else:
            is_valid, validation_msg = validate_report_content(report_content)
            if not is_valid:
                st.error(f"⚠️ Validation Error: {validation_msg}")
            else:
                spinner_msg = f"🔍 Running 2-Level Review (Level 1: {primary_model} ➔ Final: {final_model})..." if enable_dual else "🔍 Senior CTI Analyst is evaluating the report..."
                with st.spinner(spinner_msg):
                    try:
                        grader = CTIGrader(
                            api_key=api_key_input,
                            primary_model=primary_model.strip(),
                            final_model=final_model.strip()
                        )
                        stage_result: MultiStageGradingResult = grader.grade_report(
                            student_name=student_display_name.strip(),
                            report_text=report_content,
                            dual_review=enable_dual
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
                        st.success(f"🎉 Complete! Saved report content & evaluation as **Attempt #{attempt_num}** (ID: `{sub_id}`)")
                    except Exception as e:
                        st.error(f"❌ Grading Failed: {str(e)}")

    # Display Grading Results Scorecard
    if st.session_state.current_result:
        res: GradingResult = st.session_state.current_result
        st.write("---")
        st.subheader(f"📊 Assessment Scorecard for {res.student_name} (Attempt #{st.session_state.current_attempt})")
        
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
            st.markdown("#### 🎯 Final Senior Analyst Critique")
            st.info(res.overall_critique)

        st.markdown("### 📋 4 Core Evaluation Criteria (0–25 Scale Each)")
        
        criteria_list = [
            ("1. Actionability (Can security teams take direct defensive action?)", res.actionability),
            ("2. Clarity of Scope (Are targeted sectors, regions, or systems clearly defined?)", res.clarity_of_scope),
            ("3. Evidence and Attribution (Are claims backed by technical data/IoCs, or pure speculation?)", res.evidence_and_attribution),
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

        # Export Section
        st.write("---")
        st.subheader("📥 Export Evaluation Report")
        col_dl1, col_dl2 = st.columns(2)
        
        md_export = f"""# CTI Report Critique & Scorecard
**Student:** {res.student_name} ({st.session_state.user_email})  
**Attempt:** #{st.session_state.current_attempt}  
**Report Title:** {res.report_title}  
**Total Score:** {res.total_score}/100 (Grade {res.letter_grade})

## Senior Analyst Overall Critique
{res.overall_critique}

## Category Breakdown (0-25 Scale)
- **Actionability:** {res.actionability.score}/25  
  {res.actionability.explanation}
- **Clarity of Scope:** {res.clarity_of_scope.score}/25  
  {res.clarity_of_scope.explanation}
- **Evidence & Attribution:** {res.evidence_and_attribution.score}/25  
  {res.evidence_and_attribution.explanation}
- **Methodology:** {res.methodology.score}/25  
  {res.methodology.explanation}

## Gaps, Logical Fallacies & Missing Context
""" + "\n".join([f"- {g}" for g in res.gaps_and_logical_fallacies]) + """

## Three Questions for the Author
""" + "\n".join([f"{idx}. {q}" for idx, q in enumerate(res.questions_for_author, 1)])
        
        with col_dl1:
            st.download_button(
                "📥 Download Markdown Report (.md)",
                data=md_export,
                file_name=f"critique_{st.session_state.user_email.split('@')[0]}_attempt{st.session_state.current_attempt}.md",
                mime="text/markdown"
            )
        with col_dl2:
            st.download_button(
                "📥 Download JSON Data (.json)",
                data=res.model_dump_json(indent=2),
                file_name=f"critique_{st.session_state.user_email.split('@')[0]}_attempt{st.session_state.current_attempt}.json",
                mime="application/json"
            )


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
        
        csv_data = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            "📥 Export Complete Gradebook (CSV)",
            data=csv_data,
            file_name=f"cti_gradebook_{datetime.date.today()}.csv",
            mime="text/csv",
            type="primary"
        )
        
        st.write("---")
        st.subheader("🔍 Inspect Student Submission & Uploaded Report")
        submission_options = {
            f"{s.student_name} ({s.student_email}) | Attempt #{s.attempt_number} - {s.total_score}/100 ({s.letter_grade}) - {s.timestamp}": s 
            for s in all_submissions
        }
        chosen_key = st.selectbox("Select a submission record to inspect:", list(submission_options.keys()))
        
        if chosen_key:
            selected_sub = submission_options[chosen_key]
            st.markdown(f"### Submission: **{selected_sub.student_name}** (`{selected_sub.student_email}`) — Attempt #{selected_sub.attempt_number}")
            st.write(f"**Report Title:** {selected_sub.report_title} | **File:** `{selected_sub.filename or 'Direct Paste'}` | **Submitted At:** {selected_sub.timestamp}")
            st.write(f"**Score:** {selected_sub.total_score}/100 (Grade {selected_sub.letter_grade})")

            insp_tab1, insp_tab2, insp_tab3 = st.tabs([
                "📄 Uploaded Report Content",
                f"🏆 Final Evaluation ({selected_sub.final_model_used})",
                f"📝 Level 1 Evaluation ({selected_sub.primary_model_used})"
            ])

            with insp_tab1:
                st.markdown("**Original Uploaded / Submitted Text:**")
                st.markdown(f'<div class="report-preview-box">{selected_sub.report_content}</div>', unsafe_allow_html=True)
                st.download_button(
                    "📥 Download Student's Original Report",
                    data=selected_sub.report_content,
                    file_name=f"report_{selected_sub.student_email.split('@')[0]}_attempt{selected_sub.attempt_number}.txt",
                    mime="text/plain"
                )

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
    st.markdown('<div class="sub-title">Standardized 4-pillar evaluation criteria used by the Gemini Assessor (0–25 points each).</div>', unsafe_allow_html=True)
    
    st.markdown("""
    ### 1. Actionability (0 to 25 Points)
    *Can security teams take direct defensive action based on this?*
    - **17 - 25 (Outstanding):** Direct, immediate defensive actions: detection engineering rules (Sigma/YARA/Snort), explicit firewall blocklists, patching priority matrix ready for SOC execution.
    - **8 - 16 (Acceptable):** General recommendations provided, but lacks concrete configuration parameters or rule syntax.
    - **0 - 7 (Poor):** Zero actionable guidance; vague slogans like "stay vigilant" or "keep software updated".

    ### 2. Clarity of Scope (0 to 25 Points)
    *Are the targeted sectors, regions, or systems clearly defined?*
    - **17 - 25 (Outstanding):** Granular victimology (industry vertical, geo-region, specific software versions, affected network protocols).
    - **8 - 16 (Acceptable):** Broad sector named (e.g. "Healthcare") without technical versions or attack surface details.
    - **0 - 7 (Poor):** Unbounded claims ("everyone on the internet is vulnerable").

    ### 3. Evidence and Attribution (0 to 25 Points)
    *Are claims backed by solid technical data, logs, or IoCs, or is it pure speculation?*
    - **17 - 25 (Outstanding):** Verified SHA256 hashes, C2 telemetry, CVE IDs, MITRE ATT&CK technique IDs, and explicit confidence level ratings.
    - **8 - 16 (Acceptable):** Adversary named with some IoCs, but missing verification sources or confidence calibration.
    - **0 - 7 (Poor):** Speculation and conspiracy with zero technical indicators or logs.

    ### 4. Methodology (0 to 25 Points)
    *Does the report explain how the data was gathered and analyzed?*
    - **17 - 25 (Outstanding):** Transparent analytic workflow (e.g. honeypot logs, dark web monitoring, reverse engineering sandbox analysis).
    - **8 - 16 (Acceptable):** High-level data source mentioned without methodology explanation.
    - **0 - 7 (Poor):** No explanation of where the intelligence originated.

    ---
    ### Total Score & Grade Scale
    - **90 – 100:** Grade A (Production-ready CTI advisory)
    - **80 – 89:** Grade B (Solid professional report with minor gaps)
    - **70 – 79:** Grade C (Acceptable student submission, missing key technical details)
    - **60 – 69:** Grade D (Substandard)
    - **Below 60:** Grade F (Inadequate or failed submission)
    """)
