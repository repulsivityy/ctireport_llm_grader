# 🛡️ Cyber Threat Intelligence (CTI) Report Grader

An automated **LLM-as-a-Judge** web platform that evaluates student **executive CTI reports**
on a **100-point scale (4 pillars × 25)** using a two-tier Gemini pipeline.

This is a **workshop / practice tool**, not an exam. Every student always gets an immediate
grade and feedback; nothing is queued for human approval.

> **What it grades:** completeness, structure, sourcing discipline, and analytic tradecraft.
> **What it does _not_ grade:** whether the report's factual claims are actually true. A
> well-structured, fully-cited report built on claims the model doubts still scores well;
> a plausible-sounding report with no citations or estimative language scores poorly.

## 🔁 How the two tiers work

| | Model | Job | Output |
| :--- | :--- | :--- | :--- |
| **Tier 1** | `gemini-3.5-flash-lite` | Structure & completeness check, pillar scoring, evidence gathering (pulls verbatim quotes of estimative language, vague hedging, and uncited claims). Does **not** do the security review. | `Level1Assessment` |
| **Tier 2** | `gemini-3.7-flash` | (1) **Integrity / security review** of the submission — detects prompt injection, instruction overrides, fake system messages, score demands. (2) **De-anchored audit** of Tier 1: it sees Tier 1's checklist, quotes and written reasoning **but not its numeric scores**, and grades each pillar independently, explaining any divergence. | `FinalAdjudication` → `GradingResult` |

- The **platform** (Python) sums the four Tier 2 pillar scores — no model owns the total.
  Output is a **0–100 score only** — no letter grade, no pass/fail.
- A **high-severity manipulation attempt** caps the Analytic Tradecraft pillar at 8 and shows
  the student a learning note explaining why. It is never a hidden or separate penalty.
- Tier 1 ↔ Tier 2 per-pillar deltas and the integrity findings are stored and shown in the
  **instructor gradebook** for review — but they do not gate or delay the student's result.

### Graceful degradation

The pipeline fails silently and uses whatever scoring is available (each tier is retried once):

| Situation | Result shown to the student |
| :--- | :--- |
| Both tiers OK | Tier 2's de-anchored audit |
| Tier 1 fails | Tier 2 grades the report standalone |
| Tier 2 fails | Tier 1's scores (no integrity review that attempt) |
| Both fail | An error — nothing is graded or saved; the student resubmits |

The instructor gradebook records which path was taken (`evaluation_note`).

### Iterating on a draft

A workshop is about revising. When a student resubmits, the previous attempt's report and
scores are passed to Tier 2, which returns a **`progress_note`** — a specific "what changed
since last time" comparison shown above the new scorecard. A student cannot re-grade the
**exact same text** twice; the submit button unlocks only after the report is edited.

---

## 🎯 Evaluation Principles

Every submission is evaluated as an **executive-level CTI report** prepared for senior organizational decision-makers (Risk Committees, Board of Directors, C-Suite). 

Rather than enforcing rigid formatting, the evaluation assesses reports against core tradecraft dimensions:

### 📋 The 4 Core Evaluation Pillars

1. **Structure, Scope & Framing**: Clear problem definition, defined operational context and boundaries, and an executive-first narrative progression.
2. **Evidence & Sourcing Rigor**: Factual claims backed by traceable references, empirical grounding, and disciplined separation between verified data and analyst deduction (unresolved automated search tokens receive formatting hygiene deductions rather than zero-credit).
3. **Analytic Tradecraft & Reasoning**: Disciplined analytical assertions, calibrated likelihood and confidence for forecasts, transparent intelligence gaps, and context-aware grading (purely factual retrospectives are not penalized for omitting probability terms).
4. **Executive Actionability & Business Impact**: Translation of technical findings into operational, financial, or regulatory business implications, paired with prioritized, decision-ready mitigation recommendations.

### 🎯 Reading the Feedback

There is **no letter grade and no pass/fail** — this platform is designed as an iterative learning tool. The 0–100 score makes progress visible across drafts. Students improve their work by analyzing the per-pillar diagnostic feedback, identified gaps, and revision comparison notes.

---

## 🔒 Access Control & User Tracking

The platform provides simple, frictionless access without requiring third-party OAuth setup:

- **Visitors & Students**: Can view the landing page and the **📖 Evaluation Overview** without logging in.
- **Report Submission**: Students enter their email address to access the submission portal. Submissions, scorecards, and iterative revisions are tracked automatically by email.
- **Instructor Gradebook**: The **"📊 Instructor Gradebook"** tab is protected by an **Instructor PIN** (`INSTRUCTOR_PIN` in `.env`, defaulting to `cti-instructor-2026`). Authorized instructors can inspect all student submissions, view Tier 1 vs Tier 2 score breakdowns, and monitor class metrics.

---

## ☁️ Deploy to Google Cloud Run

### 1. Configure Environment (`.env`)
Copy and configure `.env`:
```bash
cp .env.example .env
```
Ensure the following are set:
- `GEMINI_API_KEY`: Your Google GenAI API key.
- `GOOGLE_CLOUD_PROJECT`: Your GCP project ID (e.g. `virustotal-lab`).
- `INSTRUCTOR_PIN`: Secret passcode to unlock the Instructor Gradebook (e.g. `cti-instructor-2026`).

### 2. Deploy
```bash
chmod +x deploy.sh
./deploy.sh
```

`deploy.sh` automatically:
1. Enables required GCP APIs (Secret Manager, Cloud Run, Cloud Build, Firestore).
2. Syncs `GEMINI_API_KEY` into Secret Manager.
3. Builds and deploys the container to Cloud Run with public landing page access.
4. Mounts the runtime secrets and environment variables.

### Management Subcommands
```bash
./deploy.sh purge        # PERMANENTLY delete every stored submission (Firestore + local db)
```

---

## 💻 Local Testing

```bash
pip install -r requirements.txt
ALLOW_INSECURE_LOCAL_AUTH=true streamlit run app.py
```

Open `http://localhost:8501`.

Sample inputs live in `sample_reports/`:
- `sample_good_report.md`: Baseline high-scoring exemplar.
- `sample_prompt_injection_attempt.md`: Adversarial report attempting to instruct the grader to assign 100/100, which trips the Tier 2 integrity review.
