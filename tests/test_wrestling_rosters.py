"""Tests for the wrestling roster generator and bracket statistics."""

import pytest

from wrestling.rosters import (
    MAX_ROSTER,
    MIN_ROSTER,
    N_SCHOOLS,
    SCHOOL_NAMES,
    WEIGHT_CLASSES,
    bracket_stats,
    generate_rosters,
    next_power_of_two,
    tournament_statistics,
)


# ---------- roster generation ----------

def test_exactly_twelve_schools():
    rosters = generate_rosters(seed=42)
    assert len(rosters) == 12 == N_SCHOOLS
    assert [r.school for r in rosters] == SCHOOL_NAMES


def test_roster_sizes_between_8_and_14():
    for seed in (42, 0, 1, 99):
        for r in generate_rosters(seed=seed):
            assert MIN_ROSTER <= r.size <= MAX_ROSTER


def test_no_school_has_two_wrestlers_in_same_weight():
    for seed in (42, 7, 123):
        for r in generate_rosters(seed=seed):
            assert len(r.filled_weights) == len(set(r.filled_weights))


def test_all_assigned_weights_are_valid():
    valid = set(WEIGHT_CLASSES)
    for r in generate_rosters(seed=42):
        assert set(r.filled_weights) <= valid


def test_same_seed_reproduces_identical_rosters():
    a = generate_rosters(seed=42)
    b = generate_rosters(seed=42)
    assert [(r.school, r.filled_weights) for r in a] == [
        (r.school, r.filled_weights) for r in b
    ]


def test_different_seeds_give_different_rosters():
    a = generate_rosters(seed=42)
    b = generate_rosters(seed=43)
    assert [r.filled_weights for r in a] != [r.filled_weights for r in b]


def test_missing_weights_complement_filled_weights():
    for r in generate_rosters(seed=42):
        assert sorted(r.filled_weights + r.missing_weights) == WEIGHT_CLASSES


# ---------- tournament statistics ----------

def test_missing_positions_counted_correctly():
    rosters = generate_rosters(seed=42)
    stats = tournament_statistics(rosters)
    assert stats["total_possible_positions"] == 12 * 14 == 168
    assert stats["total_wrestlers"] == sum(r.size for r in rosters)
    assert (
        stats["total_missing_positions"]
        == 168 - stats["total_wrestlers"]
        == sum(len(r.missing_weights) for r in rosters)
    )


def test_per_weight_entrants_sum_to_total_wrestlers():
    rosters = generate_rosters(seed=42)
    stats = tournament_statistics(rosters)
    assert (
        sum(s["entrants"] for s in stats["per_weight"].values())
        == stats["total_wrestlers"]
    )


def test_entrants_never_exceed_school_count():
    stats = tournament_statistics(generate_rosters(seed=42))
    for s in stats["per_weight"].values():
        assert 0 <= s["entrants"] <= N_SCHOOLS


# ---------- bracket mathematics ----------

def test_next_power_of_two():
    assert next_power_of_two(1) == 1
    assert next_power_of_two(2) == 2
    assert next_power_of_two(3) == 4
    assert next_power_of_two(8) == 8
    assert next_power_of_two(9) == 16
    assert next_power_of_two(12) == 16
    with pytest.raises(ValueError):
        next_power_of_two(0)


def test_bracket_sizes_and_byes():
    assert bracket_stats(12) == {
        "entrants": 12, "bracket_size": 16, "byes": 4, "matches": 11,
    }
    assert bracket_stats(8) == {
        "entrants": 8, "bracket_size": 8, "byes": 0, "matches": 7,
    }
    assert bracket_stats(9) == {
        "entrants": 9, "bracket_size": 16, "byes": 7, "matches": 8,
    }


def test_single_elimination_matches_equal_entrants_minus_one():
    for entrants in range(1, 13):
        assert bracket_stats(entrants)["matches"] == entrants - 1


def test_edge_cases_zero_and_one_entrant():
    assert bracket_stats(0) == {
        "entrants": 0, "bracket_size": 0, "byes": 0, "matches": 0,
    }
    # One entrant: champion by walkover - no bye needed, no match wrestled.
    assert bracket_stats(1) == {
        "entrants": 1, "bracket_size": 1, "byes": 0, "matches": 0,
    }
    with pytest.raises(ValueError):
        bracket_stats(-1)


def test_total_matches_consistent_with_per_weight():
    stats = tournament_statistics(generate_rosters(seed=42))
    assert stats["total_matches"] == sum(
        s["matches"] for s in stats["per_weight"].values()
    )
    assert stats["total_byes"] == sum(
        s["byes"] for s in stats["per_weight"].values()
    )
