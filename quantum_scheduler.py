"""QAOA experiment for the verified 18-variable scheduling QUBO.

Pipeline (hybrid quantum-classical):

  1. Take the EXACT QUBO coefficients verified exhaustively in Phase 2B
     Part 1 (qubo_formulation.build_qubo). The math is not changed here.
  2. Convert the QUBO to an Ising Hamiltonian (Pauli-Z operators) using
     the standard substitution x_i = (1 - z_i) / 2, tracking the constant
     energy offset so that <H> equals the original QUBO energy exactly.
  3. Build an 18-qubit QAOA ansatz (depth p configurable, starting at 1).
  4. Optimize the 2p circuit parameters with SciPy's COBYLA, where each
     objective evaluation samples the circuit on the Aer simulator and
     scores every measured bitstring with the ORIGINAL verified
     qubo_formulation.energy() function.
  5. Sample the best parameters, report the fraction of valid schedules,
     mirror valid ones to double round-robins, and check them with the
     ORIGINAL Phase 1 validator.

Honesty notes:
  * QAOA is a heuristic; it may return few or no valid schedules.
  * All runtimes are measured with time.perf_counter() and the classical
    optimizer overhead is reported as part of total runtime.
  * Fixed seeds make the experiment reproducible.

Run:  python quantum_scheduler.py
"""

import json
import time
from pathlib import Path

import numpy as np
from qiskit.circuit.library import qaoa_ansatz
from qiskit.quantum_info import SparsePauliOp
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit_aer.primitives import SamplerV2
from scipy.optimize import minimize

from qubo_formulation import (
    N_VARS,
    TEAMS,
    build_qubo,
    energy,
    mirror_to_double_round_robin,
)
from schedule_validator import validate_schedule

DEFAULT_SEED = 42


# ---------------------------------------------------------------------------
# QUBO -> Ising conversion
# ---------------------------------------------------------------------------

def qubo_to_ising() -> tuple[SparsePauliOp, float]:
    """Convert the verified QUBO into (Pauli operator, constant offset).

    Substituting x_i = (1 - z_i)/2 (x in {0,1}, z in {+1,-1}):

        a_i * x_i      ->  a_i/2          - (a_i/2) * z_i
        b_ij * x_i x_j ->  b_ij/4         - (b_ij/4) * (z_i + z_j)
                                          + (b_ij/4) * z_i z_j

    Returns (operator, offset) such that for every assignment:

        <z| operator |z> + offset == qubo_formulation.energy(assignment)
    """
    qubo_offset, linear, quadratic = build_qubo()

    z_coeffs = {i: 0.0 for i in range(N_VARS)}
    zz_terms: list[tuple[int, int, float]] = []
    offset = float(qubo_offset)

    for i, a in linear.items():
        offset += a / 2
        z_coeffs[i] += -a / 2

    for (i, j), b in quadratic.items():
        offset += b / 4
        z_coeffs[i] += -b / 4
        z_coeffs[j] += -b / 4
        zz_terms.append((i, j, b / 4))

    sparse_list = [
        ("Z", [i], c) for i, c in z_coeffs.items() if c != 0.0
    ] + [
        ("ZZ", [i, j], c) for i, j, c in zz_terms
    ]
    operator = SparsePauliOp.from_sparse_list(sparse_list, num_qubits=N_VARS)
    return operator.simplify(), offset


def evaluate_ising(assignment: int, operator: SparsePauliOp, offset: float) -> float:
    """Classically evaluate <z|H|z> + offset for one binary assignment.

    Used by tests to prove the Ising conversion reproduces the QUBO energy.
    """
    z = np.array(
        [1.0 if not (assignment >> i) & 1 else -1.0 for i in range(N_VARS)]
    )
    total = offset
    for pauli, coeff in zip(operator.paulis, operator.coeffs):
        zs = np.where(pauli.z)[0]  # qubit indices carrying a Z
        total += coeff.real * np.prod(z[zs])
    return float(total)


