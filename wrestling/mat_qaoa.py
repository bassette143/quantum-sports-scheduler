"""Phase W5: QAOA on the verified 14-variable wrestling mat-selection QUBO.

Separate from the original 18-qubit round-robin experiment
(quantum_scheduler.py), which is not modified or imported for its QUBO.

Pipeline
--------
1. Build the W4 instance exactly as wrestling/mat_qubo.py does (seed 42,
   snapshot slot 17, 14 ready matches, k = 6, A = B = 13, C = 1).
2. Expand H(x) into explicit QUBO coefficients (offset, linear, quadratic)
   and check them against the ORIGINAL mat_qubo.qubo_energy().
3. Convert to an Ising operator with x_i = (1 - z_i) / 2, tracking the
   constant offset so that <z|H|z> + offset == qubo_energy(x) exactly.
4. Build a QAOA ansatz (p = 1 to start) on the Aer simulator. The cost
   operator fed to the ansatz is divided by its largest |coefficient|
   (a constant rescaling of the gamma angles only: same eigenvectors,
   same ordering of energies, same ground state). Without this, the
   W4 penalties (up to 39/4 per ZZ term) would make gamma wrap around
   many times inside the optimizer's starting range.
5. COBYLA minimizes the mean ORIGINAL qubo_energy() over sampled shots.
6. Final samples are decoded and scored with the original W4 functions
   (qubo_energy, is_feasible, selection_score); every distinct feasible
   selection is completed to a full tournament and checked by the
   INDEPENDENT mat validator (mat_qubo.validator_agreement).

Honesty notes
-------------
* QAOA is a heuristic and may rarely or never sample the optimum.
* The exact uniform-random probabilities are known (1,289 feasible and
  1 optimal out of 16,384), so "better than chance" is measured against
  exact numbers, not a lucky empirical baseline.
* All runtimes are measured with time.perf_counter(); nothing is estimated.
* Aer simulator only. No IBM hardware, no QPU time.

Run:  python -m wrestling.mat_qaoa
"""

import json
import statistics
import time
from pathlib import Path

import numpy as np
from qiskit.circuit.library import qaoa_ansatz
from qiskit.quantum_info import SparsePauliOp
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit_aer.primitives import SamplerV2
from scipy.optimize import minimize

from wrestling.mat_qubo import (
    build_qubo_instance,
    classical_brute_force,
    classical_greedy,
    extract_snapshot,
    is_feasible,
    qubo_energy,
    selection_score,
    validator_agreement,
)
from wrestling.rosters import DEFAULT_SEED

QAOA_SEED = 42

PILOT = {"reps": 1, "opt_shots": 200, "final_shots": 1000, "maxiter": 5}
MAIN = {"reps": 1, "opt_shots": 1000, "final_shots": 4000, "maxiter": 40}
PILOT_BUDGET_SECONDS = 600  # abort the main run if the estimate exceeds this


# ---------------------------------------------------------------------------
# QUBO coefficients and Ising conversion
# ---------------------------------------------------------------------------

def qubo_coefficients(inst: dict) -> tuple[float, dict[int, float],
                                           dict[tuple[int, int], float]]:
    """Expand the W4 energy into H = offset + sum a_i x_i + sum b_ij x_i x_j.

    Using x_i**2 == x_i for binary variables:

      A (sum x - k)^2 = A k^2 + A (1 - 2k) sum x_i + 2A sum_{i<j} x_i x_j
      B sum_{same weight} x_i x_j          -> +B on those pairs
      -C sum u_i x_i                       -> -C u_i on the diagonal
    """
    n = len(inst["pool"])
    A, B, C, k = (inst["penalty_A"], inst["penalty_B"],
                  inst["objective_C"], inst["k"])
    offset = float(A * k * k)
    linear = {i: float(A * (1 - 2 * k) - C * inst["scores"][i])
              for i in range(n)}
    quadratic = {(i, j): float(2 * A)
                 for i in range(n) for j in range(i + 1, n)}
    for i, j in inst["same_weight_pairs"]:
        quadratic[(min(i, j), max(i, j))] += B
    return offset, linear, quadratic


