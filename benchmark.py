"""Phase 2C: controlled QAOA benchmarking against classical baselines.

Research question: does increasing QAOA depth (p = 1, 2, 3) improve
solution quality, success probability, or time-to-valid-solution on the
verified 18-variable scheduling QUBO?

Protocol
--------
* Pilot first: one p=2 trial is run and timed; the full sweep cost is
  estimated from it and the sweep is aborted if the estimate is excessive.
* 5 fixed seeds per depth; identical optimizer settings and shot counts
  for every configuration (COBYLA maxiter=40, 1000 optimization shots per
  evaluation, 4000 final evaluation shots).
* Baseline 1: classical backtracking on the SAME simplified problem,
  repeated many times for timing variability.
* Baseline 2: uniformly random 18-bit strings, same number of "shots" as
  one final QAOA evaluation, per seed.
* Every valid candidate is re-checked through the independent Phase 1
  validator (inside analyze_counts).
* All numbers reported are measured. Nothing is estimated or invented.

Run:  python benchmark.py
"""

import json
import statistics
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no GUI needed; we only save files
import matplotlib.pyplot as plt
import numpy as np

from quantum_scheduler import analyze_counts, run_qaoa_experiment
from qubo_formulation import (
    N_ASSIGNMENTS,
    N_VARS,
    TEAMS,
    energy,
    generate_single_rr_backtracking,
    single_rr_to_assignment,
)

DEPTHS = [1, 2, 3]
SEEDS = [11, 22, 33, 44, 55]
OPT_SHOTS = 1000
FINAL_SHOTS = 4000
MAXITER = 40
CLASSICAL_REPEATS = 200
PILOT_BUDGET_SECONDS = 600  # abort the sweep if the estimate exceeds this

RANDOM_VALID_PROBABILITY = 6 / N_ASSIGNMENTS  # exact: 6 ground states


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------

def run_classical_baseline(repeats: int = CLASSICAL_REPEATS) -> dict:
    """Backtracking on the SAME 18-variable single round-robin problem.

    Success is confirmed per repeat by scoring the solution with the
    verified QUBO energy function (must be 0).
    """
    times: list[float] = []
    all_valid = True
    for _ in range(repeats):
        schedule, elapsed = generate_single_rr_backtracking(TEAMS)
        times.append(elapsed)
        if schedule is None or energy(single_rr_to_assignment(schedule)) != 0:
            all_valid = False
    return {
        "method": "classical_backtracking",
        "same_problem_as_qubo": True,
        "repeats": repeats,
        "all_runs_found_valid_zero_energy_solution": all_valid,
        "median_time_s": statistics.median(times),
        "mean_time_s": statistics.mean(times),
        "stdev_time_s": statistics.stdev(times),
        "min_time_s": min(times),
        "max_time_s": max(times),
    }


def run_random_baseline(seed: int, shots: int = FINAL_SHOTS) -> dict:
    """Uniformly random bitstrings, scored identically to QAOA samples."""
    rng = np.random.default_rng(seed)
    start = time.perf_counter()
    assignments = rng.integers(0, N_ASSIGNMENTS, size=shots)
    counts: dict[str, int] = {}
    for a in assignments:
        bs = format(int(a), f"0{N_VARS}b")
        counts[bs] = counts.get(bs, 0) + 1
    analysis = analyze_counts(counts)
    elapsed = time.perf_counter() - start
    return {
        "method": "uniform_random",
        "seed": seed,
        "shots": shots,
        "best_energy": analysis["best_energy"],
        "valid_shots": analysis["valid_shots"],
        "valid_percent": analysis["valid_percent"],
        "time_s": elapsed,
    }


# ---------------------------------------------------------------------------
# QAOA sweep
# ---------------------------------------------------------------------------

