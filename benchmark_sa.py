"""Phase 2F: simulated annealing vs. backtracking vs. QAOA (stored results).

Protocol
--------
* Pilot: 5 SA runs to measure cost; the 30-run experiment proceeds only if
  the estimated total stays trivial (< 60 s).
* Main experiment: 30 independent SA runs with fixed seeds 101..130 and
  identical settings, on the UNCHANGED verified QUBO.
* Classical backtracking baseline: re-measured fresh (200 repeats).
* QAOA: NOT rerun (expensive; per instructions). The stored five-seed
  Phase 2C measurements are loaded from results/benchmark_results.json and
  the comparison is labeled PRELIMINARY because sample sizes differ
  (30 SA runs vs 5 QAOA trials per depth).
* Success definitions are kept distinct:
    - SA/backtracking: a successful RUN finds one zero-energy solution.
    - QAOA: a successful TRIAL has >= 1 valid candidate among 4000 final
      sampled shots. One QAOA trial costs tens of thousands of shots plus
      an optimization loop; one SA run costs <= 50,001 energy evaluations.
      Equal counts do NOT mean equal computational effort.
* Time-to-solution (TTS): expected TTS = total wall time across all runs /
  number of successful runs (failures included). TTS99 = time to reach 99%
  probability of >= 1 success under independent repeated attempts:
      TTS99 = median_run_time * ln(0.01) / ln(1 - p)
  where p is the measured per-run success fraction. If p = 1 the formula
  is undefined; the 99th-percentile single-run time is reported instead.
  Assumptions: runs are independent and p is estimated from a finite
  sample (binomial uncertainty; for QAOA, p rests on only 5 trials).

Outputs (new files; original Phase 2C outputs are never overwritten):
  results/sa_benchmark_results.json
  results/solver_comparison_charts.png

Run:  python benchmark_sa.py
"""

import json
import math
import statistics
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from benchmark import run_classical_baseline
from simulated_annealing import (
    DEFAULT_COOLING_RATE,
    DEFAULT_INITIAL_TEMPERATURE,
    DEFAULT_MAX_ITERATIONS,
    run_simulated_annealing,
)

PILOT_SEEDS = [901, 902, 903, 904, 905]
MAIN_SEEDS = list(range(101, 131))  # 30 independent runs
PILOT_BUDGET_SECONDS = 60
CLASSICAL_REPEATS = 200


def tts99(success_probability: float, median_time: float,
          times: list[float]) -> tuple[float | None, str]:
    """99% time-to-solution estimate. Returns (value_seconds, note)."""
    p = success_probability
    if p <= 0:
        return None, "undefined: no successful runs"
    if p >= 1:
        times_sorted = sorted(times)
        idx = min(len(times_sorted) - 1, math.ceil(0.99 * len(times_sorted)) - 1)
        return times_sorted[idx], (
            "all runs succeeded; reporting 99th-percentile single-run time"
        )
    value = median_time * math.log(0.01) / math.log(1.0 - p)
    return value, (
        f"median run time x ln(0.01)/ln(1-p), p={p:.3f} from finite sample"
    )


def summarize_sa(runs: list[dict]) -> dict:
    times = [r["time_s"] for r in runs]
    energies = [r["best_energy"] for r in runs]
    successes = [r for r in runs if r["found_valid_solution"]]
    p = len(successes) / len(runs)
    total_time = sum(times)
    expected_tts = total_time / len(successes) if successes else None
    t99, t99_note = tts99(p, statistics.median(times), times)
    return {
        "method": "simulated_annealing",
        "runtime_environment": "classical CPU (pure Python + NumPy RNG)",
        "settings": runs[0]["settings"],
        "n_runs": len(runs),
        "seeds": [r["seed"] for r in runs],
        "successful_runs": len(successes),
        "success_percent": 100.0 * p,
        "all_successes_validator_confirmed": all(
            r["validator_confirmed"] for r in successes
        ),
        "best_energy_overall": min(energies),
        "mean_best_energy": statistics.mean(energies),
        "median_time_s": statistics.median(times),
        "mean_time_s": statistics.mean(times),
        "stdev_time_s": statistics.stdev(times) if len(times) > 1 else 0.0,
        "min_time_s": min(times),
        "max_time_s": max(times),
        "median_time_to_valid_s": (
            statistics.median(r["time_to_valid_s"] for r in successes)
            if successes else None
        ),
        "mean_iterations": statistics.mean(r["iterations_used"] for r in runs),
        "median_energy_evaluations": statistics.median(
            r["energy_evaluations"] for r in runs
        ),
        "mean_energy_evaluations": statistics.mean(
            r["energy_evaluations"] for r in runs
        ),
        "total_time_all_runs_s": total_time,
        "expected_tts_including_failures_s": expected_tts,
        "tts99_s": t99,
        "tts99_note": t99_note,
    }


