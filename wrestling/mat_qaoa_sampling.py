"""Phase W5D: does reusing fixed sampling randomness inflate the optimizer gap?

Two sampling strategies, compared on MATCHED initializations (same trial
seed -> same initial parameters), everything else identical: 14-variable
W4 QUBO, p = 1, penalties A = B = 13, C = 1, mean-QUBO-energy objective,
COBYLA (maxiter 40, rhobeg 0.5), 1,000 shots per evaluation, 4,000 final.

  A  "fixed":       one SamplerV2(seed=trial_seed) reused for every
                    optimizer evaluation and the final sample. This is
                    exactly wrestling.mat_qaoa.run_qaoa (verified: A
                    reproduces the stored W5C p=1 runs bit for bit).
                    Same parameters -> identical 1,000 shots.
  B  "independent": every optimizer evaluation uses a fresh SamplerV2 with
                    its own seed from SeedSequence([trial_seed, 1]); the
                    final 4,000 shots use SeedSequence([trial_seed, 2]).
                    Reproducible, but no measurement stream is reused.

Independent final evaluation (identical for A and B, never seen by COBYLA):
  * EXACT: statevector probabilities of the unmeasured ansatz at the
    returned parameters (infinite-shot limit, no sampling noise).
  * HIGH-SHOT: 50,000 shots with seed SeedSequence([trial_seed, 3]).

"Optimizer's best estimated energy" = min over the 1,000-shot objective
values COBYLA saw. "Gap" = exact final energy - best estimate.

Run:  python -m wrestling.mat_qaoa_sampling
"""

import json
import math
import statistics
import time
from pathlib import Path

import numpy as np
from qiskit.circuit.library import qaoa_ansatz
from qiskit.quantum_info import Statevector
from qiskit_aer.primitives import SamplerV2
from scipy import stats
from scipy.optimize import minimize

