#!/usr/bin/env python3
"""
Score-stability harness for the CTI report grader.

This measures RELIABILITY, not VALIDITY. It does not know or care whether any
score is "correct" - it grades the same unchanged report many times and reports
how much the score moves. Low spread = students can trust that a changed score
means their revision did something.

Usage:
    GEMINI_API_KEY=...  .venv/bin/python eval/stability_eval.py
    .venv/bin/python eval/stability_eval.py --runs 20 --workers 3
    .venv/bin/python eval/stability_eval.py --temperature 0.0 --label temp0
    .venv/bin/python eval/stability_eval.py --reports 'eval/reports/*.md' --reports sample_reports/sample_good_report.md

Outputs a per-report table to stdout and a full JSON record to eval/results/.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

# Import from the repo root regardless of where this is run from.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from grader import CTIGrader, EvaluationUnavailable, PILLAR_FIELDS  # noqa: E402

PILLAR_LABELS = {
    "clarity_of_scope": "Framing/Scope/Coherence",
    "evidence_and_attribution": "Source Attribution",
    "methodology": "Analytic Reasoning",
    "actionability": "Executive Value",
}

# Rough expected band per report, keyed by a substring of the filename. This is a
# gut-check on placement only - NOT a correctness metric.
EXPECTED_BAND = {
    "weak": (10, 30),
    "mid": (40, 60),
    "strong": (80, 100),
    "sample_good": (80, 100),
}

# SD thresholds for the verdict (total score, then per-pillar).
TOTAL_GREEN, TOTAL_YELLOW = 3.0, 5.0
PILLAR_GREEN, PILLAR_YELLOW = 1.5, 2.5


@dataclass
class RunRecord:
    ok: bool
    total: int | None = None
    pillars: dict = field(default_factory=dict)
    path: str | None = None            # full | tier1_only | tier2_standalone
    primary_model: str | None = None
    final_model: str | None = None
    integrity_severity: str | None = None
    tier1_total: int | None = None
    tier1_to_tier2_total_delta: int | None = None
    seconds: float | None = None
    error: str | None = None


def classify_path(stage_result) -> str:
    if stage_result.level_1_result is None:
        return "tier2_standalone"
    if stage_result.integrity is None:
        return "tier1_only"
    return "full"


def one_run(grader: CTIGrader, text: str, dual_review: bool, harness_retries: int) -> RunRecord:
    delay = 4.0
    last_err = None
    harness_retries = max(1, harness_retries)
    t0 = time.time()
    for attempt in range(harness_retries):
        t0 = time.time()
        try:
            sr = grader.grade_report(
                student_name="Eval Runner",
                report_text=text,
                dual_review=dual_review,
            )
            fr = sr.final_result
            return RunRecord(
                ok=True,
                total=fr.total_score,
                pillars={f: getattr(fr, f).score for f in PILLAR_FIELDS},
                path=classify_path(sr),
                primary_model=sr.primary_model_used,
                final_model=sr.final_model_used,
                integrity_severity=(sr.integrity.severity if sr.integrity else None),
                tier1_total=(sr.level_1_result.total_score if sr.level_1_result else None),
                tier1_to_tier2_total_delta=(sr.total_delta if sr.level_1_result else None),
                seconds=round(time.time() - t0, 1),
            )
        except EvaluationUnavailable as e:
            last_err = f"EvaluationUnavailable: {e}"
        except Exception as e:  # noqa: BLE001 - harness-level; likely rate limit / transient
            last_err = f"{type(e).__name__}: {e}"
        if attempt < harness_retries - 1:
            time.sleep(delay)
            delay *= 2
    return RunRecord(ok=False, error=last_err, seconds=round(time.time() - t0, 1))


def summarise(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "mean": round(statistics.mean(values), 2),
        "sd": round(statistics.stdev(values), 2) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
        "range": max(values) - min(values),
        "mode": statistics.multimode(values),
    }


def verdict(sd: float, green: float, yellow: float) -> str:
    if sd <= green:
        return "GREEN"
    if sd <= yellow:
        return "YELLOW"
    return "RED"


def band_for(name: str) -> tuple[int, int] | None:
    for key, band in EXPECTED_BAND.items():
        if key in name:
            return band
    return None


def run_report(grader, path: Path, runs: int, workers: int, dual_review: bool, harness_retries: int):
    text = path.read_text(encoding="utf-8")
    records: list[RunRecord] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(one_run, grader, text, dual_review, harness_retries) for _ in range(runs)]
        for i, fut in enumerate(as_completed(futs), 1):
            rec = fut.result()
            records.append(rec)
            tag = f"total={rec.total}" if rec.ok else f"FAIL {rec.error}"
            print(f"  [{path.name}] run {i}/{runs}  {tag}")
    return records


def report_block(name: str, records: list[RunRecord]) -> dict:
    ok = [r for r in records if r.ok]
    fails = [r for r in records if not r.ok]
    totals = [r.total for r in ok]
    per_pillar = {f: summarise([r.pillars[f] for r in ok]) for f in PILLAR_FIELDS}
    total_stats = summarise(totals)
    paths = {}
    for r in ok:
        paths[r.path] = paths.get(r.path, 0) + 1
    t1t2 = [r.tier1_to_tier2_total_delta for r in ok if r.tier1_to_tier2_total_delta is not None]

    print(f"\n=== {name} ===  (ok={len(ok)}, failed={len(fails)})")
    if total_stats.get("n"):
        band = band_for(name)
        band_str = ""
        if band:
            lo, hi = band
            hit = lo <= total_stats["mean"] <= hi
            band_str = f"   expected {lo}-{hi}  [{'in band' if hit else 'OUT OF BAND'}]"
        print(f"  {'pillar':<24}{'mean':>7}{'sd':>7}{'min':>6}{'max':>6}{'range':>7}")
        for f in PILLAR_FIELDS:
            s = per_pillar[f]
            v = verdict(s["sd"], PILLAR_GREEN, PILLAR_YELLOW)
            print(f"  {PILLAR_LABELS[f]:<24}{s['mean']:>7}{s['sd']:>7}{s['min']:>6}{s['max']:>6}{s['range']:>7}  {v}")
        tv = verdict(total_stats["sd"], TOTAL_GREEN, TOTAL_YELLOW)
        print(f"  {'TOTAL':<24}{total_stats['mean']:>7}{total_stats['sd']:>7}{total_stats['min']:>6}{total_stats['max']:>6}{total_stats['range']:>7}  {tv}{band_str}")
        print(f"  degradation path: " + ", ".join(f"{k}={v}" for k, v in sorted(paths.items())))
        if t1t2:
            print(f"  Tier1->Tier2 total delta: mean {round(statistics.mean(t1t2), 2)}, "
                  f"sd {round(statistics.stdev(t1t2), 2) if len(t1t2) > 1 else 0.0}, "
                  f"range [{min(t1t2)}, {max(t1t2)}]")
    if fails:
        print(f"  failures ({len(fails)}):")
        for r in fails[:5]:
            print(f"    - {r.error}")

    return {
        "report": name,
        "runs_ok": len(ok),
        "runs_failed": len(fails),
        "total": total_stats,
        "pillars": per_pillar,
        "degradation_paths": paths,
        "tier1_to_tier2_total_delta": summarise([float(x) for x in t1t2]) if t1t2 else {"n": 0},
        "expected_band": band_for(name),
        "raw_runs": [asdict(r) for r in records],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=15, help="grading runs per report (default 15)")
    ap.add_argument("--workers", type=int, default=3, help="concurrent runs (default 3; raise carefully - rate limits)")
    ap.add_argument("--reports", action="append", default=None,
                    help="glob or path, repeatable (default: eval/reports/*.md + the repo sample_good_report)")
    ap.add_argument("--temperature", type=float, default=None, help="override grader temperature (e.g. 0.0)")
    ap.add_argument("--no-dual-review", action="store_true", help="Tier 1 only (skip the final evaluator)")
    ap.add_argument("--attempts-per-call", type=int, default=2, help="grader's per-call retry budget (default 2)")
    ap.add_argument("--harness-retries", type=int, default=3, help="harness-level retries per run on transient errors (default 3)")
    ap.add_argument("--out", default=str(_ROOT / "eval" / "results"), help="output dir for the JSON record")
    ap.add_argument("--label", default=None, help="tag added to the output filename")
    args = ap.parse_args()

    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_APIKEY")):
        print("GEMINI_API_KEY is not set.", file=sys.stderr)
        return 2

    patterns = args.reports or [
        str(_ROOT / "eval" / "reports" / "*.md"),
        str(_ROOT / "sample_reports" / "sample_good_report.md"),
    ]
    paths: list[Path] = []
    for pat in patterns:
        hits = [Path(p) for p in glob.glob(pat)] or ([Path(pat)] if Path(pat).exists() else [])
        paths.extend(sorted(hits))
    paths = sorted({p.resolve() for p in paths})
    if not paths:
        print(f"No report files matched: {patterns}", file=sys.stderr)
        return 2

    grader = CTIGrader(temperature=args.temperature, attempts_per_call=args.attempts_per_call)
    dual = not args.no_dual_review

    print(f"Reports ({len(paths)}): " + ", ".join(p.name for p in paths))
    print(f"runs={args.runs}  workers={args.workers}  dual_review={dual}  "
          f"temperature={grader.temperature}  primary={grader.primary_model}  final={grader.final_model}")
    print("-" * 72)

    started = time.time()
    blocks = []
    for p in paths:
        recs = run_report(grader, p, args.runs, args.workers, dual, args.harness_retries)
        blocks.append(report_block(p.name, recs))

    elapsed = round(time.time() - started, 1)
    print("\n" + "=" * 72)
    print("SUMMARY")
    print(f"  {'report':<26}{'total mean':>12}{'total sd':>10}{'range':>8}   verdict")
    for b in blocks:
        t = b["total"]
        if not t.get("n"):
            print(f"  {b['report']:<26}{'(all failed)':>12}")
            continue
        print(f"  {b['report']:<26}{t['mean']:>12}{t['sd']:>10}{t['range']:>8}   {verdict(t['sd'], TOTAL_GREEN, TOTAL_YELLOW)}")
    print(f"\n  thresholds: total sd <= {TOTAL_GREEN} GREEN, <= {TOTAL_YELLOW} YELLOW; "
          f"pillar sd <= {PILLAR_GREEN} / {PILLAR_YELLOW}")
    print(f"  wall time: {elapsed}s")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    fname = f"stability_{stamp}" + (f"_{args.label}" if args.label else "") + ".json"
    out_path = out_dir / fname
    out_path.write_text(json.dumps({
        "generated_utc": stamp,
        "config": {
            "runs": args.runs, "workers": args.workers, "dual_review": dual,
            "temperature": grader.temperature, "attempts_per_call": args.attempts_per_call,
            "primary_model": grader.primary_model, "final_model": grader.final_model,
            "reports": [p.name for p in paths],
        },
        "elapsed_seconds": elapsed,
        "results": blocks,
    }, indent=2), encoding="utf-8")
    print(f"  full record: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