def run_qaoa_trial(depth: int, seed: int) -> dict:
    """One QAOA trial with the shared Phase 2C settings."""
    result = run_qaoa_experiment(
        reps=depth,
        opt_shots=OPT_SHOTS,
        final_shots=FINAL_SHOTS,
        maxiter=MAXITER,
        seed=seed,
    )
    a = result["analysis_of_final_samples"]
    return {
        "depth": depth,
        "seed": seed,
        "optimizer_iterations": result["optimizer_iterations"],
        "initial_mean_energy": result["initial_mean_energy"],
        "final_mean_energy": result["final_mean_energy"],
        "best_energy": a["best_energy"],
        "valid_shots": a["valid_shots"],
        "valid_percent": a["valid_percent"],
        "n_distinct_valid_schedules": a["n_distinct_valid_schedules"],
        "validator_confirmed": a["mirrored_schedules_pass_phase1_validator"],
        "circuit_depth": result["circuit_depth"],
        "two_qubit_gates": result["two_qubit_gates"],
        "total_gates": result["total_gates"],
        "total_time_s": result["timings_seconds"]["total_experiment"],
        "sampling_time_s": result["timings_seconds"]["circuit_sampling_only"],
    }


def aggregate_depth(trials: list[dict]) -> dict:
    """Summarize all trials of one depth. Only measured values are used."""
    times = [t["total_time_s"] for t in trials]
    valid_pcts = [t["valid_percent"] for t in trials]
    successes = [t for t in trials if t["valid_shots"] > 0]
    total_time = sum(times)
    # Time-to-valid-solution including unsuccessful attempts: total wall
    # time spent across ALL trials divided by the number of trials that
    # produced at least one valid schedule. Undefined if none succeeded.
    tts = total_time / len(successes) if successes else None
    return {
        "depth": trials[0]["depth"],
        "n_trials": len(trials),
        "optimizer_iterations": [t["optimizer_iterations"] for t in trials],
        "successful_trials": len(successes),
        "mean_valid_percent": statistics.mean(valid_pcts),
        "stdev_valid_percent": (
            statistics.stdev(valid_pcts) if len(valid_pcts) > 1 else 0.0
        ),
        "valid_percent_per_seed": valid_pcts,
        "best_energy_overall": min(t["best_energy"] for t in trials),
        "median_total_time_s": statistics.median(times),
        "min_total_time_s": min(times),
        "max_total_time_s": max(times),
        "total_time_all_trials_s": total_time,
        "time_to_valid_including_failures_s": tts,
        "circuit_depth": trials[0]["circuit_depth"],
        "two_qubit_gates": trials[0]["two_qubit_gates"],
        "all_validator_confirmed": all(t["validator_confirmed"] for t in trials),
    }


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def make_charts(
    summaries: list[dict],
    trials: list[dict],
    classical: dict,
    random_runs: list[dict],
    out_path: Path,
) -> None:
    depths = [s["depth"] for s in summaries]
    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    fig.suptitle(
        "QAOA vs classical: 4-team round-robin scheduling (18 qubits, "
        "Aer simulator, 5 seeds per depth)"
    )

    # (1) Valid-sample rate per depth, with random baseline.
    ax = axes[0][0]
    for t in trials:
        ax.scatter(t["depth"], t["valid_percent"], color="tab:blue", alpha=0.5)
    ax.plot(
        depths,
        [s["mean_valid_percent"] for s in summaries],
        "o-",
        color="tab:blue",
        label="QAOA mean (dots: seeds)",
    )
    random_mean = statistics.mean(r["valid_percent"] for r in random_runs)
    ax.axhline(
        random_mean,
        color="tab:red",
        linestyle="--",
        label=f"random sampling, measured mean ({random_mean:.4f}%)",
    )
    ax.axhline(
        100 * RANDOM_VALID_PROBABILITY,
        color="tab:gray",
        linestyle=":",
        label="random, exact probability (0.0023%)",
    )
    ax.set_xlabel("QAOA depth p")
    ax.set_ylabel("valid samples in final 4000 shots (%)")
    ax.set_title("Validity rate")
    ax.set_xticks(depths)
    ax.legend(fontsize=8)

    # (2) Runtime per depth vs classical baseline.
    ax = axes[0][1]
    for t in trials:
        ax.scatter(t["depth"], t["total_time_s"], color="tab:blue", alpha=0.5)
    ax.plot(
        depths,
        [s["median_total_time_s"] for s in summaries],
        "o-",
        color="tab:blue",
        label="QAOA median total runtime",
    )
    ax.axhline(
        classical["median_time_s"],
        color="tab:green",
        linestyle="--",
        label=f"classical backtracking median "
        f"({classical['median_time_s']*1e6:.0f} us)",
    )
    ax.set_yscale("log")
    ax.set_xlabel("QAOA depth p")
    ax.set_ylabel("end-to-end runtime (s, log scale)")
    ax.set_title("Measured runtime")
    ax.set_xticks(depths)
    ax.legend(fontsize=8)

    # (3) Circuit complexity per depth.
    ax = axes[1][0]
    width = 0.35
    x = np.arange(len(depths))
    ax.bar(
        x - width / 2,
        [s["circuit_depth"] for s in summaries],
        width,
        label="transpiled circuit depth",
        color="tab:purple",
    )
    ax.bar(
        x + width / 2,
        [s["two_qubit_gates"] for s in summaries],
        width,
        label="two-qubit (CX) gates",
        color="tab:orange",
    )
    ax.set_xticks(x)
    ax.set_xticklabels([f"p={d}" for d in depths])
    ax.set_ylabel("count")
    ax.set_title("Circuit complexity (basis: cx, rz, rx, h)")
    ax.legend(fontsize=8)

    # (4) Successful trials per depth.
    ax = axes[1][1]
    ax.bar(
        [f"p={d}" for d in depths],
        [s["successful_trials"] for s in summaries],
        color="tab:blue",
    )
    ax.axhline(
        len(SEEDS), color="tab:green", linestyle="--", label="classical (always)"
    )
    ax.set_ylim(0, len(SEEDS) + 0.5)
    ax.set_ylabel(f"trials with >= 1 valid schedule (of {len(SEEDS)})")
    ax.set_title("Success probability")
    ax.legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main protocol
