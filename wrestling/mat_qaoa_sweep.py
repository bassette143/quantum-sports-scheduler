"""Phase W5C: reproducibility sweep for wrestling QAOA (p=1 and p=2).

Five fixed seeds per depth on the UNCHANGED 14-variable W4 QUBO, with the
committed run_qaoa() exactly as used for the seed-42 runs: same penalties,
COBYLA settings (maxiter 40, rhobeg 0.5), shot counts (1,000 per
evaluation, 4,000 final), initial-point design (uniform [0, 0.5) from the
seed) and |+>^n initial state.

Terminology kept distinct throughout:
  * optimizer objective  - mean QUBO energy of the 1,000-shot sample at a
                           parameter point, as seen by COBYLA. With a fixed
                           sampler seed, the same parameters always return
                           the same 1,000 shots, so the minimum over the run
                           is biased low by favorable sampling noise.
  * final-sample energy  - mean QUBO energy of the separate 4,000-shot
                           sample drawn at the returned parameters (a
                           different random stream; checked empirically).

"Excessive violation" (fixed before the sweep): a sample whose penalty
part (energy + progression score) is >= 16 * A = 208, i.e. the selection
size is off by 4 or more from k = 6, or an equivalent combination of
violations. Its exact uniform-random probability is computed over all
16,384 assignments.

Run:  python -m wrestling.mat_qaoa_sweep
"""

import json
import math
import statistics
import time
from pathlib import Path

import numpy as np
from scipy import stats

from wrestling.mat_qaoa import (
    MAIN,
    PILOT_BUDGET_SECONDS,
    bitstring_to_selection,
    classical_reference,
    run_qaoa,
)
from wrestling.mat_qubo import (
    build_qubo_instance,
    classical_brute_force,
    extract_snapshot,
    is_feasible,
    qubo_energy,
    selection_score,
)
from wrestling.rosters import DEFAULT_SEED

SEEDS = [11, 22, 33, 44, 55]
DEPTHS = [1, 2]
EXCESSIVE_PENALTY_MULTIPLE = 16  # penalty >= 16 * A counts as excessive
OUT = Path(__file__).parent.parent / "results" / "wrestling_qaoa_sweep_results.json"
T95 = {4: 2.776}  # two-sided 95% Student t, df = n - 1 = 4


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def penalty_part(x: int, inst: dict) -> int:
    """Constraint-penalty share of the energy (energy + progression score)."""
    return qubo_energy(x, inst) + selection_score(x, inst)


def sample_metrics(counts: dict[str, int], inst: dict, threshold: int) -> dict:
    """Extra per-run statistics computed from the final 4,000 shots."""
    n_bits = len(inst["pool"])
    shots = sum(counts.values())
    energy_sum = excess_energy_sum = 0.0
    excessive = 0
    cardinality = [0] * (n_bits + 1)
    for bs, c in counts.items():
        x = bitstring_to_selection(bs)
        e = qubo_energy(x, inst)
        energy_sum += e * c
        cardinality[bin(x).count("1")] += c
        if penalty_part(x, inst) >= threshold:
            excessive += c
            excess_energy_sum += e * c
    non_excess = shots - excessive
    return {
        "final_sample_mean_energy": energy_sum / shots,
        "excessive_shots": excessive,
        "excessive_percent": 100.0 * excessive / shots,
        "mean_energy_without_excessive": (
            (energy_sum - excess_energy_sum) / non_excess if non_excess else None
        ),
        "share_of_energy_sum_from_excessive": (
            excess_energy_sum / energy_sum if energy_sum > 0 else None
        ),
        "cardinality_distribution": cardinality,
    }


