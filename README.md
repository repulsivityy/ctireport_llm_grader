# 🛡️ Cyber Threat Intelligence (CTI) Report Grader

An automated, LLM-as-a-Judge web platform for evaluating student Threat Intelligence reports on a **100-point scale (4 criteria × 25 points each)** using **Gemini 3.5 Flash-Lite (Level 1 Assessor)** and **Gemini 3.7 Flash (Final Evaluator)**.

---

## 🎯 3 Calibrated CTI Report Types & Tradecraft Rubrics

### 1. 🕵️ Threat Actor Deep Dive Report
- **Clarity of Scope (0–25):** 
  - *Identity & Alias Hygiene:* Primary designation stated, vendor aliases mapped, naming conflicts acknowledged, cluster boundaries defined. *(Undifferentiated alias soup = max 5/25)*.
  - *Victimology & Targeting Logic:* Granular sectors, geographies, organization profile, time-bounded, and reasoning for target selection. *(Sector list with no reasoning = max 7/25)*.
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

### 2. 🌐 Country Threat Landscape
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

### 3. 🛡️ CVE Strategic Reporting
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

## ☁️ Deploy to Google Cloud Run

```bash
cd cti_report_grader
chmod +x deploy.sh
./deploy.sh
```

---

## 💻 Local Testing

```bash
cd cti_report_grader
pip install -r requirements.txt
streamlit run app.py
```
Open `http://localhost:8501` in your browser.