# ---------------------------------------------------------------------------

def main() -> None:
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)

    print("=== Phase 2C: controlled QAOA benchmarking ===\n")

    # --- Pilot: one p=2 trial to estimate sweep cost ---
    print("Pilot run (p=2, one seed) to estimate sweep cost...")
    pilot = run_qaoa_trial(depth=2, seed=SEEDS[0])
    pilot_time = pilot["total_time_s"]
    # Sampling cost grows roughly linearly with depth; estimate per depth
    # relative to the p=2 pilot and multiply by seeds.
    est_total = sum(pilot_time * (d / 2) * len(SEEDS) for d in DEPTHS)
    print(f"Pilot time: {pilot_time:.2f} s")
    print(f"Estimated full sweep: ~{est_total:.0f} s "
          f"(budget {PILOT_BUDGET_SECONDS} s)\n")
    if est_total > PILOT_BUDGET_SECONDS:
        print("STOP: estimated cost exceeds budget. Not running the sweep.")
        return

    # --- Full sweep (pilot trial is reused for its configuration) ---
    trials: list[dict] = []
    for depth in DEPTHS:
        for seed in SEEDS:
            if depth == pilot["depth"] and seed == pilot["seed"]:
                trials.append(pilot)
                continue
            trial = run_qaoa_trial(depth, seed)
            trials.append(trial)
            print(
                f"  p={depth} seed={seed}: valid {trial['valid_percent']:.3f}% "
                f"({trial['valid_shots']}/{FINAL_SHOTS}), "
                f"best energy {trial['best_energy']}, "
                f"{trial['total_time_s']:.2f} s"
            )

    summaries = [
        aggregate_depth([t for t in trials if t["depth"] == d]) for d in DEPTHS
    ]

    # --- Baselines ---
    print("\nClassical backtracking baseline "
          f"({CLASSICAL_REPEATS} repeats, same problem)...")
    classical = run_classical_baseline()
    print(
        f"  median {classical['median_time_s']*1e6:.1f} us, "
        f"all valid: {classical['all_runs_found_valid_zero_energy_solution']}"
    )

    print("Uniform random baseline (one per seed)...")
    random_runs = [run_random_baseline(seed) for seed in SEEDS]
    for r in random_runs:
        print(
            f"  seed={r['seed']}: valid {r['valid_percent']:.4f}% "
            f"({r['valid_shots']}/{r['shots']}), best energy {r['best_energy']}"
        )

    # --- Report table ---
    print("\n=== Comparison table (all values measured) ===")
    header = (
        f"{'config':<16}{'opt evals':<11}{'final shots':<13}"
        f"{'mean valid %':<14}{'success':<9}{'best E':<8}"
        f"{'median time':<13}{'depth':<7}{'2q gates':<9}"
    )
    print(header)
    print("-" * len(header))
    for s in summaries:
        iters = f"{min(s['optimizer_iterations'])}-{max(s['optimizer_iterations'])}"
        print(
            f"{'QAOA p=' + str(s['depth']):<16}{iters:<11}{FINAL_SHOTS:<13}"
            f"{s['mean_valid_percent']:<14.3f}"
            f"{str(s['successful_trials']) + '/' + str(s['n_trials']):<9}"
            f"{s['best_energy_overall']:<8}"
            f"{s['median_total_time_s']:<13.2f}{s['circuit_depth']:<7}"
            f"{s['two_qubit_gates']:<9}"
        )
    rand_mean = statistics.mean(r["valid_percent"] for r in random_runs)
    rand_best = min(r["best_energy"] for r in random_runs)
    rand_success = sum(1 for r in random_runs if r["valid_shots"] > 0)
    rand_median_t = statistics.median(r["time_s"] for r in random_runs)
    print(
        f"{'random':<16}{'-':<11}{FINAL_SHOTS:<13}{rand_mean:<14.4f}"
        f"{str(rand_success) + '/' + str(len(random_runs)):<9}{rand_best:<8}"
        f"{rand_median_t:<13.4f}{'-':<7}{'-':<9}"
    )
    print(
        f"{'classical':<16}{'-':<11}{'-':<13}{'100.000':<14}"
        f"{str(CLASSICAL_REPEATS) + '/' + str(CLASSICAL_REPEATS):<9}{'0':<8}"
        f"{classical['median_time_s']:<13.6f}{'-':<7}{'-':<9}"
    )

    print("\nTime-to-valid-solution (total time across trials / successful trials):")
    for s in summaries:
        tts = s["time_to_valid_including_failures_s"]
        print(
            f"  QAOA p={s['depth']}: "
            + (f"{tts:.2f} s" if tts is not None else "not achieved")
        )
    print(f"  classical: {classical['median_time_s']:.6f} s (every run succeeds)")

    # --- Charts and raw data ---
    chart_path = results_dir / "benchmark_charts.png"
    make_charts(summaries, trials, classical, random_runs, chart_path)
    print(f"\nCharts saved to {chart_path}")

    record = {
        "experiment": "phase2c_qaoa_depth_sweep",
        "settings": {
            "depths": DEPTHS,
            "seeds": SEEDS,
            "opt_shots": OPT_SHOTS,
            "final_shots": FINAL_SHOTS,
            "maxiter": MAXITER,
            "optimizer": "COBYLA",
            "backend": "qiskit-aer SamplerV2 (local simulator)",
        },
        "pilot": pilot,
        "trials": trials,
        "summaries": summaries,
        "classical_baseline": classical,
        "random_baseline_runs": random_runs,
        "limitations": [
            "Only 5 seeds per depth: small sample, high variance in rates.",
            "Simulator runtimes include Python/Aer overhead and do not "
            "model real-hardware noise, latency, or queueing.",
            "COBYLA budget (maxiter=40) is identical across depths; deeper "
            "circuits have more parameters and may be under-optimized.",
            "Greater depth can perform worse: more parameters and a longer "
            "circuit make the optimization landscape harder.",
            "The 4-team problem is an educational example; classical "
            "backtracking solves it in microseconds.",
        ],
    }
    data_path = results_dir / "benchmark_results.json"
    data_path.write_text(json.dumps(record, indent=2))
    print(f"Raw data saved to {data_path}")


if __name__ == "__main__":
    main()
