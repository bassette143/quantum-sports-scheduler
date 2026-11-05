"""Tests for the Phase W4 mat-selection QUBO feasibility model."""

from wrestling.mat_qubo import (
    build_qubo_instance,
    classical_brute_force,
    classical_greedy,
    exhaustive_verification,
    extract_snapshot,
    is_feasible,
    qubo_energy,
    selection_score,
    validator_agreement,
)

_snapshot = None


def snapshot():
    global _snapshot
    if _snapshot is None:
        _snapshot = extract_snapshot(seed=42)
    return _snapshot


def test_snapshot_is_deterministic_and_bounded():
    s = snapshot()
    s2 = extract_snapshot(seed=42)
    assert s["pool"] == s2["pool"]
    assert s["slot"] == s2["slot"]
    assert 8 <= s["n_variables"] <= 16
    assert 1 <= s["k"] <= 6


def test_scores_are_one_or_two():
    s = snapshot()
    assert set(s["scores"].values()) <= {1, 2}


def test_feasible_energy_equals_negative_score():
    inst = build_qubo_instance(snapshot())
    n = len(inst["pool"])
    found_feasible = 0
    for x in range(0, 2 ** n, 7):  # strided sample across the space
        if is_feasible(x, inst):
            found_feasible += 1
            assert qubo_energy(x, inst) == -selection_score(x, inst)
    assert found_feasible > 0


def test_infeasible_assignments_receive_positive_penalty():
    inst = build_qubo_instance(snapshot())
    # Empty selection and full selection are both infeasible.
    for x in (0, 2 ** len(inst["pool"]) - 1):
        assert not is_feasible(x, inst)
        penalty_part = qubo_energy(x, inst) + selection_score(x, inst)
        assert penalty_part > 0


def test_penalty_dominates_objective():
    inst = build_qubo_instance(snapshot())
    assert inst["penalty_A"] > inst["max_score"]


def test_exhaustive_ground_states_are_feasible_optima():
    inst = build_qubo_instance(snapshot())
    ver = exhaustive_verification(inst)
    assert ver["all_ground_states_feasible"]
    assert ver["ground_equals_best_feasible"]
    assert ver["min_infeasible_penalty"] > 0
    assert ver["n_feasible"] > 0


def test_brute_force_matches_qubo_optimum():
    inst = build_qubo_instance(snapshot())
    ver = exhaustive_verification(inst)
    brute = classical_brute_force(inst)
    assert brute["best_score"] == ver["optimal_score"]


def test_greedy_is_feasible_and_bounded_by_optimum():
    inst = build_qubo_instance(snapshot())
    brute = classical_brute_force(inst)
    greedy = classical_greedy(inst)
    assert len(greedy["selection"]) == inst["k"]
    weights = [inst["weights"][i] for i in greedy["selection"]]
    assert len(weights) == len(set(weights))
    assert greedy["score"] <= brute["best_score"]


def test_optimal_selection_completes_to_valid_schedule():
    s = snapshot()
    inst = build_qubo_instance(s)
    ver = exhaustive_verification(inst)
    assert validator_agreement(s, ver["ground_states"][0])
