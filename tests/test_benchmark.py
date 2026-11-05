"""Tests for benchmark helpers (no full QAOA sweep is run here)."""

from benchmark import aggregate_depth, run_classical_baseline, run_random_baseline
from qubo_formulation import N_ASSIGNMENTS


def test_random_baseline_is_reproducible_and_scored_correctly():
    a = run_random_baseline(seed=123, shots=500)
    b = run_random_baseline(seed=123, shots=500)
    assert a["valid_shots"] == b["valid_shots"]
    assert a["best_energy"] == b["best_energy"]
    assert a["shots"] == 500
    assert a["best_energy"] >= 0
    assert 0.0 <= a["valid_percent"] <= 100.0


def test_classical_baseline_always_solves_same_problem():
    result = run_classical_baseline(repeats=10)
    assert result["same_problem_as_qubo"] is True
    assert result["all_runs_found_valid_zero_energy_solution"] is True
    assert result["min_time_s"] <= result["median_time_s"] <= result["max_time_s"]


def test_aggregate_depth_computes_time_to_valid():
    trials = [
        {
            "depth": 1, "seed": 1, "optimizer_iterations": 10,
            "valid_shots": 5, "valid_percent": 0.125, "best_energy": 0,
            "total_time_s": 2.0, "circuit_depth": 43, "two_qubit_gates": 108,
            "validator_confirmed": True,
        },
        {
            "depth": 1, "seed": 2, "optimizer_iterations": 12,
            "valid_shots": 0, "valid_percent": 0.0, "best_energy": 3,
            "total_time_s": 4.0, "circuit_depth": 43, "two_qubit_gates": 108,
            "validator_confirmed": True,
        },
    ]
    s = aggregate_depth(trials)
    assert s["successful_trials"] == 1
    # 6 s total across both trials / 1 successful trial
    assert abs(s["time_to_valid_including_failures_s"] - 6.0) < 1e-9
    assert s["best_energy_overall"] == 0
    assert abs(s["mean_valid_percent"] - 0.0625) < 1e-9


def test_aggregate_depth_handles_no_successes():
    trials = [
        {
            "depth": 2, "seed": 1, "optimizer_iterations": 10,
            "valid_shots": 0, "valid_percent": 0.0, "best_energy": 3,
            "total_time_s": 2.0, "circuit_depth": 78, "two_qubit_gates": 216,
            "validator_confirmed": True,
        },
    ]
    s = aggregate_depth(trials)
    assert s["successful_trials"] == 0
    assert s["time_to_valid_including_failures_s"] is None
