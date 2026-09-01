# Score-stability harness

Measures **reliability, not validity**: it grades the same unchanged report many
times and reports how much the score moves. It never decides whether a score is
"right" — only whether it is *consistent*. If the run-to-run spread on identical
text is as large as the change a real revision produces, students can't tell
whether their edit helped.

## Run it

```bash
GEMINI_API_KEY=... .venv/bin/python eval/stability_eval.py
```

Common options:

```bash
--runs 20            # grading runs per report (default 15)
--workers 3          # concurrency (default 3 — raise carefully, Gemini rate limits)
--temperature 0.0    # override grader temperature (default 0.2) to compare spread
--no-dual-review     # Tier 1 only
--reports 'eval/reports/*.md' --reports sample_reports/sample_good_report.md
--label temp0        # tag the output JSON filename
```

Each run prints a per-report table (per-pillar and total mean / sd / min / max /
range, plus a GREEN/YELLOW/RED verdict) and writes the full per-run record to
`eval/results/`.

## The three fixtures

| File | Design target* | What it exercises |
| :--- | :--- | :--- |
| `reports/weak_report.md` | ~10–30 | No BLUF or decision ask, no sources, vague hedging, generic recs — should trip every structural cap |
| `reports/mid_report.md` | ~40–60 | Recognisable structure but half-built everywhere: fuzzy ask, some claims uncited, inconsistent confidence language, unscoped recs |
| `reports/strong_report.md` | ~80+ | Full BLUF + calibrated confidence, every claim cited, assumptions/gaps, business impact, prioritised recs with owners, alternative hypothesis, reassessment triggers, TLP marking |

\* The target band is a placement gut-check, **not** a correctness measure — "good"
is contextual and the harness does not evaluate it. The repo's
`sample_reports/sample_good_report.md` is included by default as a fourth
high-scoring reference point.

## Reading the verdict

- **Total score sd** ≤ 3 GREEN, ≤ 5 YELLOW, else RED.
- **Per-pillar sd** ≤ 1.5 / ≤ 2.5.
- **`degradation path`** — how many runs went `full` (both tiers) vs `tier1_only`
  (Tier 2 failed) vs `tier2_standalone` (Tier 1 failed). A mix here means part of
  the spread is infrastructure luck switching which model produced the score.
- **`Tier1->Tier2 total delta`** — how far the final evaluator moved from Tier 1.
  A large, wide delta means the rubric is ambiguous enough that two models read it
  differently.