def trial(inst, snapshot, optimal, depth, seed, threshold) -> dict:
    run = run_qaoa(inst, snapshot, optimal, seed=seed,
                   **{**MAIN, "reps": depth})
    a = run["analysis"]
    hist = run["mean_energy_history"]
    return {
        "depth": depth,
        "seed": seed,
        "objective_initial": hist[0],
        "objective_final_evaluation": hist[-1],
        "objective_best": min(hist),
        **sample_metrics(run["final_counts"], inst, threshold),
        "feasible_percent": a["feasible_percent"],
        "optimal_percent": a["optimal_percent"],
        "feasible_shots": a["feasible_shots"],
        "optimal_shots": a["optimal_shots"],
        "found_optimum": a["optimal_shots"] > 0,
        "best_feasible_score": a["best_feasible_score"],
        "best_qubo_energy": a["best_energy"],
        "optimizer_evaluations": run["optimizer_evaluations"],
        "hit_evaluation_cap": run["optimizer_evaluations"] >= MAIN["maxiter"],
        "circuit_depth": run["circuit_depth"],
        "two_qubit_gates": run["two_qubit_gates"],
        "runtime_s": run["timings_seconds"]["quantum_pipeline_total"],
        "validation": a["validation"],
        "optimal_parameters": run["optimal_parameters"],
        "objective_history": hist,
        "final_counts": run["final_counts"],
    }


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def mean_sd_ci(values: list[float]) -> dict:
    n = len(values)
    m = statistics.mean(values)
    sd = statistics.stdev(values) if n > 1 else 0.0
    half = T95[n - 1] * sd / math.sqrt(n) if n - 1 in T95 else None
    return {"mean": m, "sd": sd, "ci95_t": [m - half, m + half] if half is not None else None,
            "min": min(values), "max": max(values)}


def t_ci95(values: list[float]) -> dict:
    """Two-sided 95% Student-t interval with the exact df = n - 1.

    Added in Phase W5D: mean_sd_ci() only had the df=4 table value, so the
    n=10 optimizer-gap interval was stored as null in the W5C file. This
    function does not replace mean_sd_ci(), so the saved W5C summaries still
    recompute exactly."""
    n = len(values)
    if n < 2:
        raise ValueError("need at least 2 values")
    m = statistics.mean(values)
    sd = statistics.stdev(values)
    t = float(stats.t.ppf(0.975, n - 1))
    half = t * sd / math.sqrt(n)
    return {"n": n, "df": n - 1, "t_critical": t, "mean": m, "sd": sd,
            "ci95_t": [m - half, m + half]}


def gap_ci95_corrected(trials: list[dict]) -> dict:
    """Corrected CI for (final-sample energy - optimizer best objective),
    computed purely from saved trial records."""
    gaps = [t["final_sample_mean_energy"] - t["objective_best"] for t in trials]
    out = t_ci95(gaps)
    out["all_gaps_positive"] = all(g > 0 for g in gaps)
    out["sign_test_p_two_sided"] = (
        2 * 0.5 ** len(gaps) if out["all_gaps_positive"] else None)
    return out


CI_CORRECTION_OUT = OUT.with_name("wrestling_qaoa_sweep_ci_correction.json")


def write_ci_correction(sweep_path: Path = OUT,
                        out_path: Path = CI_CORRECTION_OUT) -> dict:
    """Write the corrected interval to a SIDECAR file; the original sweep
    JSON is only read, never modified. Refuses to overwrite."""
    if out_path.exists():
        raise SystemExit(f"{out_path.name} already exists; refusing to overwrite.")
    record = json.loads(sweep_path.read_text())
    corrected = gap_ci95_corrected(record["trials"])
    sidecar = {
        "correction_for": sweep_path.name,
        "field": "analysis.final_minus_optimizer_best_objective.ci95_t",
        "stored_value": record["analysis"]
        ["final_minus_optimizer_best_objective"]["ci95_t"],
        "reason": "df=9 t value was missing from the T95 table; computed "
                  "with scipy.stats.t.ppf(0.975, n-1) from the saved trials. "
                  "No experiment was rerun.",
        "corrected": corrected,
    }
    out_path.write_text(json.dumps(sidecar, indent=2))
    return sidecar


