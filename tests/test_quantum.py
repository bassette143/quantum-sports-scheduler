"""Tests for the QAOA experiment plumbing (no full experiment runs here,
except one tiny smoke test).

The critical property: every quantum-side transformation (QUBO -> Ising,
bitstring decoding) must agree EXACTLY with the exhaustively verified
classical energy function from Phase 2B Part 1.
"""

import random

from quantum_scheduler import (
    analyze_counts,
    bitstring_to_assignment,
    evaluate_ising,
    qubo_to_ising,
    run_qaoa_experiment,
)
from qubo_formulation import (
    N_ASSIGNMENTS,
    N_VARS,
    energy,
    single_rr_to_assignment,
)

# Known-valid single round-robin: R1: AB,CD  R2: AC,BD  R3: AD,BC
KNOWN_VALID = [
    (1, ("A", "B")), (1, ("C", "D")),
    (2, ("A", "C")), (2, ("B", "D")),
    (3, ("A", "D")), (3, ("B", "C")),
]


def assignment_to_bitstring(assignment: int) -> str:
    """Inverse of bitstring_to_assignment, for test fixtures."""
    return format(assignment, f"0{N_VARS}b")


# ---------- QUBO -> Ising conversion ----------

def test_ising_energy_matches_qubo_energy_on_samples():
    operator, offset = qubo_to_ising()
    rng = random.Random(7)
    samples = [0, N_ASSIGNMENTS - 1, single_rr_to_assignment(KNOWN_VALID)]
    samples += [rng.randrange(N_ASSIGNMENTS) for _ in range(200)]
    for assignment in samples:
        ising = evaluate_ising(assignment, operator, offset)
        assert abs(ising - energy(assignment)) < 1e-9


def test_ising_constant_offset_value():
    # Each variable appears in 3 constraint groups, so its linear QUBO
    # coefficient is a_i = -3 (see build_qubo). Therefore:
    # offset = qubo_offset + sum(a_i)/2 + sum(b_ij)/4
    #        = 18 + (18 * -3)/2 + (54 * 2)/4 = 18 - 27 + 27 = 18
    _, offset = qubo_to_ising()
    assert abs(offset - 18.0) < 1e-9


def test_ising_ground_state_energy_is_zero():
    operator, offset = qubo_to_ising()
    valid = single_rr_to_assignment(KNOWN_VALID)
    assert abs(evaluate_ising(valid, operator, offset)) < 1e-9


def test_ising_operator_size():
    operator, _ = qubo_to_ising()
    # 18 single-Z terms + 54 ZZ coupling terms
    assert operator.num_qubits == N_VARS
    assert len(operator) == 18 + 54


# ---------- bitstring ordering ----------

def test_bitstring_ordering_variable_zero_is_rightmost_bit():
    # Qiskit bitstrings are little-endian: classical bit 0 (our variable 0)
    # is the RIGHTMOST character.
    assert bitstring_to_assignment("0" * (N_VARS - 1) + "1") == 1
    assert bitstring_to_assignment("1" + "0" * (N_VARS - 1)) == 1 << (N_VARS - 1)


def test_bitstring_roundtrip():
    rng = random.Random(3)
    for _ in range(50):
        assignment = rng.randrange(N_ASSIGNMENTS)
        assert bitstring_to_assignment(assignment_to_bitstring(assignment)) == assignment


# ---------- sample analysis: valid detection, rejection, mirroring ----------

def test_analyze_counts_detects_valid_schedule():
    valid = single_rr_to_assignment(KNOWN_VALID)
    counts = {
        assignment_to_bitstring(valid): 10,
        assignment_to_bitstring(0): 90,  # empty schedule, energy 18
    }
    analysis = analyze_counts(counts)
    assert analysis["shots"] == 100
    assert analysis["best_energy"] == 0
    assert analysis["valid_shots"] == 10
    assert abs(analysis["valid_percent"] - 10.0) < 1e-9
    assert analysis["n_distinct_valid_schedules"] == 1
    assert analysis["mirrored_schedules_pass_phase1_validator"] is True


def test_analyze_counts_rejects_invalid_schedules():
    # Shift the valid schedule by one bit -> invalid assignment.
    valid = single_rr_to_assignment(KNOWN_VALID)
    invalid = valid ^ 1  # flip variable 0
    counts = {assignment_to_bitstring(invalid): 50}
    analysis = analyze_counts(counts)
    assert analysis["valid_shots"] == 0
    assert analysis["best_energy"] > 0
    assert analysis["n_distinct_valid_schedules"] == 0


# ---------- smoke test of the full pipeline (tiny budget) ----------

def test_building_qaoa_circuit_raises_no_deprecation_warnings():
    # Regression test for the Qiskit 2.1 QAOAAnsatz deprecation: the
    # supported qaoa_ansatz function must build cleanly at every depth
    # used in benchmarking.
    import warnings

    from quantum_scheduler import build_qaoa_circuit

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        for reps in (1, 2, 3):
            circuit, _, _ = build_qaoa_circuit(reps)
            assert circuit.num_qubits == N_VARS
            assert len(circuit.parameters) == 2 * reps


def test_qaoa_smoke_run_is_reproducible_shape():
    result = run_qaoa_experiment(
        reps=1, opt_shots=100, final_shots=200, maxiter=5, seed=1
    )
    assert result["n_qubits"] == 18
    assert result["qaoa_depth_p"] == 1
    assert result["two_qubit_gates"] == 108  # 54 ZZ couplings x 2 CX each
    assert result["optimizer_iterations"] >= 1
    analysis = result["analysis_of_final_samples"]
    assert analysis["shots"] == 200
    assert analysis["best_energy"] >= 0
    timings = result["timings_seconds"]
    assert timings["circuit_sampling_only"] <= timings["total_experiment"]
