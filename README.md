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

## 🎯 The brief given to students

Every submission is treated as a **CTI report written for executives and upper management**.
Students choose the subject; the grader adapts the *expected section structure* to it:

| Report subject | Structure the grader expects |
| :--- | :--- |
| **Threat landscape** | What matters now, what changed vs. the prior period, **and an explicit "what is next" / outlook** section |
| **Vulnerability / CVE assessment** | The vulnerability, our exposure, exploitation status, **and a dedicated Business Impact Assessment** |
| **Threat actor profile** | Attributed activity, targeting logic, intent, and actionable TTPs |
| **Incident retrospective** | Timeline, impact, root cause, lessons and follow-up actions |

All subjects are still expected to open with a **BLUF**, state **scope + time window**, cite
their claims, and use **ICD 203 estimative + confidence language**.

---

## 🏆 Gold-standard structure

```markdown
# 1. Bottom Line Up Front (BLUF) / Executive Summary
#    core judgement first: the threat, how likely, how confident, the decision requested
# 2. Scope & Methodology
#    coverage & exclusions, reporting period, sources + reliability, assumptions, intel gaps
# 3. Body  (adapts to the subject - see table above)
#    every factual claim carries a citation (inline URL or numbered appendix reference)
# 4. Business Impact
#    operational / financial / regulatory-legal consequences in executive terms
# 5. Recommendations / Requested Decisions
#    prioritised, concrete, decision-ready (a budget ask, a policy call)
# 6. Appendix
#    numbered source list; IOCs / rules / raw data kept out of the narrative
```

### Estimative probability & confidence (ICD 203)

Likelihood terms — *almost no chance · very unlikely · unlikely · roughly even chance ·
likely · very likely · almost certain* — **not** "could / may / might".

A separate **confidence level** — *low / moderate / high* — based on how solid the sourcing
is, kept distinct from likelihood:

> "We assess it is **very likely** (**high confidence**) that …"

### Citing claims

Either inline:

> Bank A disclosed a ransomware incident in March 2026 — `www.example-news.com/bank-a-breach`

or numbered, resolved in an appendix:

> Bank A disclosed a ransomware incident in March 2026 **[3]**
> …
> **[3]** www.example-news.com/bank-a-breach

---

## 📋 Scoring — 4 pillars × 25 = 100

| Pillar (internal field) | What earns the marks | Hard caps |
| :--- | :--- | :--- |
| **1. Structure, Scope & Completeness** (`clarity_of_scope`) | BLUF present; scope + time window defined; sections complete and appropriate to the subject; appendix present if numbered refs are used | No BLUF → **max 8**. Missing the subject-critical section (e.g. vuln report with no business impact) → **max 10** |
| **2. Evidence & Sourcing** (`evidence_and_attribution`) | Every factual claim has a traceable citation (inline URL or numbered appendix reference); source confidence characterised | Several uncited material claims → **max 10**. No sourcing mechanism at all → **max 5** |
| **3. Analytic Tradecraft & Estimative Language** (`methodology`) | ICD 203 likelihood terms; explicit confidence level kept separate from likelihood; methodology, assumptions, intel gaps; consistent throughout | No estimative/confidence language anywhere → **max 8**. Confidence and likelihood conflated → **max 15** |
| **4. Executive Communication & Actionability** (`actionability`) | Written for leadership; jargon controlled; clear "so what"; prioritised, decision-ready recommendations | Raw technical dump, no exec framing → **max 8**. Recommendations absent or generic ("stay vigilant") → **max 8** |

### 🎯 Reading the score

There is **no letter grade and no pass/fail**. The 0–100 number exists only to make
progress between drafts visible. Students work from the per-pillar explanations, the gaps
list, and the "what changed" note on each revision. The four pillar scores are summed
**in Python** — the model never owns the total.

---

## 🔒 Authentication & Access Control

The app features a **public-facing landing page** with secure **Google Sign-In (OAuth 2.0 / OIDC)**:

- **Visitors & Students**: Can immediately view the landing page, read the course briefing, and review the **📖 Rubric Reference** without authenticating.
- **Report Submission**: Clicking **"🔵 Sign in with Google"** authenticates the user via Google Accounts (GAIA / OAuth 2.0).
  - Supports any Google Workspace account or `@gmail.com` user.
  - Automatically identifies the student to track their revision attempts, past scores, and progression deltas.
- **Instructor Gradebook**: The **"📊 Instructor Gradebook"** tab only unlocks if the authenticated Google email matches `INSTRUCTOR_EMAILS`. Students cannot access or tamper with instructor views.
- **Local Development**: Set `ALLOW_INSECURE_LOCAL_AUTH=true` in `.env` to enable an email input in the sidebar for offline testing.

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
- `INSTRUCTOR_EMAILS`: Comma-separated list of instructor Google emails.
- `GOOGLE_CLIENT_ID` & `GOOGLE_CLIENT_SECRET`: OAuth 2.0 Web Client credentials from GCP Console (`APIs & Services > Credentials`).
- `REDIRECT_URI`: `https://<YOUR-CLOUD-RUN-SERVICE-URL>/oauth2callback`

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