def energy_from_coefficients(x: int, offset: float, linear: dict,
                             quadratic: dict) -> float:
    total = offset
    for i, a in linear.items():
        if (x >> i) & 1:
            total += a
    for (i, j), b in quadratic.items():
        if (x >> i) & 1 and (x >> j) & 1:
            total += b
    return total


def qubo_to_ising(inst: dict) -> tuple[SparsePauliOp, float]:
    """Return (operator, offset) with <z|op|z> + offset == qubo_energy(x).

    x_i = (1 - z_i)/2:
      a_i x_i       -> a_i/2 - (a_i/2) z_i
      b_ij x_i x_j  -> b_ij/4 - (b_ij/4)(z_i + z_j) + (b_ij/4) z_i z_j
    """
    n = len(inst["pool"])
    q_offset, linear, quadratic = qubo_coefficients(inst)
    z = {i: 0.0 for i in range(n)}
    zz: list[tuple[int, int, float]] = []
    offset = q_offset
    for i, a in linear.items():
        offset += a / 2
        z[i] -= a / 2
    for (i, j), b in quadratic.items():
        offset += b / 4
        z[i] -= b / 4
        z[j] -= b / 4
        zz.append((i, j, b / 4))
    terms = [("Z", [i], c) for i, c in z.items() if c != 0.0]
    terms += [("ZZ", [i, j], c) for i, j, c in zz]
    op = SparsePauliOp.from_sparse_list(terms, num_qubits=n).simplify()
    return op, offset


def ising_energies_all(op: SparsePauliOp, offset: float, n: int) -> np.ndarray:
    """Vectorized <z|op|z> + offset for every assignment 0 .. 2^n - 1."""
    xs = np.arange(2 ** n)
    zmat = 1.0 - 2.0 * ((xs[:, None] >> np.arange(n)) & 1)  # z = 1 - 2x
    total = np.full(2 ** n, offset, dtype=float)
    for pauli, coeff in zip(op.paulis, op.coeffs):
        idx = np.where(pauli.z)[0]
        total += coeff.real * np.prod(zmat[:, idx], axis=1)
    return total


# ---------------------------------------------------------------------------
# Bitstrings and sample analysis
# ---------------------------------------------------------------------------

def bitstring_to_selection(bitstring: str) -> int:
    """Qiskit bitstrings are little-endian (qubit 0 is the RIGHTMOST
    character) and measure_all maps qubit i -> clbit i, so int(bs, 2)
    puts variable i at integer bit i, the encoding used by mat_qubo."""
    return int(bitstring, 2)


def selected_matches(x: int, inst: dict) -> list[str]:
    return [m for i, m in enumerate(inst["pool"]) if (x >> i) & 1]


def analyze_samples(counts: dict[str, int], inst: dict, snapshot: dict,
                    optimal_score: int, validate: bool = True) -> dict:
    """Score samples with the ORIGINAL W4 functions and, optionally, check
    every distinct feasible selection with the independent validator."""
    shots = sum(counts.values())
    feasible_shots = optimal_shots = 0
    best_energy = None
    best_feasible_score = None
    distinct_feasible: dict[int, int] = {}
    for bs, c in counts.items():
        x = bitstring_to_selection(bs)
        e = qubo_energy(x, inst)
        if best_energy is None or e < best_energy:
            best_energy = e
        if is_feasible(x, inst):
            feasible_shots += c
            distinct_feasible[x] = distinct_feasible.get(x, 0) + c
            s = selection_score(x, inst)
            if best_feasible_score is None or s > best_feasible_score:
                best_feasible_score = s
            if s == optimal_score:
                optimal_shots += c

    validation = None
    if validate:
        t0 = time.perf_counter()
        failures = [x for x in distinct_feasible
                    if not validator_agreement(snapshot, x)]
        validation = {
            "distinct_feasible_checked": len(distinct_feasible),
            "validator_failures": len(failures),
            "all_feasible_samples_validator_confirmed": not failures,
            "validation_time_s": time.perf_counter() - t0,
        }

    optimal_x = [x for x in distinct_feasible
                 if selection_score(x, inst) == optimal_score]
    return {
        "shots": shots,
        "best_energy": best_energy,
        "best_feasible_score": best_feasible_score,
        "feasible_shots": feasible_shots,
        "feasible_percent": 100.0 * feasible_shots / shots if shots else 0.0,
        "optimal_shots": optimal_shots,
        "optimal_percent": 100.0 * optimal_shots / shots if shots else 0.0,
        "n_distinct_bitstrings": len(counts),
        "n_distinct_feasible": len(distinct_feasible),
        "optimal_selections_found": [selected_matches(x, inst)
                                     for x in optimal_x],
        "validation": validation,
    }