def clopper_pearson(k: int, n: int, level: float = 0.95) -> list[float]:
    alpha = 1 - level
    lo = 0.0 if k == 0 else stats.beta.ppf(alpha / 2, k, n - k + 1)
    hi = 1.0 if k == n else stats.beta.ppf(1 - alpha / 2, k + 1, n - k)
    return [float(lo), float(hi)]


def summarize_depth(trials: list[dict]) -> dict:
    keys = ["feasible_percent", "optimal_percent", "final_sample_mean_energy",
            "objective_best", "objective_initial", "excessive_percent",
            "best_feasible_score", "optimizer_evaluations", "runtime_s"]
    found = sum(t["found_optimum"] for t in trials)
    return {
        "depth": trials[0]["depth"],
        "n": len(trials),
        **{k: mean_sd_ci([float(t[k]) for t in trials]) for k in keys},
        "runs_finding_optimum": found,
        "runs_finding_optimum_ci95_clopper_pearson": clopper_pearson(found, len(trials)),
        "runs_hitting_evaluation_cap": sum(t["hit_evaluation_cap"] for t in trials),
        "circuit_depth": trials[0]["circuit_depth"],
        "two_qubit_gates": trials[0]["two_qubit_gates"],
        "all_feasible_validator_confirmed": all(
            t["validation"]["all_feasible_samples_validator_confirmed"] for t in trials),
        "distinct_feasible_validated": sum(
            t["validation"]["distinct_feasible_checked"] for t in trials),
    }


def analysis(trials: list[dict]) -> dict:
    p1 = [t for t in trials if t["depth"] == 1]
    p2 = [t for t in trials if t["depth"] == 2]
    sp = lambda a, b: stats.spearmanr(a, b)  # noqa: E731
    e = [t["final_sample_mean_energy"] for t in trials]
    f = [t["feasible_percent"] for t in trials]
    rho_ef = sp(e, f)
    rho_obj = sp([t["objective_best"] for t in trials], e)
    mw = stats.mannwhitneyu([t["feasible_percent"] for t in p2],
                            [t["feasible_percent"] for t in p1],
                            alternative="two-sided", method="exact")
    by_seed = {t["seed"]: t for t in p1}
    p2_better = sum(t["feasible_percent"] > by_seed[t["seed"]]["feasible_percent"]
                    for t in p2)
    gap = [t["final_sample_mean_energy"] - t["objective_best"] for t in trials]
    return {
        "spearman_final_energy_vs_feasible_all_runs": {
            "rho": float(rho_ef.statistic), "p_value": float(rho_ef.pvalue), "n": len(trials)},
        "spearman_optimizer_best_objective_vs_final_sample_energy": {
            "rho": float(rho_obj.statistic), "p_value": float(rho_obj.pvalue), "n": len(trials)},
        "final_minus_optimizer_best_objective": mean_sd_ci(gap),
        "mann_whitney_feasible_p2_vs_p1": {
            "U": float(mw.statistic), "p_value_two_sided_exact": float(mw.pvalue)},
        "paired_seeds_where_p2_feasible_exceeds_p1": p2_better,
    }


# ---------------------------------------------------------------------------
# Main protocol
# ---------------------------------------------------------------------------

