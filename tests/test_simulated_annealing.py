"""Tests for the simulated annealing solver.

No test hard-codes a successful annealing outcome: success-dependent
assertions apply only when a run actually reports success.
"""

import pytest

from qubo_formulation import (
    N_ASSIGNMENTS,
    energy,
    single_rr_to_assignment,
)
from simulated_annealing import metropolis_accept, run_simulated_annealing

KNOWN_VALID = [
    (1, ("A", "B")), (1, ("C", "D")),
    (2, ("A", "C")), (2, ("B", "D")),
    (3, ("A", "D")), (3, ("B", "C")),
]


class FakeRng:
    """Deterministic stand-in for numpy Generator.random()."""

    def __init__(self, value: float):
        self.value = value

    def random(self) -> float:
        return self.value


# ---------- Metropolis acceptance behavior ----------

def test_accepts_all_improvements_and_ties():
    rng = FakeRng(0.999999)  # draw is irrelevant for delta <= 0
    assert metropolis_accept(-5.0, 1.0, rng)
    assert metropolis_accept(0.0, 1.0, rng)
    assert metropolis_accept(-1.0, 0.0, rng)  # even at zero temperature


def test_rejects_uphill_at_zero_temperature():
    assert not metropolis_accept(1.0, 0.0, FakeRng(0.0))


def test_uphill_acceptance_matches_metropolis_probability():
    # exp(-3/3) = exp(-1) ~ 0.3679: draws below are accepted, above rejected.
    assert metropolis_accept(3.0, 3.0, FakeRng(0.30))
    assert not metropolis_accept(3.0, 3.0, FakeRng(0.40))


# ---------- reproducibility ----------

def test_same_seed_gives_identical_run():
    a = run_simulated_annealing(seed=7, max_iterations=2000)
    b = run_simulated_annealing(seed=7, max_iterations=2000)
    for key in (
        "best_assignment", "best_energy", "final_energy",
        "iterations_used", "energy_evaluations", "found_valid_solution",
    ):
        assert a[key] == b[key]


def test_different_seeds_explore_differently():
    a = run_simulated_annealing(seed=1, max_iterations=500)
    b = run_simulated_annealing(seed=2, max_iterations=500)
    # Extremely unlikely to visit identical best assignments; the point is
    # that the seed controls the trajectory.
    assert (a["best_assignment"], a["iterations_used"]) != (
        b["best_assignment"], b["iterations_used"],
    )


# ---------- energy evaluation and state validity ----------

def test_best_energy_matches_qubo_energy_of_best_assignment():
    result = run_simulated_annealing(seed=3, max_iterations=1000)
    assert result["best_energy"] == energy(result["best_assignment"])
    assert 0 <= result["best_assignment"] < N_ASSIGNMENTS


def test_known_valid_schedule_scores_zero_and_terminates_immediately():
    valid = single_rr_to_assignment(KNOWN_VALID)
    result = run_simulated_annealing(seed=0, initial_assignment=valid)
    assert result["found_valid_solution"] is True
    assert result["best_energy"] == 0
    assert result["iterations_used"] == 0  # early termination before any flip
    assert result["energy_evaluations"] == 1
    assert result["validator_confirmed"] is True
    assert result["time_to_valid_s"] is not None


def test_rejects_out_of_range_initial_assignment():
    with pytest.raises(ValueError):
        run_simulated_annealing(seed=0, initial_assignment=N_ASSIGNMENTS)


# ---------- early termination and bookkeeping ----------

def test_early_termination_stops_before_budget_when_successful():
    result = run_simulated_annealing(seed=5)
    if result["found_valid_solution"]:
        assert result["iterations_used"] < result["settings"]["max_iterations"]
        assert result["best_energy"] == 0
        assert result["validator_confirmed"] is True
    else:  # no success: full budget must have been used
        assert result["iterations_used"] == result["settings"]["max_iterations"]
        assert result["best_energy"] > 0


def test_energy_evaluation_count_is_iterations_plus_initial():
    result = run_simulated_annealing(seed=9, max_iterations=300)
    assert result["energy_evaluations"] == result["iterations_used"] + 1