def load_qaoa_summaries(results_dir: Path) -> list[dict]:
    data = json.loads((results_dir / "benchmark_results.json").read_text())
    out = []
    for s in data["summaries"]:
        p = s["successful_trials"] / s["n_trials"]
        trials = [t for t in data["trials"] if t["depth"] == s["depth"]]
        times = [t["total_time_s"] for t in trials]
        t99, t99_note = tts99(p, s["median_total_time_s"], times)
        out.append({
            "method": f"qaoa_p{s['depth']}",
            "runtime_environment": "quantum circuit SIMULATOR (Aer, noiseless)",
            "n_runs": s["n_trials"],
            "successful_runs": s["successful_trials"],
            "success_percent": 100.0 * p,
            "best_energy_overall": s["best_energy_overall"],
            "median_time_s": s["median_total_time_s"],
            "expected_tts_including_failures_s":
                s["time_to_valid_including_failures_s"],
            "tts99_s": t99,
            "tts99_note": t99_note + " (PRELIMINARY: only 5 trials)",
            "preliminary_small_sample": True,
        })
    return out


def make_comparison_charts(
    sa: dict, classical: dict, qaoa: list[dict], out_path: Path
) -> None:
    labels, succ, tts, colors = [], [], [], []
    entries = (
        [("backtracking", 100.0,
          classical["median_time_s"], "tab:green"),
         (f"simulated\nannealing\n(n={sa['n_runs']})",
          sa["success_percent"],
          sa["expected_tts_including_failures_s"], "tab:olive")]
        + [(f"QAOA p={q['method'][-1]}\n(simulator,\nn=5, prelim.)",
            q["success_percent"],
            q["expected_tts_including_failures_s"], "tab:blue")
           for q in qaoa]
    )
    for label, s, t, c in entries:
        labels.append(label)
        succ.append(s)
        tts.append(t)
        colors.append(c)

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle(
        "Three solver families, same verified 18-variable scheduling QUBO\n"
        "(green/olive: classical CPU; blue: noiseless Aer SIMULATOR - "
        "no quantum hardware used; QAOA n=5 is preliminary)"
    )

    ax = axes[0]
    ax.bar(labels, succ, color=colors)
    ax.set_ylabel("successful runs/trials (%)")
    ax.set_title("Success probability per complete run/trial")
    ax.tick_params(axis="x", labelsize=8)

    ax = axes[1]
    ax.bar(labels, tts, color=colors)
    ax.set_yscale("log")
    ax.set_ylabel("expected time-to-solution incl. failures (s, log)")
    ax.set_title("Expected time to one valid schedule")
    ax.tick_params(axis="x", labelsize=8)
    for i, t in enumerate(tts):
        ax.text(i, t, f"{t:.2g}s", ha="center", va="bottom", fontsize=8)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main() -> None:
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)

    print("=== Phase 2F: simulated annealing benchmark ===\n")
    print(f"SA settings: max_iterations={DEFAULT_MAX_ITERATIONS}, "
          f"T0={DEFAULT_INITIAL_TEMPERATURE}, "
          f"cooling_rate={DEFAULT_COOLING_RATE}\n")

    # --- Pilot ---
    print(f"Pilot: {len(PILOT_SEEDS)} runs...")
    pilot_start = time.perf_counter()
    pilot_runs = [run_simulated_annealing(seed=s) for s in PILOT_SEEDS]
    pilot_time = time.perf_counter() - pilot_start
    pilot_succ = sum(r["found_valid_solution"] for r in pilot_runs)
    est_main = pilot_time / len(PILOT_SEEDS) * len(MAIN_SEEDS)
    print(f"  pilot: {pilot_succ}/{len(PILOT_SEEDS)} successful, "
          f"{pilot_time:.2f} s total")
    print(f"  estimated main experiment ({len(MAIN_SEEDS)} runs): "
          f"~{est_main:.1f} s (budget {PILOT_BUDGET_SECONDS} s)\n")
    if est_main > PILOT_BUDGET_SECONDS:
        print("STOP: estimated cost exceeds budget.")
        return

    # --- Main experiment: 30 independent runs ---
    print(f"Main experiment: {len(MAIN_SEEDS)} independent runs "
          f"(seeds {MAIN_SEEDS[0]}..{MAIN_SEEDS[-1]})...")
    runs = [run_simulated_annealing(seed=s) for s in MAIN_SEEDS]
    sa_summary = summarize_sa(runs)
    print(f"  successful runs: {sa_summary['successful_runs']}"
          f"/{sa_summary['n_runs']} ({sa_summary['success_percent']:.1f}%)")
    print(f"  validator confirmed all successes: "
          f"{sa_summary['all_successes_validator_confirmed']}")
    print(f"  median time: {sa_summary['median_time_s']*1000:.2f} ms  "
          f"(min {sa_summary['min_time_s']*1000:.2f}, "
          f"max {sa_summary['max_time_s']*1000:.2f}, "
          f"stdev {sa_summary['stdev_time_s']*1000:.2f} ms)")
    print(f"  median energy evaluations: "
          f"{sa_summary['median_energy_evaluations']:.0f}\n")

    # --- Classical backtracking baseline (fresh measurement) ---
    print(f"Classical backtracking baseline ({CLASSICAL_REPEATS} repeats)...")
    classical = run_classical_baseline(CLASSICAL_REPEATS)
    print(f"  median {classical['median_time_s']*1e6:.1f} us, all valid: "
          f"{classical['all_runs_found_valid_zero_energy_solution']}\n")

    # --- Stored QAOA results (not rerun) ---
    qaoa = load_qaoa_summaries(results_dir)

    # --- Report table ---
    print("=== Comparison (same 18-variable QUBO, same validator) ===")
    print("NOTE: QAOA rows are PRELIMINARY (5 trials each vs 30 SA runs);")
    print("      a QAOA 'trial' and an SA 'run' are different budgets.\n")
    header = (f"{'method':<22}{'env':<11}{'runs':<7}{'success %':<11}"
              f"{'best E':<8}{'median time':<14}{'expected TTS':<14}"
              f"{'TTS99':<12}")
    print(header)
    print("-" * len(header))
    print(f"{'backtracking':<22}{'classical':<11}"
          f"{CLASSICAL_REPEATS:<7}{'100.0':<11}{'0':<8}"
          f"{classical['median_time_s']:<14.6f}"
          f"{classical['median_time_s']:<14.6f}{'~same':<12}")
    t99 = sa_summary["tts99_s"]
    print(f"{'simulated annealing':<22}{'classical':<11}"
          f"{sa_summary['n_runs']:<7}"
          f"{sa_summary['success_percent']:<11.1f}"
          f"{sa_summary['best_energy_overall']:<8}"
          f"{sa_summary['median_time_s']:<14.6f}"
          f"{sa_summary['expected_tts_including_failures_s']:<14.6f}"
          f"{(f'{t99:.4f}' if t99 is not None else 'n/a'):<12}")
    for q in qaoa:
        t99q = q["tts99_s"]
        print(f"{q['method'] + ' (prelim.)':<22}{'simulator':<11}"
              f"{q['n_runs']:<7}{q['success_percent']:<11.1f}"
              f"{q['best_energy_overall']:<8}{q['median_time_s']:<14.2f}"
              f"{q['expected_tts_including_failures_s']:<14.2f}"
              f"{(f'{t99q:.1f}' if t99q is not None else 'n/a'):<12}")

    # --- Charts and raw data (new files only) ---
    chart_path = results_dir / "solver_comparison_charts.png"
    make_comparison_charts(sa_summary, classical, qaoa, chart_path)
    print(f"\nCharts saved to {chart_path}")

    record = {
        "experiment": "phase2f_simulated_annealing_benchmark",
        "pilot": {"seeds": PILOT_SEEDS, "runs": pilot_runs,
                  "total_time_s": pilot_time},
        "sa_runs": runs,
        "sa_summary": sa_summary,
        "classical_baseline": classical,
        "qaoa_summaries_from_phase2c_not_rerun": qaoa,
        "fairness_notes": [
            "QAOA numbers are the stored Phase 2C five-seed measurements; "
            "they were not rerun. Sample sizes differ (30 vs 5): QAOA "
            "comparisons are preliminary.",
            "Success units differ: an SA 'run' ends at the first valid "
            "solution or 50,000 iterations; a QAOA 'trial' includes a "
            "24-40 objective-evaluation optimization (measured range in "
            "Phase 2C; 1,000 shots each) plus 4,000 "
            "final shots. Equal counts are not equal computational effort.",
            "All SA and backtracking times are classical CPU; all QAOA "
            "times are noiseless-simulator times, not hardware times.",
            "TTS99 assumes independent repeated attempts with the measured "
            "per-run success fraction; that fraction carries binomial "
            "uncertainty from finite samples.",
        ],
    }
    data_path = results_dir / "sa_benchmark_results.json"
    data_path.write_text(json.dumps(record, indent=2))
    print(f"Raw data saved to {data_path}")


if __name__ == "__main__":
    main()
