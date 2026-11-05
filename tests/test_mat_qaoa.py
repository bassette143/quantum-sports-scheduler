"""Tests for the Phase W5 wrestling QAOA module.

Core property: every quantum-side transformation (coefficient expansion,
Ising conversion, bitstring decoding) must agree EXACTLY with the original,
exhaustively verified W4 energy function in wrestling/mat_qubo.py.
"""

import numpy as np

from wrestling.mat_qaoa import (
    analyze_samples,
    bitstring_to_selection,
    build_circuit,
    energy_from_coefficients,
    ising_energies_all,
    qubo_coefficients,
    qubo_to_ising,
    run_qaoa,
)
from wrestling.mat_qubo import (
    build_qubo_instance,
    classical_brute_force,
    extract_snapshot,
    is_feasible,
    qubo_energy,
    selection_score,
    validator_agreement,
)

_cache = {}


def setup():
    if not _cache:
        snap = extract_snapshot(seed=42)
        inst = build_qubo_instance(snap)
        brute = classical_brute_force(inst)
        opt_x = sum(1 << i for i in brute["example_subset"])
        _cache.update(snap=snap, inst=inst, brute=brute, opt_x=opt_x,
                      n=len(inst["pool"]))
    return _cache


def to_bitstring(x: int, n: int) -> str:
    return format(x, f"0{n}b")


# ---------- QUBO -> Ising equivalence ----------

def test_coefficient_expansion_matches_original_energy_exhaustively():
    c = setup()
    off, lin, quad = qubo_coefficients(c["inst"])
    for x in range(2 ** c["n"]):
        assert energy_from_coefficients(x, off, lin, quad) == qubo_energy(x, c["inst"])


def test_ising_matches_original_energy_exhaustively():
    c = setup()
    op, offset = qubo_to_ising(c["inst"])
    ising = ising_energies_all(op, offset, c["n"])
    orig = np.array([qubo_energy(x, c["inst"]) for x in range(2 ** c["n"])])
    assert np.allclose(ising, orig, atol=1e-9)


def test_ising_offset_equals_mean_energy_over_all_assignments():
    # Every Z / ZZ term averages to zero over the uniform distribution, so
    # the constant offset must equal the mean QUBO energy: an independent
    # check of the offset bookkeeping.
    c = setup()
    _, offset = qubo_to_ising(c["inst"])
    mean = sum(qubo_energy(x, c["inst"]) for x in range(2 ** c["n"])) / 2 ** c["n"]
    assert abs(offset - mean) < 1e-9
    assert abs(offset - 61.5) < 1e-9


def test_ising_operator_size():
    c = setup()
    op, _ = qubo_to_ising(c["inst"])
    assert op.num_qubits == 14
    assert len(op) == 14 + 91  # 14 Z terms + C(14,2) ZZ couplings


# ---------- bitstring ordering ----------

def test_bitstring_variable_zero_is_rightmost():
    n = setup()["n"]
    assert bitstring_to_selection("0" * (n - 1) + "1") == 1
    assert bitstring_to_selection("1" + "0" * (n - 1)) == 1 << (n - 1)


def test_bitstring_roundtrip_all():
    n = setup()["n"]
    for x in range(0, 2 ** n, 37):
        assert bitstring_to_selection(to_bitstring(x, n)) == x


# ---------- penalties and objective ----------

def test_penalty_and_objective_values():
    c = setup()
    inst, n = c["inst"], c["n"]
    A, B, k = inst["penalty_A"], inst["penalty_B"], inst["k"]
    assert (A, B, k, inst["objective_C"]) == (13, 13, 6, 1)
    # Empty selection: only the cardinality penalty A*k^2 = 13*36.
    assert qubo_energy(0, inst) == A * k * k == 468
    # Select everything: A*(14-6)^2 + B*(4 same-weight pairs) - sum(scores).
    full = 2 ** n - 1
    assert qubo_energy(full, inst) == A * 64 + B * 4 - sum(inst["scores"]) == 864
    # Optimal feasible selection: energy is exactly -score = -12.
    assert qubo_energy(c["opt_x"], inst) == -12


# ---------- feasible / optimal identification ----------

def test_analyze_samples_identifies_feasible_and_optimal():
    c = setup()
    inst, n, opt_x = c["inst"], c["n"], c["opt_x"]
    # A feasible but sub-optimal selection: swap one score-2 match for a
    # score-1 match of an unused weight class.
    sub = None
    for x in range(2 ** n):
        if is_feasible(x, inst) and selection_score(x, inst) == 11:
            sub = x
            break
    assert sub is not None
    counts = {
        to_bitstring(opt_x, n): 5,
        to_bitstring(sub, n): 15,
        to_bitstring(0, n): 80,  # infeasible (empty)
    }
    a = analyze_samples(counts, inst, c["snap"], optimal_score=12)
    assert a["shots"] == 100
    assert a["feasible_shots"] == 20
    assert a["optimal_shots"] == 5
    assert abs(a["optimal_percent"] - 5.0) < 1e-9
    assert a["best_energy"] == -12
    assert a["best_feasible_score"] == 12
    assert a["n_distinct_feasible"] == 2
    assert a["validation"]["all_feasible_samples_validator_confirmed"]


def test_analyze_samples_rejects_infeasible_only():
    c = setup()
    n = c["n"]
    counts = {to_bitstring(0, n): 10, to_bitstring(2 ** n - 1, n): 10}
    a = analyze_samples(counts, c["inst"], c["snap"], optimal_score=12)
    assert a["feasible_shots"] == 0
    assert a["optimal_shots"] == 0
    assert a["best_feasible_score"] is None
    assert a["best_energy"] > 0


# ---------- independent validation ----------

def test_independent_validator_accepts_optimal_selection():
    c = setup()
    assert validator_agreement(c["snap"], c["opt_x"])


def test_independent_validator_rejects_too_many_matches():
    # 7 selected matches would need a 7th mat: the W3 validator must reject.
    c = setup()
    seven = (1 << 7) - 1
    assert bin(seven).count("1") == 7
    assert not validator_agreement(c["snap"], seven)


# ---------- circuit and reproducibility ----------

def test_circuit_structure_p1():
    circuit, _, _, scale = build_circuit(setup()["inst"], reps=1)
    assert circuit.num_qubits == 14
    assert len(circuit.parameters) == 2
    assert circuit.count_ops().get("cx", 0) == 182  # 91 ZZ terms x 2 CX
    assert scale > 0


def test_qaoa_run_is_reproducible_with_fixed_seed():
    c = setup()
    kwargs = dict(reps=1, opt_shots=100, final_shots=200, maxiter=4,
                  seed=7, validate=False)
    r1 = run_qaoa(c["inst"], c["snap"], 12, **kwargs)
    r2 = run_qaoa(c["inst"], c["snap"], 12, **kwargs)
    assert r1["final_counts"] == r2["final_counts"]
    assert r1["mean_energy_history"] == r2["mean_energy_history"]
    assert r1["analysis"]["shots"] == 200
