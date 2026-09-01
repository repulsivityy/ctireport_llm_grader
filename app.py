import os
import re
import html
import uuid
import datetime
import streamlit as st
import pandas as pd
from dotenv import load_dotenv

from schemas import GradingResult, MultiStageGradingResult, SubmissionRecord
from parser import extract_text_from_bytes, validate_report_content, sanitize_report_text, DocumentParsingError
from grader import CTIGrader, EvaluationUnavailable
import storage

load_dotenv()

st.set_page_config(
    page_title="CTI Report Grader",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Instructor PIN for Gradebook access (defaults to cti-instructor-2026 if not set in .env)
INSTRUCTOR_PIN = os.getenv("INSTRUCTOR_PIN", "cti-instructor-2026").strip()

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
    .hero-banner {
        background: linear-gradient(135deg, #0F172A 0%, #1E293B 100%);
        color: #FFFFFF;
        padding: 2.5rem 2rem;
        border-radius: 14px;
        margin-bottom: 2rem;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
    }
    .hero-title {
        font-size: 2.5rem;
        font-weight: 800;
        color: #38BDF8;
        margin-bottom: 0.5rem;
    }
    .hero-sub {
        font-size: 1.15rem;
        color: #CBD5E1;
        max-width: 800px;
        line-height: 1.6;
        margin-bottom: 1.5rem;
    }
    .feature-card {
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 1.2rem;
        height: 100%;
    }
    .feature-title {
        font-size: 1.1rem;
        font-weight: 700;
        color: #0F172A;
        margin-bottom: 0.5rem;
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
    if "instructor_authenticated" not in st.session_state:
        st.session_state.instructor_authenticated = False


init_session_state()

is_logged_in = bool(st.session_state.user_email)
is_instructor = st.session_state.get("instructor_authenticated", False)

# Sidebar Navigation & Authentication Control
with st.sidebar:
    st.image("https://img.icons8.com/color/96/cyber-security.png", width=64)
    st.title("CTI Grader Control")
    
    st.subheader("👤 User Session")
    if is_logged_in:
        st.caption("Active Email / User")
        st.code(st.session_state.user_email, language=None)
        if is_instructor:
            st.success("👨‍🏫 **Instructor Mode Active**")
            if st.button("🔒 Exit Instructor Mode", use_container_width=True):
                st.session_state.instructor_authenticated = False
                st.rerun()
        else:
            st.info("🎓 **Student / Analyst Mode**")
            
        if st.button("🚪 Switch User / Sign Out", use_container_width=True):
            st.session_state.user_email = ""
            st.session_state.current_result = None
            st.session_state.current_stage_result = None
            st.session_state.current_submission_id = None
            st.session_state.current_attempt = 1
            st.session_state.instructor_authenticated = False
            st.rerun()
    else:
        st.caption("Enter your email to begin:")
        sidebar_email = st.text_input("Your Email", placeholder="analyst@domain.com", key="sidebar_email_input")
        if st.button("Continue", type="primary", use_container_width=True):
            if sidebar_email.strip() and "@" in sidebar_email:
                st.session_state.user_email = sidebar_email.strip().lower()
                st.rerun()
            else:
                st.error("Please enter a valid email address.")

    st.divider()

    # Dynamic Navigation Tabs
    if is_logged_in:
        nav_options = ["📝 Submit & Grade Report", "📊 Instructor Gradebook", "📖 Evaluation Overview"]
        app_mode = st.radio("Navigation", nav_options, index=0)
    else:
        nav_options = ["🏠 Welcome & Sign In", "📖 Evaluation Overview"]
        app_mode = st.radio("Navigation", nav_options, index=0)


# ==============================================================================
# TAB 0: PUBLIC LANDING PAGE (When Logged Out)
# ==============================================================================
if not is_logged_in and app_mode == "🏠 Welcome & Sign In":
    st.markdown("""
    <div class="hero-banner">
        <div class="hero-title">🛡️ Cyber Threat Intelligence Report Grader</div>
        <div class="hero-sub">
            A workshop tool that helps you build executive Threat Intelligence reports in a more structured way — it checks how your report is put together, not whether its facts are right.
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("### 📋 Core Evaluation Dimensions")
    st.markdown("Reports are assessed on whether they perform four core functions — in whatever structure you choose:")
    
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("""
        <div class="feature-card">
            <div class="feature-title">Framing, Scope & Coherence</div>
            <p>Does the report frame the problem, define its scope, lead with the judgement, and hang together as one connected argument?</p>
        </div>
        """, unsafe_allow_html=True)
        st.write("")
        st.markdown("""
        <div class="feature-card">
            <div class="feature-title">Source Attribution & Evidence</div>
            <p>Are the report's material claims linked to a source the reader can go to? We check that a reference is attached — not whether the source is accurate.</p>
        </div>
        """, unsafe_allow_html=True)

    with c2:
        st.markdown("""
        <div class="feature-card">
            <div class="feature-title">Analytic Reasoning & Uncertainty</div>
            <p>Is the path from evidence to judgement visible, and is uncertainty expressed in a calibrated, consistent scheme with assumptions and gaps surfaced?</p>
        </div>
        """, unsafe_allow_html=True)
        st.write("")
        st.markdown("""
        <div class="feature-card">
            <div class="feature-title">Executive Value & Actionability</div>
            <p>Does the report give leadership something to decide or do, framed in business terms, with prioritised and concrete recommendations?</p>
        </div>
        """, unsafe_allow_html=True)

    st.write("---")
    
    col_login_box, col_info = st.columns([1, 1])
    with col_login_box:
        st.markdown("### 🚀 Ready to Submit Your Report?")
        st.info("Enter your email address to access the submission portal, track revisions, and receive feedback.")
        landing_email = st.text_input("Your Email Address", placeholder="analyst@domain.com", key="landing_email_input")
        if st.button("🚀 Enter Submission Portal", type="primary", use_container_width=True):
            if landing_email.strip() and "@" in landing_email:
                st.session_state.user_email = landing_email.strip().lower()
                st.rerun()
            else:
                st.error("Please enter a valid email address.")
                
    with col_info:
        st.markdown("### 💡 How It Works")
        st.write("Submit your executive threat report in Markdown or PDF format.")
        st.write("The platform evaluates your submission across these core dimensions and provides diagnostic feedback to help guide subsequent revisions.")


# ==============================================================================
# TAB 1: SUBMIT & GRADE REPORT (Logged In Students + Instructors)
# ==============================================================================
elif is_logged_in and app_mode == "📝 Submit & Grade Report":
    st.markdown('<div class="main-title">🛡️ Cyber Threat Intelligence Report Grader</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">Submit your CTI report to be evaluated on a 100-point scale (4 criteria × 25 pts each). Revisions are tracked automatically by your email.</div>', unsafe_allow_html=True)

    if not st.session_state.user_email:
        st.warning("👈 Please enter your email in the sidebar to access the submission portal.")
        st.stop()

    if st.session_state.get("_flash"):
        st.success(st.session_state.pop("_flash"))

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
                        <strong>Attempt #{att.attempt_number}</strong><br>
                        <span style="font-size: 1.3rem; font-weight:700; color:#0284C7;">{att.total_score} / 100</span><br>
                        <small style="color:#475569;"><strong>{html.escape(att.report_type)}</strong></small><br>
                        <small style="color:#64748B;">{html.escape(att.timestamp)}</small><br>
                        <small>Framing: {att.clarity_of_scope_score}/25 | Sourcing: {att.evidence_and_attribution_score}/25<br>Reasoning: {att.methodology_score}/25 | Exec/Action: {att.actionability_score}/25</small>
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

    st.info(
        "📌 **All submissions are graded as an executive CTI report** (audience: executives / "
        "upper management). The subject is up to you — threat landscape, vulnerability assessment, "
        "threat actor profile, incident retrospective — and so is the structure. There is no "
        "required format: the grader checks whether your report performs a set of functions, in "
        "whatever sections and order you choose. See **📖 Evaluation Overview** for how reports "
        "are assessed."
    )
    st.info("📌 **Accepted Formats:** PDF (`.pdf`), Markdown (`.md`), or Plain Text (`.txt`). *(Word `.docx` is not accepted)*")
    
    input_mode = st.radio(
        "Choose Submission Method:",
        ["✍️ Paste Report Text", "📁 Upload Document (.pdf, .md, .txt)"],
        horizontal=True,
    )
    
    col_lang1, col_lang2 = st.columns(2)
    with col_lang1:
        report_language = st.selectbox(
            "Report Language",
            ["English", "Spanish", "French", "German", "Chinese", "Japanese", "Korean", "Other"],
            help="The language your report is written in."
        )
    with col_lang2:
        feedback_language = st.selectbox(
            "Feedback Language",
            ["English", "Match Report Language"],
            help="The language you want the grader's feedback to be in."
        )
    
    report_content = ""
    file_name = None
    file_type = "direct_text"
    
    if input_mode == "📁 Upload Document (.pdf, .md, .txt)":
        uploaded_file = st.file_uploader(
            "Choose a Threat Intel Report file",
            type=["pdf", "md", "markdown", "txt"],
            help="Upload your completed CTI advisory.",
            key="report_file_uploader",
        )
        if uploaded_file is not None:
            file_name = uploaded_file.name
            try:
                bytes_data = uploaded_file.getvalue()
                report_content, file_type = extract_text_from_bytes(bytes_data, uploaded_file.name)
                st.success(f"✅ Extracted & sanitized **{uploaded_file.name}** ({file_type.upper()}, {len(report_content):,} characters)")
            except DocumentParsingError as e:
                st.error(f"❌ File Parsing Error: {str(e)}")
            except Exception as e:
                st.error(f"❌ Unexpected Error: {str(e)}")
    else:
        pasted_text = st.text_area(
            "Paste Markdown or Plain Text Report Content",
            height=280,
            placeholder="# Threat Intelligence Report\n\n## Executive Summary\n...",
            key="report_pasted_text",
        )
        if pasted_text.strip():
            report_content = sanitize_report_text(pasted_text.strip())
            file_type = "pasted_text"
            file_name = "pasted_submission.md"

    if report_content:
        with st.expander("📄 Preview Extracted Content", expanded=False):
            st.text(report_content[:3000] + ("\n... [Truncated for preview]" if len(report_content) > 3000 else ""))
            st.caption(f"Total Characters: {len(report_content):,} | Words: ~{len(report_content.split()):,}")

    st.write("")

    # One submission per report version: the same text cannot be graded twice in a row.
    # Editing the report (upload or paste) unlocks the button again.
    _last = past_attempts[-1] if past_attempts else None
    already_submitted = bool(_last and report_content.strip() and _last.report_content.strip() == report_content.strip())
    grading_running = st.session_state.get("grading_in_progress", False)

    btn_label = f"🚀 Score & Critique Attempt #{next_attempt_num}"
    grade_button = st.button(
        btn_label,
        type="primary",
        use_container_width=True,
        disabled=already_submitted or grading_running,
    )
    if already_submitted:
        st.caption(f"✅ This exact report was already graded as Attempt #{_last.attempt_number}. Revise it above to submit a new version.")

    if grade_button and not already_submitted and not grading_running:
        if not report_content.strip():
            st.error("⚠️ Please upload a valid report file or paste report text to evaluate.")
        else:
            is_valid, validation_msg = validate_report_content(report_content)
            if not is_valid:
                st.error(f"⚠️ Validation Error: {validation_msg}")
            else:
                st.session_state.grading_in_progress = True
                try:
                    with st.spinner("🔍 Senior CTI Analyst is evaluating the report against the rubric..."):
                        grader = CTIGrader()
                        stage_result: MultiStageGradingResult = grader.grade_report(
                            student_name=student_display_name.strip(),
                            report_text=report_content,
                            previous_attempt=_last,
                            dual_review=True,
                            report_language=report_language,
                            feedback_language=feedback_language,
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
                            report_type=result.report_type if result.report_type else "General CTI Briefing",
                            filename=file_name,
                            file_type=file_type,
                            report_content=report_content,
                            total_score=result.total_score,
                            percentage_score=result.percentage_score,
                            actionability_score=result.actionability.score,
                            clarity_of_scope_score=result.clarity_of_scope.score,
                            evidence_and_attribution_score=result.evidence_and_attribution.score,
                            methodology_score=result.methodology.score,
                            primary_model_used=stage_result.primary_model_used,
                            final_model_used=stage_result.final_model_used,
                            level_1_result=stage_result.level_1_result,
                            result=result,
                            integrity=stage_result.integrity,
                        )
                        storage.save_submission(record)

                        st.session_state.current_result = result
                        st.session_state.current_stage_result = stage_result
                        st.session_state.current_submission_id = sub_id
                        st.session_state.current_attempt = attempt_num
                        st.session_state._flash = f"🎉 Evaluation complete — saved as Attempt #{attempt_num} (ID: {sub_id})."
                    st.rerun()
                except EvaluationUnavailable as e:
                    st.error(f"⏳ {e}")
                except Exception as e:
                    st.error(f"❌ Grading failed: {e}")
                finally:
                    st.session_state.grading_in_progress = False

    # Display Grading Results Scorecard (No download buttons as requested)
    if st.session_state.current_result:
        res: GradingResult = st.session_state.current_result
        st.write("---")
        
        # Header with Attempt & Classification Meta
        st.markdown(f"""
        <div style="display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; margin-bottom: 0.5rem;">
            <div class="main-title" style="font-size: 1.8rem;">📊 Assessment Scorecard: {html.escape(res.student_name)}</div>
            <div style="background: #E2E8F0; padding: 4px 12px; border-radius: 9999px; font-weight: 600; color: #1E293B; font-size: 0.9rem;">
                Attempt #{st.session_state.current_attempt}
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.caption(f"Detected Subject: **{res.report_type}** | Subject Scope: *{res.report_title}*")

        # Attempt Progress Callout (if revising)
        prior_atts = [a for a in past_attempts if a.attempt_number != st.session_state.current_attempt]
        if prior_atts:
            prev = prior_atts[-1]
            diff_total = res.total_score - prev.total_score
            diff_str = f"+{diff_total}" if diff_total > 0 else str(diff_total)
            delta_cls = "delta-badge-pos" if diff_total >= 0 else "delta-badge-neg"
            arrow = "▲" if diff_total >= 0 else "▼"
            
            with st.container():
                st.markdown(f"""
                <div style="background: #F8FAFC; border: 1px solid #CBD5E1; border-left: 4px solid {'#16A34A' if diff_total >= 0 else '#DC2626'}; border-radius: 8px; padding: 0.8rem 1.2rem; margin-bottom: 1.2rem;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-weight: 600; color: #1E293B;">Progression vs Attempt #{prev.attempt_number}:</span>
                        <span class="{delta_cls}" style="font-size: 1.1rem;">{arrow} {diff_str} pts ({prev.total_score}/100 ➔ <strong>{res.total_score}/100</strong>)</span>
                    </div>
                    {f'<div style="color: #475569; font-size: 0.95rem; margin-top: 0.4rem;"><strong>What evolved:</strong> {html.escape(res.progress_note)}</div>' if res.progress_note else ''}
                </div>
                """, unsafe_allow_html=True)

        # Hero Scorecard Block
        score_band = "🟢 Executive Ready" if res.total_score >= 85 else ("🟡 Substantive (Revisions Suggested)" if res.total_score >= 70 else "🔴 Substantial Gaps Detected")
        col_score1, col_score2 = st.columns([1, 2])
        with col_score1:
            st.markdown(f"""
            <div class="score-card" style="padding: 1.2rem;">
                <div style="font-size: 0.9rem; opacity: 0.8; letter-spacing: 0.05em;">COMPOSITE SCORE</div>
                <div class="score-number">{res.total_score}<span style="font-size: 1.6rem; color: #94A3B8;">/100</span></div>
                <div style="margin-top: 0.5rem; font-size: 0.85rem; background: rgba(255,255,255,0.1); padding: 3px 8px; border-radius: 6px;">
                    {score_band}
                </div>
            </div>
            """, unsafe_allow_html=True)

        with col_score2:
            st.markdown("#### 🎯 Senior Analyst Overall Critique")
            st.info(res.overall_critique)

        if res.integrity_notice:
            st.error(f"🛡️ **Evaluator-integrity note (learning point, not a separate penalty):** {res.integrity_notice}")

        # 4 Core Pillars in a 2x2 Modern Grid
        st.markdown("### 📋 The 4 Evaluation Pillars (0–25 Pts Each)")

        criteria_list = [
            ("1. Framing, Scope & Coherence", res.clarity_of_scope),
            ("2. Source Attribution & Evidence", res.evidence_and_attribution),
            ("3. Analytic Reasoning & Uncertainty", res.methodology),
            ("4. Executive Value & Actionability", res.actionability),
        ]

        p_col1, p_col2 = st.columns(2)
        for idx, (title, item) in enumerate(criteria_list):
            target_col = p_col1 if idx % 2 == 0 else p_col2
            with target_col:
                with st.container():
                    st.markdown(f"""
                    <div class="rubric-box" style="margin-bottom: 0.8rem;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.4rem;">
                            <span class="metric-title">{html.escape(title)}</span>
                            <span style="font-size: 1.15rem; font-weight: 700; color: #0284C7; background: #E0F2FE; padding: 2px 8px; border-radius: 6px;">{item.score} / 25</span>
                        </div>
                        <p style="color: #334155; font-size: 0.92rem; line-height: 1.5; margin: 0.4rem 0 0.6rem 0;">{html.escape(item.explanation)}</p>
                    </div>
                    """, unsafe_allow_html=True)
                    st.progress(item.score / 25.0)
                    st.write("")

        # Function Check — structural map of what the report does / doesn't do
        _stage = st.session_state.get("current_stage_result")
        _l1 = getattr(_stage, "level_1_result", None) if _stage else None
        if _l1 and _l1.structure_checklist:
            st.write("---")
            st.markdown("### 🧭 Function Check — what your report does")
            st.caption(
                "A first-pass structural read, not a score. Every strong executive report performs "
                "these functions — in whatever structure or section order you choose. Missing ones "
                "are the fastest place to strengthen your next draft; check them against the pillar "
                "feedback above."
            )
            fc_col1, fc_col2 = st.columns(2)
            for fc_idx, fc_item in enumerate(_l1.structure_checklist):
                mark = "✅" if fc_item.present else "⬜"
                border = "#16A34A" if fc_item.present else "#CA8A04"
                bg = "#F0FDF4" if fc_item.present else "#FEFCE8"
                note = html.escape(fc_item.evidence or "") if not fc_item.present else ""
                note_html = f'<div style="color:#713F12; font-size:0.82rem; margin-top:3px;">{note}</div>' if note and note.lower() != "not found" else ""
                (fc_col1 if fc_idx % 2 == 0 else fc_col2).markdown(f"""
                <div style="background:{bg}; border-left:3px solid {border}; padding:6px 10px; margin:4px 0; font-size:0.9rem; color:#1E293B;">
                    {mark} {html.escape(fc_item.element)}{note_html}
                </div>
                """, unsafe_allow_html=True)

        # Side-by-Side Diagnostic: Gaps vs Socratic Questions
        st.write("---")
        diag_col1, diag_col2 = st.columns(2)

        _single_pass = not res.gaps_and_missing_elements and not res.questions_for_author

        with diag_col1:
            st.markdown("#### ⚠️ Key Areas for Refinement")
            if res.gaps_and_missing_elements:
                for gap in res.gaps_and_missing_elements:
                    st.warning(f"• {gap}")
            elif _single_pass:
                st.info(
                    "A lighter single-pass review ran for this draft, so the detailed gap list and "
                    "author questions aren't available. Use the pillar feedback and the Function "
                    "Check below, and resubmit for a full review."
                )
            else:
                st.success("✅ No major structural, sourcing, or reasoning gaps flagged for this draft.")

            if getattr(res, "internal_inconsistencies", None):
                st.markdown("**🔀 Internal inconsistencies to reconcile** _(highlighted for revision, not scored)_")
                for inc in res.internal_inconsistencies:
                    st.markdown(f"""
                    <div style="background: #FEF9C3; border-left: 3px solid #CA8A04; padding: 6px 10px; margin: 4px 0; font-size: 0.9rem; color: #713F12;">
                        {html.escape(str(inc))}
                    </div>
                    """, unsafe_allow_html=True)

        with diag_col2:
            st.markdown("#### ❓ Socratic Questions for the Author")
            if res.questions_for_author:
                for i, q in enumerate(res.questions_for_author, 1):
                    st.markdown(f"""
                    <div class="author-question-box">
                        <strong>Question {i}:</strong> {html.escape(str(q))}
                    </div>
                    """, unsafe_allow_html=True)
            elif _single_pass:
                st.caption("Not generated on a single-pass review — resubmit for the full evaluation.")


# ==============================================================================
# TAB 2: INSTRUCTOR GRADEBOOK (Strictly Restricted to Authorized Instructors)
# ==============================================================================
elif app_mode == "📊 Instructor Gradebook":
    if not is_instructor:
        st.markdown('<div class="main-title">📊 Instructor Gradebook & Submissions Archive</div>', unsafe_allow_html=True)
        st.markdown('<div class="sub-title">Restricted to authorized instructors. Please enter the instructor PIN to access the gradebook.</div>', unsafe_allow_html=True)
        
        pin_col, _ = st.columns([1, 1])
        with pin_col:
            with st.form("gradebook_pin_form"):
                entered_pin = st.text_input("Enter Instructor PIN", type="password", key="gradebook_auth_pin")
                submit_pin = st.form_submit_button("🔓 Unlock Gradebook", type="primary", use_container_width=True)
                if submit_pin:
                    if entered_pin.strip() == INSTRUCTOR_PIN:
                        st.session_state.instructor_authenticated = True
                        st.rerun()
                    else:
                        st.error("❌ Incorrect Instructor PIN.")
        st.stop()

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
            f"{s.student_name} ({s.student_email}) | Attempt #{s.attempt_number} [{s.report_type}] - {s.total_score}/100 - {s.timestamp}": s
            for s in all_submissions
        }
        chosen_key = st.selectbox("Select a submission record to inspect:", list(submission_options.keys()))

        if chosen_key:
            selected_sub = submission_options[chosen_key]
            st.markdown(f"### Submission: **{selected_sub.student_name}** (`{selected_sub.student_email}`) — Attempt #{selected_sub.attempt_number}")
            st.write(f"**Report Title:** {selected_sub.report_title} | **Subject:** `{selected_sub.report_type}` | **File:** `{selected_sub.filename or 'Direct Paste'}` | **Submitted At:** {selected_sub.timestamp}")
            st.write(f"**Score:** {selected_sub.total_score}/100")
            if selected_sub.result.evaluation_note:
                st.warning(f"⚙️ Pipeline note: {selected_sub.result.evaluation_note}")

            _PILLAR_LABELS = [
                ("clarity_of_scope", "Framing, Scope & Coherence"),
                ("evidence_and_attribution", "Source Attribution & Evidence"),
                ("methodology", "Analytic Reasoning & Uncertainty"),
                ("actionability", "Executive Value & Actionability"),
            ]

            insp_tab1, insp_tab2, insp_tab3, insp_tab4 = st.tabs([
                "📄 Uploaded Report Content",
                "🏆 Tier 2 — Final Scorecard",
                "📝 Tier 1 — Level 1 Review",
                "🔀 Tier 1 vs Tier 2 + Integrity",
            ])

            with insp_tab1:
                st.markdown("**Original Uploaded / Submitted Text:**")
                # Render as inert text (never as HTML) - report_content is untrusted student input.
                st.text_area(
                    "Original submitted text",
                    value=selected_sub.report_content,
                    height=450,
                    disabled=True,
                    label_visibility="collapsed",
                )

            def _render_final(gr):
                st.info(gr.overall_critique)
                if gr.progress_note:
                    st.caption(f"Progress note shown to student: {gr.progress_note}")
                for field, label in _PILLAR_LABELS:
                    cs = getattr(gr, field)
                    caps = f"  _(caps: {', '.join(cs.caps_applied)})_" if cs.caps_applied else ""
                    st.write(f"- **{label} ({cs.score}/25):** {cs.explanation}{caps}")
                if gr.integrity_notice:
                    st.warning(f"Integrity note shown to student: {gr.integrity_notice}")
                if gr.gaps_and_missing_elements:
                    st.markdown("**Gaps & missing elements:**")
                    for g in gr.gaps_and_missing_elements:
                        st.write(f"- {g}")
                if getattr(gr, "internal_inconsistencies", None):
                    st.markdown("**Internal inconsistencies (highlighted, not scored):**")
                    for inc in gr.internal_inconsistencies:
                        st.write(f"> {inc}")
                if gr.questions_for_author:
                    st.markdown("**Questions for author:**")
                    for idx, q in enumerate(gr.questions_for_author, 1):
                        st.write(f"{idx}. {q}")

            def _render_level1(l1):
                st.info(l1.overall_critique)
                st.caption(f"Level 1 implied total: {l1.total_score}/100")
                if l1.structure_checklist:
                    st.markdown("**Function checklist:**")
                    for item in l1.structure_checklist:
                        mark = "✅" if item.present else "❌"
                        st.write(f"- {mark} **{item.element}** — {item.evidence or '—'}")
                for field, label in _PILLAR_LABELS:
                    cs = getattr(l1, field)
                    caps = f"  _(caps: {', '.join(cs.caps_applied)})_" if cs.caps_applied else ""
                    st.write(f"- **{label} ({cs.score}/25):** {cs.explanation}{caps}")
                for heading, quotes in [
                    ("Estimative-language quotes", l1.estimative_language_quotes),
                    ("Vague-language quotes", l1.vague_language_quotes),
                    ("Uncited-claim quotes", l1.uncited_claim_quotes),
                    ("Internal inconsistencies (not scored)", getattr(l1, "internal_inconsistencies", [])),
                ]:
                    if quotes:
                        st.markdown(f"**{heading}:**")
                        for qt in quotes:
                            st.write(f"> {qt}")

            with insp_tab2:
                _render_final(selected_sub.result)

            with insp_tab3:
                if selected_sub.level_1_result:
                    _render_level1(selected_sub.level_1_result)
                else:
                    st.caption("No Level 1 assessment recorded for this entry.")

            with insp_tab4:
                l1 = selected_sub.level_1_result
                if l1:
                    rows = []
                    for field, label in _PILLAR_LABELS:
                        l1s = getattr(l1, field).score
                        f2s = getattr(selected_sub.result, field).score
                        rows.append({"Pillar": label, "Tier 1": l1s, "Tier 2 (final)": f2s, "Δ": f2s - l1s})
                    rows.append({
                        "Pillar": "TOTAL", "Tier 1": l1.total_score,
                        "Tier 2 (final)": selected_sub.total_score,
                        "Δ": selected_sub.total_score - l1.total_score,
                    })
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                else:
                    st.caption("No Level 1 assessment to compare against.")

                st.markdown("**Integrity / security review (Tier 2):**")
                integ = selected_sub.integrity
                if integ is None:
                    st.caption("No integrity review recorded.")
                elif not integ.manipulation_detected:
                    st.success(f"No evaluator-manipulation content detected (severity: {integ.severity}).")
                else:
                    box = st.error if integ.severity == "high" else st.warning
                    box(f"Manipulation detected — severity **{integ.severity}**. {integ.note}")
                    for f in integ.findings:
                        st.write(f"- _{f.technique}_: “{f.quote}”")


# ==============================================================================
# TAB 3: EVALUATION OVERVIEW
# ==============================================================================
elif app_mode in ("📖 Evaluation Overview", "📖 Rubric Reference"):
    st.markdown('<div class="main-title">📖 Evaluation Overview — Executive CTI Report</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">A summary of the core principles and dimensions used to assess executive Threat Intelligence reports.</div>', unsafe_allow_html=True)

    st.markdown("""
    ### 🎯 Purpose & Audience
    Every submission is evaluated as a **Cyber Threat Intelligence report prepared for organisational leadership** (e.g., Executive Risk Committee, Board, C-Suite).

    This is a **thinking aid**, not a template checker. The goal is to encourage you to think bigger and build reports in a more structured way. There is **no single required format** — any structure that performs the functions below is fine, whatever your sections are called. We do **not** check whether your facts are correct, whether your sources are reliable, or whether we agree with your conclusions.

    **The score reflects whether each function is built into your report — not a tally of mistakes.** Individual gaps, claims without a reference, blurred confidence, and self-contradictions are *highlighted for your next draft*, they don't chip away at the number.

    ---

    ### 📋 Core Evaluation Dimensions

    Reports are evaluated across four functional pillars (0–25 each):

    1. **Framing, Scope & Coherence**
       - Does the report frame the question it answers and whose decision it serves, and define what's in and out of scope?
       - Does it lead with the core judgement and the requested decision, and read as one connected argument?

    2. **Source Attribution & Evidence**
       - Are the report's material claims (intrusions, statistics, vendor findings, attributions) linked to a source the reader can go to — an inline link, a footnote, or a reference list?
       - We check only that a reference **is attached** and that fact is kept separate from analyst inference — not whether the source is accurate or reliable.

    3. **Analytic Reasoning & Uncertainty**
       - Is the path from evidence to judgement visible, not just asserted?
       - Is uncertainty expressed in a calibrated, consistent scheme (ICD 203 terms, numeric bands, PHIA, or a house scale — all fine) with likelihood and confidence kept distinct, and assumptions and gaps surfaced?

    4. **Executive Value & Actionability**
       - Are technical findings translated into operational, financial, or regulatory implications leadership can weigh?
       - Are recommendations prioritised, concrete, and decision-ready?

    **Bonus signals** (lift a score, never lower it): a stated alternative explanation, honest treatment of your data's limits, named reassessment triggers.

    ---

    ### 🔁 Iterative Feedback & Revision
    This tool is designed to support the drafting and revision process:
    - Each draft receives diagnostic feedback detailing analytical strengths and actionable areas for refinement.
    - Subsequent revisions are compared against previous attempts to track your progress and analytical growth.
    """)
