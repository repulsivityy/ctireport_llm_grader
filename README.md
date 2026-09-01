# 🛡️ Cyber Threat Intelligence (CTI) Report Grader

An automated **LLM-as-a-Judge** web platform that evaluates student **executive CTI reports**
on a **100-point scale (4 pillars × 25)** using a two-tier Gemini pipeline.

This is a **workshop / practice tool**, not an exam. Every student always gets an immediate
grade and feedback; nothing is queued for human approval.

> **What it grades:** whether the report is *structured and reasoned* so an executive can act —
> problem framing, coherence, source attribution, calibrated uncertainty, decision-readiness.
> It is a **thinking aid, not a template checker**: any structure that performs the functions
> is fine, whatever the sections are called.
> **What it does _not_ grade:** whether the report's factual claims are true, whether its
> sources are reliable, or whether the model agrees with its conclusions. It also does **not**
> deduct per mistake — individual gaps, uncited claims, and self-contradictions are *highlighted
> for the next draft*, not subtracted from the score.

## 🔁 How the two tiers work

| | Model | Job | Output |
| :--- | :--- | :--- | :--- |
| **Tier 1** | `gemini-3.5-flash-lite` | Function checklist, pillar scoring, evidence gathering (pulls verbatim quotes of estimative language, vague hedging, uncited claims, and internal inconsistencies). Does **not** do the security review. | `Level1Assessment` |
| **Tier 2** | `gemini-3.7-flash` | (1) **Integrity / security review** of the submission — detects prompt injection, instruction overrides, fake system messages, score demands. (2) **De-anchored audit** of Tier 1: it sees Tier 1's checklist, quotes and written reasoning **but not its numeric scores**, and grades each pillar independently, explaining any divergence. | `FinalAdjudication` → `GradingResult` |

- The **platform** (Python) sums the four Tier 2 pillar scores — no model owns the total.
  Output is a **0–100 score only** — no letter grade, no pass/fail.
- A **high-severity manipulation attempt** caps the *Analytic Reasoning & Uncertainty* pillar at 8 and shows
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

The evaluation does **not** enforce a template or a required set of section headings. It checks whether the report performs a set of **functions**, grouped into four pillars. The score reflects how completely each function is *built into* the report — not a tally of mistakes.

### 📋 The 4 Core Evaluation Pillars

1. **Framing, Scope & Coherence**: Frames the question and the decision it serves, defines what's in and out of scope, leads with the judgement, and reads as one connected argument.
2. **Source Attribution & Evidence**: Material claims are linked to a source the reader can go to (inline link, footnote, or reference list), and analyst inference is kept separate from sourced fact. Checks only that a reference **is attached** — not whether the source is accurate or reliable. Unresolved automated search tokens are noted as a traceability gap, not treated as "no sourcing".
3. **Analytic Reasoning & Uncertainty**: The path from evidence to judgement is visible; likelihood and confidence are expressed in a calibrated, consistent scheme (ICD 203, numeric bands, PHIA, or a house scale) and kept distinct; assumptions and gaps are surfaced. Purely factual retrospectives are not penalized for omitting probability terms.
4. **Executive Value & Actionability**: Technical findings translated into operational, financial, or regulatory implications, paired with prioritized, decision-ready recommendations.

**Bonus signals** (lift a pillar score, never lower it): a stated alternative explanation, honest treatment of the report's own data limits, named reassessment triggers.

### 🎯 Reading the Feedback

There is **no letter grade and no pass/fail** — this platform is designed as an iterative learning tool. The 0–100 score makes progress visible across drafts. Gaps, uncited claims, and internal inconsistencies are surfaced as **highlights for the next draft**, not score deductions.

The scorecard's feedback is split by intent:

- **⚠️ Key Areas for Refinement** — functions that are absent or half-built. What the report still needs.
- **🚀 How to Level Up** — 1–3 pushes that take an already-sound report *further* (build on strengths, think bigger). Not gap fixes; only shown when the report is structurally solid.
- **❓ Questions to Push Your Thinking** — three developmental questions a mentor would ask to stretch the analysis, not to point out gaps.
- **🧭 Function Check** — a first-pass structural map of which functions a strong executive report performs (frames the problem, leads with the judgement, links claims to sources, shows its reasoning, handles uncertainty, draws out what matters, gives the reader something to do) are present and which are missing.

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