# ---------------------------------------------------------------------------
# QAOA
# ---------------------------------------------------------------------------

def build_circuit(inst: dict, reps: int):
    """Transpiled, measured QAOA circuit on the NORMALIZED cost operator.

    Returns (circuit, operator, offset, scale) where operator/offset are
    the UNSCALED Ising form and scale = max |coefficient|."""
    op, offset = qubo_to_ising(inst)
    scale = float(np.max(np.abs(op.coeffs.real)))
    ansatz = qaoa_ansatz(cost_operator=op / scale, reps=reps)
    ansatz.measure_all()
    pm = generate_preset_pass_manager(
        optimization_level=1, basis_gates=["cx", "rz", "rx", "h"]
    )
    return pm.run(ansatz), op, offset, scale


def run_qaoa(inst: dict, snapshot: dict, optimal_score: int, reps: int,
             opt_shots: int, final_shots: int, maxiter: int,
             seed: int = QAOA_SEED, validate: bool = True) -> dict:
    """One reproducible QAOA experiment on the Aer simulator."""
    total_start = time.perf_counter()
    circuit, _, offset, scale = build_circuit(inst, reps)
    params = list(circuit.parameters)
    ops = circuit.count_ops()

    sampler = SamplerV2(seed=seed)
    rng = np.random.default_rng(seed)
    x0 = rng.uniform(0.0, 0.5, size=len(params))

    sampling_time = 0.0
    history: list[float] = []

    def sample(theta, shots):
        nonlocal sampling_time
        bound = circuit.assign_parameters(dict(zip(params, theta)))
        t0 = time.perf_counter()
        counts = sampler.run([bound], shots=shots).result()[0].data.meas.get_counts()
        sampling_time += time.perf_counter() - t0
        return counts

    def objective(theta):
        counts = sample(theta, opt_shots)
        n = sum(counts.values())
        mean = sum(qubo_energy(bitstring_to_selection(b), inst) * c
                   for b, c in counts.items()) / n
        history.append(mean)
        return mean

    opt_start = time.perf_counter()
    res = minimize(objective, x0, method="COBYLA",
                   options={"maxiter": maxiter, "rhobeg": 0.5})
    opt_time = time.perf_counter() - opt_start

    final_counts = sample(np.asarray(res.x), final_shots)
    quantum_time = time.perf_counter() - total_start  # excludes validation
    analysis = analyze_samples(final_counts, inst, snapshot, optimal_score,
                               validate=validate)

    return {
        "backend": "qiskit-aer SamplerV2 (local noiseless simulator)",
        "n_qubits": len(inst["pool"]),
        "qaoa_depth_p": reps,
        "seed": seed,
        "cost_operator_scale": scale,
        "ising_offset": offset,
        "circuit_depth": circuit.depth(),
        "two_qubit_gates": int(ops.get("cx", 0)),
        "total_gates": int(sum(ops.values()) - ops.get("measure", 0)
                           - ops.get("barrier", 0)),
        "gate_counts": {k: int(v) for k, v in ops.items()},
        "optimizer": "COBYLA",
        "optimizer_maxiter": maxiter,
        "optimizer_evaluations": len(history),
        "optimization_shots_per_evaluation": opt_shots,
        "final_shots": final_shots,
        "total_shots": len(history) * opt_shots + final_shots,
        "initial_mean_energy": history[0] if history else None,
        "final_mean_energy": history[-1] if history else None,
        "best_mean_energy": min(history) if history else None,
        "mean_energy_history": history,
        "optimal_parameters": [float(v) for v in res.x],
        "final_counts": final_counts,
        "analysis": analysis,
        "timings_seconds": {
            "quantum_pipeline_total": quantum_time,
            "hybrid_optimization_loop": opt_time,
            "circuit_sampling_only": sampling_time,
            "classical_overhead": quantum_time - sampling_time,
        },
    }