# ---------------------------------------------------------------------------
# Bitstring handling
# ---------------------------------------------------------------------------

def bitstring_to_assignment(bitstring: str) -> int:
    """Convert a Qiskit measurement bitstring to our assignment integer.

    Qiskit prints classical bits with bit 0 on the RIGHT (little-endian),
    and measure_all maps qubit i to classical bit i. Our variable i is
    qubit i, so int(bitstring, 2) puts variable i at integer bit i -
    exactly the encoding used by qubo_formulation.energy().
    """
    return int(bitstring, 2)


def analyze_counts(counts: dict[str, int]) -> dict:
    """Score every measured bitstring with the verified QUBO energy.

    Valid schedules (energy 0) are mirrored to double round-robins and
    checked with the original Phase 1 validator.
    """
    shots = sum(counts.values())
    best_energy = None
    valid_shots = 0
    valid_assignments: set[int] = set()

    for bitstring, count in counts.items():
        assignment = bitstring_to_assignment(bitstring)
        e = energy(assignment)
        if best_energy is None or e < best_energy:
            best_energy = e
        if e == 0:
            valid_shots += count
            valid_assignments.add(assignment)

    mirrored_all_valid = True
    for assignment in valid_assignments:
        result = validate_schedule(
            mirror_to_double_round_robin(assignment), TEAMS
        )
        if not result.is_valid:
            mirrored_all_valid = False

    return {
        "shots": shots,
        "best_energy": best_energy,
        "valid_shots": valid_shots,
        "valid_percent": 100.0 * valid_shots / shots if shots else 0.0,
        "distinct_valid_schedules": sorted(valid_assignments),
        "n_distinct_valid_schedules": len(valid_assignments),
        "mirrored_schedules_pass_phase1_validator": mirrored_all_valid,
    }


# ---------------------------------------------------------------------------
# QAOA experiment
# ---------------------------------------------------------------------------

def build_qaoa_circuit(reps: int):
    """Build and transpile the measured QAOA circuit for a given depth.

    Uses the supported qiskit.circuit.library.qaoa_ansatz function (the
    QAOAAnsatz class is deprecated since Qiskit 2.1). Returns
    (transpiled_circuit, operator, offset).
    """
    operator, offset = qubo_to_ising()
    ansatz = qaoa_ansatz(cost_operator=operator, reps=reps)
    ansatz.measure_all()
    pass_manager = generate_preset_pass_manager(
        optimization_level=1, basis_gates=["cx", "rz", "rx", "h"]
    )
    return pass_manager.run(ansatz), operator, offset


