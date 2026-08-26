# 🛡️ Cyber Threat Intelligence (CTI) Report Grader

An automated, LLM-as-a-Judge web platform for evaluating student Threat Intelligence reports on a **100-point scale (4 criteria × 25 points each)** using **Gemini 3.5 Flash-Lite (Level 1 Assessor)** and **Gemini 3.7 Flash (Final Evaluator)**.

---

## 🎯 4-Pillar CTI Rubric (100-Point Scale)

1. **Actionability (0–25 points)**:
   - Can security teams take direct defensive action based on this?
   - *17–25 pts:* Concrete Sigma/YARA/Snort rules, firewall blocks, prioritized patching matrix.
   - *8–16 pts:* General advice lacking technical parameters or rule syntax.
   - *0–7 pts:* Vague platitudes ("stay vigilant").

2. **Clarity of Scope (0–25 points)**:
   - Are the targeted sectors, regions, or systems clearly defined?
   - *17–25 pts:* Granular victimology, targeted infrastructure, specific software versions.
   - *8–16 pts:* Broad sector named without attack surface specifics.
   - *0–7 pts:* Unbounded claims ("attacks all computers").

3. **Evidence and Attribution (0–25 points)**:
   - Are claims backed by solid technical data, logs, or IoCs, or is it pure speculation?
   - *17–25 pts:* Verified SHA256 hashes, C2 telemetry, CVE IDs, MITRE ATT&CK technique IDs, and explicit confidence level ratings.
   - *8–16 pts:* Adversary named with some IoCs, but missing source validation.
   - *0–7 pts:* Speculation with zero verifiable artifacts.

4. **Methodology (0–25 points)**:
   - Does the report explain how the data was gathered and analyzed?
   - *17–25 pts:* Transparent analytic workflow (honeypot telemetry, reverse engineering sandbox analysis).
   - *8–16 pts:* High-level data source mentioned without methodology explanation.
   - *0–7 pts:* No explanation of intelligence origin.

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