# ---------------------------------------------------------------------------
# Classical reference (measured fresh, same process, same instance)
# ---------------------------------------------------------------------------

def classical_reference(inst: dict, repeats: int = 20) -> dict:
    brute_times, greedy_times = [], []
    brute = greedy = None
    for _ in range(repeats):
        t0 = time.perf_counter()
        brute = classical_brute_force(inst)
        brute_times.append(time.perf_counter() - t0)
        t0 = time.perf_counter()
        greedy = classical_greedy(inst)
        greedy_times.append(time.perf_counter() - t0)
    return {
        "repeats": repeats,
        "brute_force_score": brute["best_score"],
        "brute_force_n_optimal": brute["n_optimal_subsets"],
        "brute_force_median_time_s": statistics.median(brute_times),
        "greedy_score": greedy["score"],
        "greedy_median_time_s": statistics.median(greedy_times),
    }


def main(seed: int = DEFAULT_SEED) -> None:
    results_dir = Path(__file__).parent.parent / "results"
    print("=== Phase W5: QAOA on the 14-variable wrestling mat QUBO ===")
    print("Backend: Aer noiseless simulator (no IBM hardware)\n")

    snapshot = extract_snapshot(seed)
    inst = build_qubo_instance(snapshot)
    n = len(inst["pool"])

    # --- Pre-flight: coefficient expansion and Ising conversion, exhaustive ---
    q_off, lin, quad = qubo_coefficients(inst)
    orig = [qubo_energy(x, inst) for x in range(2 ** n)]
    coeff_ok = all(energy_from_coefficients(x, q_off, lin, quad) == orig[x]
                   for x in range(2 ** n))
    op, offset = qubo_to_ising(inst)
    ising_ok = bool(np.allclose(ising_energies_all(op, offset, n), orig,
                                atol=1e-9))
    print(f"QUBO coefficients == original energy on all {2**n:,}: {coeff_ok}")
    print(f"Ising + offset   == original energy on all {2**n:,}: {ising_ok}")
    print(f"Ising offset: {offset}  |  operator terms: {len(op)}")
    if not (coeff_ok and ising_ok):
        print("STOP: conversion check failed.")
        return

    classical = classical_reference(inst)
    optimal = classical["brute_force_score"]
    n_feasible = sum(1 for x in range(2 ** n) if is_feasible(x, inst))
    random_feasible = 100.0 * n_feasible / 2 ** n
    random_optimal = 100.0 * 1 / 2 ** n  # exactly one optimal selection
    print(f"Classical optimum (brute force): {optimal}  |  "
          f"greedy: {classical['greedy_score']}")
    print(f"Uniform-random exact rates: feasible {random_feasible:.3f}%, "
          f"optimal {random_optimal:.4f}%\n")

    # --- Pilot ---
    print(f"Pilot: {PILOT}")
    pilot = run_qaoa(inst, snapshot, optimal, seed=QAOA_SEED,
                     validate=False, **PILOT)
    pt = pilot["timings_seconds"]["quantum_pipeline_total"]
    est = pt * (MAIN["maxiter"] * MAIN["opt_shots"] + MAIN["final_shots"]) / (
        PILOT["maxiter"] * PILOT["opt_shots"] + PILOT["final_shots"])
    print(f"  pilot time {pt:.2f} s, feasible {pilot['analysis']['feasible_percent']:.2f}%"
          f"  -> main estimate ~{est:.0f} s (budget {PILOT_BUDGET_SECONDS} s)\n")
    if est > PILOT_BUDGET_SECONDS:
        print("STOP: main experiment estimate exceeds budget.")
        return

    # --- Main (initial) experiment ---
    print(f"Main experiment: {MAIN}, seed {QAOA_SEED}")
    result = run_qaoa(inst, snapshot, optimal, seed=QAOA_SEED, **MAIN)
    a, t = result["analysis"], result["timings_seconds"]
    print(f"  circuit: depth {result['circuit_depth']}, "
          f"{result['two_qubit_gates']} CX, {result['total_gates']} gates")
    print(f"  optimizer evaluations: {result['optimizer_evaluations']} "
          f"x {MAIN['opt_shots']} shots + {MAIN['final_shots']} final "
          f"= {result['total_shots']:,} shots")
    print(f"  mean energy: {result['initial_mean_energy']:.2f} -> "
          f"{result['final_mean_energy']:.2f} (best {result['best_mean_energy']:.2f})")
    print(f"  best sampled energy: {a['best_energy']}  "
          f"(optimum {-optimal})")
    print(f"  best feasible score sampled: {a['best_feasible_score']} "
          f"(optimum {optimal})")
    print(f"  feasible samples: {a['feasible_shots']}/{a['shots']} "
          f"= {a['feasible_percent']:.2f}%  (random {random_feasible:.3f}%)")
    print(f"  optimal samples:  {a['optimal_shots']}/{a['shots']} "
          f"= {a['optimal_percent']:.3f}%  (random {random_optimal:.4f}%)")
    v = a["validation"]
    print(f"  independent validator: {v['distinct_feasible_checked']} distinct "
          f"feasible selections, failures {v['validator_failures']}")
    print(f"  quantum pipeline time: {t['quantum_pipeline_total']:.2f} s "
          f"(sampling {t['circuit_sampling_only']:.2f} s)")
    print(f"  classical brute force: {classical['brute_force_median_time_s']*1000:.2f} ms, "
          f"greedy: {classical['greedy_median_time_s']*1e6:.1f} us (medians of "
          f"{classical['repeats']})")

    record = {
        "experiment": "wrestling_mat_qaoa_phase_w5_initial",
        "instance": {
            "seed": seed, "snapshot_slot": snapshot["slot"],
            "pool": inst["pool"], "weights": inst["weights"],
            "scores": inst["scores"], "k": inst["k"],
            "penalty_A": inst["penalty_A"], "penalty_B": inst["penalty_B"],
            "objective_C": inst["objective_C"],
        },
        "preflight": {
            "qubo_coefficients_match_original_energy_all_assignments": coeff_ok,
            "ising_matches_original_energy_all_assignments": ising_ok,
            "ising_offset": offset,
            "ising_terms": len(op),
        },
        "uniform_random_exact": {
            "n_feasible": n_feasible, "n_assignments": 2 ** n,
            "feasible_percent": random_feasible,
            "optimal_percent": random_optimal,
        },
        "classical_reference": classical,
        "pilot": {k: v for k, v in pilot.items() if k != "final_counts"},
        "main": result,
        "limitations": [
            "Single seed, single depth (p=1): no statistics yet.",
            "Noiseless Aer simulator; runtimes are not hardware runtimes.",
            "Cost operator normalized by its max |coefficient| for the "
            "ansatz only; all scoring uses the original W4 energy.",
            "The W4 snapshot is easy for classical greedy (optimum 12 found "
            "in microseconds).",
        ],
    }
    out = results_dir / "wrestling_qaoa_result.json"
    out.write_text(json.dumps(record, indent=2))
    print(f"\nResults saved to {out}")


if __name__ == "__main__":
    main()