from wrestling.mat_qaoa import (
    MAIN,
    PILOT_BUDGET_SECONDS,
    analyze_samples,
    bitstring_to_selection,
    build_circuit,
    classical_reference,
    qubo_to_ising,
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

STRATEGIES = ("fixed", "independent")
PAIRED_SEEDS = [11, 22, 33, 44, 55, 66, 77, 88, 99, 110]
REPS = 1
HIGH_SHOTS = 50_000
RESULTS = Path(__file__).parent.parent / "results"
OUT = RESULTS / "wrestling_qaoa_sampling_results.json"
W5C_SWEEP = RESULTS / "wrestling_qaoa_sweep_results.json"


# ---------------------------------------------------------------------------
# Seeds
# ---------------------------------------------------------------------------

def _seeds(trial_seed: int, stream: int, count: int) -> list[int]:
    ss = np.random.SeedSequence([trial_seed, stream])
    return [int(v) & 0x7FFFFFFF for v in ss.generate_state(count, dtype=np.uint32)]


def evaluation_seeds(trial_seed: int, count: int = 200) -> list[int]:
    return _seeds(trial_seed, 1, count)


def final_seed(trial_seed: int) -> int:
    return _seeds(trial_seed, 2, 1)[0]


def high_shot_seed(trial_seed: int) -> int:
    return _seeds(trial_seed, 3, 1)[0]


# ---------------------------------------------------------------------------
# Exact evaluation tables
# ---------------------------------------------------------------------------

def energy_tables(inst: dict, optimal_score: int) -> dict:
    n = len(inst["pool"])
    N = 2 ** n
    energy = np.array([qubo_energy(x, inst) for x in range(N)], dtype=float)
    feasible = np.array([is_feasible(x, inst) for x in range(N)])
    optimal = np.array([feasible[x] and selection_score(x, inst) == optimal_score
                        for x in range(N)])
    return {"energy": energy, "feasible": feasible, "optimal": optimal, "n": n}


def exact_distribution(inst: dict, reps: int, params_by_name: dict) -> np.ndarray:
    """Statevector probabilities indexed by assignment integer x (qubit i =
    bit i, little-endian, the same encoding as the sampled bitstrings)."""
    op, _ = qubo_to_ising(inst)
    scale = float(np.max(np.abs(op.coeffs.real)))
    ansatz = qaoa_ansatz(cost_operator=op / scale, reps=reps)
    bound = ansatz.assign_parameters(
        {p: params_by_name[p.name] for p in ansatz.parameters})
    return Statevector(bound).probabilities()


def mean_energy(counts: dict[str, int], inst: dict) -> float:
    n = sum(counts.values())
    return sum(qubo_energy(bitstring_to_selection(b), inst) * c
               for b, c in counts.items()) / n


# ---------------------------------------------------------------------------
# One trial
# ---------------------------------------------------------------------------

def run_trial(inst: dict, snapshot: dict, tables: dict, optimal: int,
              strategy: str, trial_seed: int, reps: int = REPS,
              opt_shots: int = MAIN["opt_shots"],
              final_shots: int = MAIN["final_shots"],
              maxiter: int = MAIN["maxiter"], high_shots: int = HIGH_SHOTS,
              validate: bool = True) -> dict:
    if strategy not in STRATEGIES:
        raise ValueError(strategy)
    t_start = time.perf_counter()
    circuit, _, _, scale = build_circuit(inst, reps)
    params = list(circuit.parameters)
    ops = circuit.count_ops()

    # Initial point: identical construction to run_qaoa (matched by seed).
    x0 = np.random.default_rng(trial_seed).uniform(0.0, 0.5, size=len(params))

    fixed_sampler = SamplerV2(seed=trial_seed)
    eval_seeds = evaluation_seeds(trial_seed)
    used_seeds: list[int] = []
    history: list[float] = []

    def sample(theta, shots, sampler):
        bound = circuit.assign_parameters(dict(zip(params, theta)))
        return sampler.run([bound], shots=shots).result()[0].data.meas.get_counts()

    def objective(theta):
        if strategy == "fixed":
            sampler = fixed_sampler
        else:
            s = eval_seeds[len(history)]
            used_seeds.append(s)
            sampler = SamplerV2(seed=s)
        counts = sample(theta, opt_shots, sampler)
        e = mean_energy(counts, inst)
        history.append(e)
        return e

    res = minimize(objective, x0, method="COBYLA",
                   options={"maxiter": maxiter, "rhobeg": 0.5})
    theta = np.asarray(res.x)
    fseed = trial_seed if strategy == "fixed" else final_seed(trial_seed)
    final_sampler = fixed_sampler if strategy == "fixed" else SamplerV2(seed=fseed)
    final_counts = sample(theta, final_shots, final_sampler)
    pipeline_time = time.perf_counter() - t_start

    # --- Independent evaluations (never seen by the optimizer) ---
    t0 = time.perf_counter()
    probs = exact_distribution(inst, reps,
                               {p.name: float(v) for p, v in zip(params, theta)})
    exact_E = float(probs @ tables["energy"])
    exact_feas = float(probs[tables["feasible"]].sum())
    exact_opt = float(probs[tables["optimal"]].sum())
    hseed = high_shot_seed(trial_seed)
    high_counts = sample(theta, high_shots, SamplerV2(seed=hseed))
    high_E = mean_energy(high_counts, inst)
    high_feas = sum(c for b, c in high_counts.items()
                    if tables["feasible"][bitstring_to_selection(b)]) / high_shots
    eval_time = time.perf_counter() - t0

    a = analyze_samples(final_counts, inst, snapshot, optimal, validate=validate)
    best_est = min(history)
    return {
        "strategy": strategy,
        "trial_seed": trial_seed,
        "depth": reps,
        "initial_parameters": [float(v) for v in x0],
        "final_parameters": [float(v) for v in theta],
        "cost_operator_scale": scale,
        "seeds": {
            "fixed_sampler_seed": trial_seed if strategy == "fixed" else None,
            "evaluation_seeds": used_seeds if strategy == "independent" else None,
            "final_sample_seed": fseed,
            "high_shot_seed": hseed,
        },
        "optimizer_evaluations": len(history),
        "objective_history": history,
        "objective_best_estimate": best_est,
        "objective_final_evaluation": history[-1],
        "exact_final_energy": exact_E,
        "gap_exact_minus_best_estimate": exact_E - best_est,
        "high_shot_final_energy": high_E,
        "gap_high_shot_minus_best_estimate": high_E - best_est,
        "final_sample_mean_energy": mean_energy(final_counts, inst),
        "exact_feasible_probability": exact_feas,
        "exact_optimal_probability": exact_opt,
        "exact_p_optimum_at_least_once_in_final": 1 - (1 - exact_opt) ** final_shots,
        "high_shot_feasible_probability": high_feas,
        "final_feasible_percent": a["feasible_percent"],
        "final_optimal_shots": a["optimal_shots"],
        "found_optimum_in_final": a["optimal_shots"] > 0,
        "best_feasible_score": a["best_feasible_score"],
        "best_qubo_energy": a["best_energy"],
        "validation": a["validation"],
        "circuit_depth": circuit.depth(),
        "two_qubit_gates": int(ops.get("cx", 0)),
        "pipeline_runtime_s": pipeline_time,
        "independent_evaluation_runtime_s": eval_time,
        "final_counts": final_counts,
    }


# ---------------------------------------------------------------------------
# Safeguards
# ---------------------------------------------------------------------------

def stream_check(inst: dict, trial_seed: int = 11) -> dict:
    """Same parameters, two consecutive evaluations: A must repeat its
    shots exactly, B must not."""
    circuit, _, _, _ = build_circuit(inst, REPS)
    params = list(circuit.parameters)
    bound = circuit.assign_parameters(dict(zip(params, [0.3, 0.2])))
    fixed = SamplerV2(seed=trial_seed)
    a1 = fixed.run([bound], shots=1000).result()[0].data.meas.get_bitstrings()
    a2 = fixed.run([bound], shots=1000).result()[0].data.meas.get_bitstrings()
    s0, s1 = evaluation_seeds(trial_seed)[:2]
    b1 = SamplerV2(seed=s0).run([bound], shots=1000).result()[0].data.meas.get_bitstrings()
    b2 = SamplerV2(seed=s1).run([bound], shots=1000).result()[0].data.meas.get_bitstrings()
    return {"fixed_repeats_identical_stream": a1 == a2,
            "independent_streams_differ": b1 != b2,
            "independent_eval_seeds_unique": len(set(evaluation_seeds(trial_seed)))
            == len(evaluation_seeds(trial_seed)),
            "final_and_high_shot_seeds_distinct_from_eval_seeds":
                final_seed(trial_seed) not in evaluation_seeds(trial_seed)
                and high_shot_seed(trial_seed) not in evaluation_seeds(trial_seed)}


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def t_interval(values: list[float]) -> dict:
    n = len(values)
    m = statistics.mean(values)
    sd = statistics.stdev(values) if n > 1 else 0.0
    half = float(stats.t.ppf(0.975, n - 1)) * sd / math.sqrt(n) if n > 1 else 0.0
    return {"n": n, "mean": m, "sd": sd, "ci95_t": [m - half, m + half],
            "min": min(values), "max": max(values)}


def clopper_pearson(k: int, n: int) -> list[float]:
    lo = 0.0 if k == 0 else float(stats.beta.ppf(0.025, k, n - k + 1))
    hi = 1.0 if k == n else float(stats.beta.ppf(0.975, k + 1, n - k))
    return [lo, hi]


METRICS = ["objective_best_estimate", "exact_final_energy",
           "gap_exact_minus_best_estimate", "high_shot_final_energy",
           "gap_high_shot_minus_best_estimate", "exact_feasible_probability",
           "exact_optimal_probability", "final_feasible_percent",
           "optimizer_evaluations", "pipeline_runtime_s"]


def summarize(trials: list[dict]) -> dict:
    found = sum(t["found_optimum_in_final"] for t in trials)
    gaps = [t["gap_exact_minus_best_estimate"] for t in trials]
    pos = sum(g > 0 for g in gaps)
    return {
        "strategy": trials[0]["strategy"],
        **{m: t_interval([float(t[m]) for t in trials]) for m in METRICS},
        "runs_finding_optimum_in_final": found,
        "runs_finding_optimum_ci95": clopper_pearson(found, len(trials)),
        "runs_with_positive_exact_gap": pos,
        "sign_test_positive_gap_p_two_sided": float(
            stats.binomtest(pos, len(gaps), 0.5).pvalue),
        "runs_hitting_evaluation_cap": sum(
            t["optimizer_evaluations"] >= MAIN["maxiter"] for t in trials),
        "circuit_depth": trials[0]["circuit_depth"],
        "two_qubit_gates": trials[0]["two_qubit_gates"],
        "all_feasible_validator_confirmed": all(
            t["validation"]["all_feasible_samples_validator_confirmed"]
            for t in trials),
    }


def paired(trials: list[dict]) -> dict:
    A = {t["trial_seed"]: t for t in trials if t["strategy"] == "fixed"}
    B = {t["trial_seed"]: t for t in trials if t["strategy"] == "independent"}
    seeds = sorted(A)
    out = {}
    for m in ["gap_exact_minus_best_estimate", "objective_best_estimate",
              "exact_final_energy", "exact_feasible_probability",
              "exact_optimal_probability"]:
        d = [B[s][m] - A[s][m] for s in seeds]
        w = stats.wilcoxon(d, alternative="two-sided", method="exact") \
            if any(v != 0 for v in d) else None
        out[m] = {"differences_B_minus_A": d, **t_interval(d),
                  "B_greater_count": sum(v > 0 for v in d),
                  "wilcoxon_exact_p_two_sided":
                      float(w.pvalue) if w is not None else None}
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(seed: int = DEFAULT_SEED) -> None:
    if OUT.exists():
        raise SystemExit(f"{OUT.name} already exists; refusing to overwrite.")
    snapshot = extract_snapshot(seed)
    inst = build_qubo_instance(snapshot)
    optimal = classical_brute_force(inst)["best_score"]
    tables = energy_tables(inst, optimal)
    N = 2 ** tables["n"]
    p_opt = tables["optimal"].sum() / N
    random_ref = {
        "feasible_probability": float(tables["feasible"].sum() / N),
        "optimal_probability": float(p_opt),
        "mean_energy": float(tables["energy"].mean()),
        "p_optimum_at_least_once_in_4000": float(1 - (1 - p_opt) ** MAIN["final_shots"]),
    }

    print("=== Phase W5D: fixed vs independent sampling seeds (p=1) ===")
    checks = stream_check(inst)
    print(f"Stream safeguards: {checks}")
    if not all(checks.values()):
        raise SystemExit("STOP: sampling-stream safeguard failed.")

    # --- Pilot: one matched pair; also proves A == stored W5C run_qaoa ---
    print("\nPilot: matched pair, trial seed 11")
    t0 = time.perf_counter()
    pilotA = run_trial(inst, snapshot, tables, optimal, "fixed", 11)
    pilotB = run_trial(inst, snapshot, tables, optimal, "independent", 11)
    pilot_t = time.perf_counter() - t0
    w5c = json.loads(W5C_SWEEP.read_text())
    stored = next(t for t in w5c["trials"] if t["depth"] == 1 and t["seed"] == 11)
    reproduces = (pilotA["final_counts"] == stored["final_counts"]
                  and pilotA["objective_history"] == stored["objective_history"])
    print(f"  strategy A reproduces stored W5C p=1 seed 11 exactly: {reproduces}")
    if not reproduces:
        raise SystemExit("STOP: strategy A does not match the original method.")
    est = pilot_t * len(PAIRED_SEEDS)
    print(f"  pilot pair {pilot_t:.2f} s -> full estimate ~{est:.0f} s "
          f"(budget {PILOT_BUDGET_SECONDS} s)")
    if est > PILOT_BUDGET_SECONDS:
        raise SystemExit("STOP: estimate exceeds budget.")

    trials = [pilotA, pilotB]
    for s in PAIRED_SEEDS[1:]:
        for strat in STRATEGIES:
            trials.append(run_trial(inst, snapshot, tables, optimal, strat, s))
    for s in PAIRED_SEEDS:
        a = next(t for t in trials if t["trial_seed"] == s and t["strategy"] == "fixed")
        b = next(t for t in trials if t["trial_seed"] == s and t["strategy"] == "independent")
        print(f"  seed {s:>3}: A est {a['objective_best_estimate']:6.2f} exact "
              f"{a['exact_final_energy']:6.2f} gap {a['gap_exact_minus_best_estimate']:5.2f} "
              f"feas {100*a['exact_feasible_probability']:5.2f}% | B est "
              f"{b['objective_best_estimate']:6.2f} exact {b['exact_final_energy']:6.2f} "
              f"gap {b['gap_exact_minus_best_estimate']:5.2f} feas "
              f"{100*b['exact_feasible_probability']:5.2f}%")

    summaries = [summarize([t for t in trials if t["strategy"] == s])
                 for s in STRATEGIES]
    record = {
        "experiment": "wrestling_qaoa_phase_w5d_sampling_strategy",
        "settings": {**MAIN, "reps": REPS, "high_shots": HIGH_SHOTS,
                     "paired_seeds": PAIRED_SEEDS, "strategies": list(STRATEGIES),
                     "penalty_A": inst["penalty_A"], "penalty_B": inst["penalty_B"],
                     "objective_C": inst["objective_C"], "k": inst["k"],
                     "seed_derivation": {
                         "evaluation": "SeedSequence([trial_seed, 1])",
                         "final_B": "SeedSequence([trial_seed, 2])",
                         "high_shot": "SeedSequence([trial_seed, 3])",
                         "initial_parameters": "default_rng(trial_seed).uniform(0, 0.5)"}},
        "safeguards": {**checks,
                       "strategy_A_reproduces_stored_w5c_seed11": reproduces},
        "uniform_random_exact": random_ref,
        "classical_reference": classical_reference(inst),
        "pilot_pair_seconds": pilot_t,
        "summaries": summaries,
        "paired_comparison_B_minus_A": paired(trials),
        "trials": trials,
    }
    OUT.write_text(json.dumps(record, indent=2))
    print(f"\nSaved {OUT}")


if __name__ == "__main__":
    main()