def main(seed: int = DEFAULT_SEED) -> None:
    if OUT.exists():
        raise SystemExit(f"{OUT.name} already exists; refusing to overwrite.")
    snapshot = extract_snapshot(seed)
    inst = build_qubo_instance(snapshot)
    n = len(inst["pool"])
    optimal = classical_brute_force(inst)["best_score"]
    threshold = EXCESSIVE_PENALTY_MULTIPLE * inst["penalty_A"]

    # Exact uniform-random reference values.
    N = 2 ** n
    n_feas = sum(1 for x in range(N) if is_feasible(x, inst))
    n_opt = sum(1 for x in range(N)
                if is_feasible(x, inst) and selection_score(x, inst) == optimal)
    n_exc = sum(1 for x in range(N) if penalty_part(x, inst) >= threshold)
    mean_E = sum(qubo_energy(x, inst) for x in range(N)) / N
    p_opt, shots = n_opt / N, MAIN["final_shots"]
    lam = shots * p_opt
    random_ref = {
        "feasible_percent": 100 * n_feas / N,
        "optimal_percent": 100 * p_opt,
        "excessive_percent": 100 * n_exc / N,
        "mean_energy": mean_E,
        "p_optimum_at_least_once_in_4000": 1 - (1 - p_opt) ** shots,
        "p_optimum_three_or_more_in_4000": float(stats.binom.sf(2, shots, p_opt)),
        "expected_optimal_hits_in_4000": lam,
    }
    classical = classical_reference(inst)

    print("=== Phase W5C: wrestling QAOA reproducibility sweep ===")
    print(f"Seeds {SEEDS} x depths {DEPTHS}; settings {MAIN}")
    print(f"Excessive-violation threshold: penalty >= {threshold}")
    print(f"Random exact: feasible {random_ref['feasible_percent']:.3f}%, "
          f"optimal {random_ref['optimal_percent']:.4f}%, excessive "
          f"{random_ref['excessive_percent']:.2f}%, mean E {mean_E:.2f}")

    # --- Pilot: the most expensive configuration, reused in the sweep ---
    print(f"\nPilot: p=2, seed {SEEDS[0]} (full settings)...")
    t0 = time.perf_counter()
    pilot = trial(inst, snapshot, optimal, 2, SEEDS[0], threshold)
    pilot_t = time.perf_counter() - t0
    est = pilot_t * len(SEEDS) * len(DEPTHS)  # conservative: p=1 is cheaper
    print(f"  pilot {pilot_t:.2f} s incl. validation -> sweep estimate "
          f"<= ~{est:.0f} s (budget {PILOT_BUDGET_SECONDS} s)")
    if est > PILOT_BUDGET_SECONDS:
        print("STOP: estimate exceeds budget.")
        return

    trials = []
    for depth in DEPTHS:
        for s in SEEDS:
            t = pilot if (depth == 2 and s == SEEDS[0]) else trial(
                inst, snapshot, optimal, depth, s, threshold)
            trials.append(t)
            print(f"  p={depth} seed={s}: feasible {t['feasible_percent']:6.2f}%  "
                  f"opt {t['optimal_shots']}  best {t['best_feasible_score']}  "
                  f"objBest {t['objective_best']:7.2f}  finalE "
                  f"{t['final_sample_mean_energy']:7.2f}  exc "
                  f"{t['excessive_percent']:5.2f}%  evals {t['optimizer_evaluations']}  "
                  f"{t['runtime_s']:.2f} s")

    summaries = [summarize_depth([t for t in trials if t["depth"] == d])
                 for d in DEPTHS]
    an = analysis(trials)
    record = {
        "experiment": "wrestling_qaoa_phase_w5c_reproducibility_sweep",
        "settings": {**MAIN, "seeds": SEEDS, "depths": DEPTHS,
                     "excessive_threshold_penalty": threshold,
                     "instance_seed": seed, "snapshot_slot": snapshot["slot"],
                     "penalty_A": inst["penalty_A"], "penalty_B": inst["penalty_B"],
                     "objective_C": inst["objective_C"], "k": inst["k"]},
        "uniform_random_exact": random_ref,
        "classical_reference": classical,
        "pilot_seconds_including_validation": pilot_t,
        "summaries": summaries,
        "analysis": an,
        "trials": trials,
        "notes": [
            "Five seeds per depth: small sample; intervals are wide.",
            "objective_* values are 1,000-shot estimates seen by COBYLA "
            "(deterministic per parameter point under the fixed sampler "
            "seed); final_sample_mean_energy uses the separate 4,000-shot "
            "sample.",
            "Seed-42 runs are stored separately and not included here.",
            "Noiseless Aer simulator; no hardware; no penalty changes.",
        ],
    }
    OUT.write_text(json.dumps(record, indent=2))
    print(f"\nSaved {OUT}")


if __name__ == "__main__":
    import sys

    if "--ci-correction" in sys.argv:
        print(json.dumps(write_ci_correction(), indent=2))
    else:
        main()
