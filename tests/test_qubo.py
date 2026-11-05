"""Tests for the QUBO formulation, mirroring, and classical baseline.

The expensive full-enumeration test runs here too (it is the heart of
Phase 2B Part 1), so the suite takes a few seconds rather than milliseconds.
"""

import itertools
import random

import pytest

from qubo_formulation import (
    MATCHUPS,
    N_ASSIGNMENTS,
    N_ROUNDS,
    N_VARS,
    TEAMS,
    build_qubo,
    decode,
    energy,
    energy_from_qubo,
    generate_single_rr_backtracking,
    mirror_to_double_round_robin,
    single_rr_to_assignment,
    var_index,
)
from schedule_validator import validate_schedule


# A known-valid single round-robin used by several tests:
#   R1: AB, CD   R2: AC, BD   R3: AD, BC
KNOWN_VALID = [
    (1, ("A", "B")), (1, ("C", "D")),
    (2, ("A", "C")), (2, ("B", "D")),
    (3, ("A", "D")), (3, ("B", "C")),
]


def known_valid_assignment() -> int:
    return single_rr_to_assignment(KNOWN_VALID)


# ---------- variable mapping ----------

def test_variable_count_is_18():
    assert N_VARS == 18
    assert len(MATCHUPS) == 6
    assert N_ROUNDS == 3
    assert N_ASSIGNMENTS == 262_144


def test_var_index_is_a_bijection():
    indices = {
        var_index(m, r)
        for m in range(len(MATCHUPS))
        for r in range(N_ROUNDS)
    }
    assert indices == set(range(N_VARS))


# ---------- energy function ----------

def test_known_valid_assignment_has_zero_energy():
    assert energy(known_valid_assignment()) == 0


def test_empty_assignment_has_positive_energy():
    # Nothing scheduled: all 18 'exactly one' constraints broken by 1 each.
    assert energy(0) == 18


def test_all_ones_assignment_has_positive_energy():
    assert energy(N_ASSIGNMENTS - 1) > 0


def test_single_swap_breaks_validity():
    # Move matchup AB from round 1 to round 2: A and B now play twice in
    # round 2 and never in round 1.
    valid = known_valid_assignment()
    m_ab = MATCHUPS.index(("A", "B"))
    broken = valid & ~(1 << var_index(m_ab, 0)) | (1 << var_index(m_ab, 1))
    assert energy(broken) > 0


def test_qubo_expansion_matches_constraint_energy():
    # The expanded coefficient form must agree with the direct definition
    # on valid, invalid, and random assignments.
    rng = random.Random(42)
    samples = [0, N_ASSIGNMENTS - 1, known_valid_assignment()]
    samples += [rng.randrange(N_ASSIGNMENTS) for _ in range(500)]
    for assignment in samples:
        assert energy(assignment) == energy_from_qubo(assignment)


def test_qubo_size_matches_phase2a_estimate():
    offset, linear, quadratic = build_qubo()
    assert offset == 18          # 18 constraint groups
    assert len(linear) == 18     # every variable appears in some group
    assert len(quadratic) == 54  # 6*3 matchup pairs + 12*3 team-round pairs


# ---------- exhaustive verification (the core Phase 2B-1 check) ----------

def test_exactly_six_zero_energy_assignments_exist():
    ground_states = [
        a for a in range(N_ASSIGNMENTS) if energy(a) == 0
    ]
    assert len(ground_states) == 6

    # Every ground state must decode to a valid single RR (each round is a
    # perfect matching, each matchup used once) and mirror to a schedule
    # accepted by the independent Phase 1 validator.
    for assignment in ground_states:
        single = decode(assignment)
        used = [pair for games in single.values() for pair in games]
        assert sorted(used) == sorted(MATCHUPS)
        for games in single.values():
            teams_in_round = [t for pair in games for t in pair]
            assert sorted(teams_in_round) == sorted(TEAMS)
        result = validate_schedule(
            mirror_to_double_round_robin(assignment), TEAMS
        )
        assert result.is_valid, result.violations


# ---------- mirroring ----------

def test_mirroring_known_valid_gives_valid_double_rr():
    games = mirror_to_double_round_robin(known_valid_assignment())
    assert len(games) == 12
    result = validate_schedule(games, TEAMS)
    assert result.is_valid, result.violations


def test_mirroring_swaps_home_and_away():
    games = mirror_to_double_round_robin(known_valid_assignment())
    first_half = {(g.home, g.away): g.round_number for g in games if g.round_number <= 3}
    second_half = {(g.home, g.away): g.round_number for g in games if g.round_number > 3}
    for (home, away), r in first_half.items():
        assert (away, home) in second_half
        assert second_half[(away, home)] == r + 3


# ---------- classical baseline ----------

def test_backtracking_baseline_solves_single_rr():
    schedule, elapsed = generate_single_rr_backtracking(TEAMS)
    assert schedule is not None
    assert elapsed >= 0
    assert energy(single_rr_to_assignment(schedule)) == 0


def test_backtracking_baseline_mirrors_to_valid_double_rr():
    schedule, _ = generate_single_rr_backtracking(TEAMS)
    assert schedule is not None
    assignment = single_rr_to_assignment(schedule)
    result = validate_schedule(mirror_to_double_round_robin(assignment), TEAMS)
    assert result.is_valid, result.violations


def test_backtracking_baseline_rejects_odd_team_count():
    with pytest.raises(ValueError):
        generate_single_rr_backtracking(["A", "B", "C"])