def run_qaoa_experiment(
    reps: int = 1,
    opt_shots: int = 1000,
    final_shots: int = 4000,
    maxiter: int = 40,
    seed: int = DEFAULT_SEED,
) -> dict:
    """Run one controlled QAOA experiment on the Aer simulator."""
    total_start = time.perf_counter()

    circuit, operator, offset = build_qaoa_circuit(reps)
    parameters = list(circuit.parameters)

    ops = circuit.count_ops()
    two_qubit_gates = int(ops.get("cx", 0))
    total_gates = int(sum(ops.values())) - int(ops.get("measure", 0)) - int(
        ops.get("barrier", 0)
    )

    sampler = SamplerV2(seed=seed)
    rng = np.random.default_rng(seed)
    initial_point = rng.uniform(0.0, 0.5, size=len(parameters))

    sampling_time = 0.0
    iteration_count = 0
    energy_history: list[float] = []

    def sample_counts(params: np.ndarray, shots: int) -> dict[str, int]:
        nonlocal sampling_time
        bound = circuit.assign_parameters(dict(zip(parameters, params)))
        t0 = time.perf_counter()
        job = sampler.run([bound], shots=shots)
        counts = job.result()[0].data.meas.get_counts()
        sampling_time += time.perf_counter() - t0
        return counts

    def objective(params: np.ndarray) -> float:
        nonlocal iteration_count
        iteration_count += 1
        counts = sample_counts(params, opt_shots)
        shots = sum(counts.values())
        mean_energy = (
            sum(energy(bitstring_to_assignment(b)) * c for b, c in counts.items())
            / shots
        )
        energy_history.append(mean_energy)
        return mean_energy

    # --- Classical optimization loop (COBYLA) ---
    opt_start = time.perf_counter()
    opt_result = minimize(
        objective,
        initial_point,
        method="COBYLA",
        options={"maxiter": maxiter, "rhobeg": 0.5},
    )
    optimization_time = time.perf_counter() - opt_start

    # --- Final sampling at the best parameters found ---
    final_counts = sample_counts(np.asarray(opt_result.x), final_shots)
    analysis = analyze_counts(final_counts)

    total_time = time.perf_counter() - total_start

    return {
        "experiment": "qaoa_simulator",
        "backend": "qiskit-aer SamplerV2 (local simulator)",
        "n_qubits": N_VARS,
        "qaoa_depth_p": reps,
        "circuit_depth": circuit.depth(),
        "total_gates": total_gates,
        "two_qubit_gates": two_qubit_gates,
        "gate_counts": {k: int(v) for k, v in ops.items()},
        "seed": seed,
        "optimizer": "COBYLA",
        "optimizer_iterations": iteration_count,
        "optimizer_maxiter": maxiter,
        "optimization_shots_per_iteration": opt_shots,
        "final_shots": final_shots,
        "initial_mean_energy": energy_history[0] if energy_history else None,
        "final_mean_energy": energy_history[-1] if energy_history else None,
        "mean_energy_history": energy_history,
        "ising_offset": offset,
        "analysis_of_final_samples": analysis,
        "timings_seconds": {
            "total_experiment": total_time,
            "hybrid_optimization_loop": optimization_time,
            "circuit_sampling_only": sampling_time,
            "classical_overhead": total_time - sampling_time,
        },
    }


def print_report(result: dict) -> None:
    a = result["analysis_of_final_samples"]
    t = result["timings_seconds"]
    print("=== QAOA simulator experiment ===")
    print(f"Backend: {result['backend']}")
    print(f"Qubits: {result['n_qubits']}  |  QAOA depth p={result['qaoa_depth_p']}")
    print(
        f"Transpiled circuit: depth {result['circuit_depth']}, "
        f"{result['total_gates']} gates "
        f"({result['two_qubit_gates']} two-qubit CX)"
    )
    print(
        f"Optimizer: {result['optimizer']}, {result['optimizer_iterations']} "
        f"iterations x {result['optimization_shots_per_iteration']} shots"
    )
    print(f"Seed: {result['seed']}")
    print()
    print(f"Mean energy: start {result['initial_mean_energy']:.3f} "
          f"-> end {result['final_mean_energy']:.3f}")
    print(f"Final sampling: {a['shots']} shots")
    print(f"Best QUBO energy sampled: {a['best_energy']}")
    print(
        f"Valid schedules: {a['valid_shots']}/{a['shots']} shots "
        f"({a['valid_percent']:.3f}%)"
    )
    print(
        f"Distinct valid schedules found: {a['n_distinct_valid_schedules']} "
        f"of 6 possible"
    )
    print(
        "Mirrored double round-robins pass Phase 1 validator: "
        f"{a['mirrored_schedules_pass_phase1_validator']}"
    )
    print()
    print("Measured runtimes:")
    print(f"  Total experiment:          {t['total_experiment']:.3f} s")
    print(f"  Hybrid optimization loop:  {t['hybrid_optimization_loop']:.3f} s")
    print(f"  Circuit sampling only:     {t['circuit_sampling_only']:.3f} s")
    print(f"  Classical overhead:        {t['classical_overhead']:.3f} s")


def main() -> None:
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)

    result = run_qaoa_experiment()
    print_report(result)

    out_path = results_dir / "quantum_qaoa_result.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
