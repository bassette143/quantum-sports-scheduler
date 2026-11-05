"""Tests for the classical backtracking schedule generator."""

import pytest

from classical_scheduler import TEAMS, generate_schedule
from schedule_validator import expected_counts, validate_schedule


def test_generated_schedule_is_valid_for_four_teams():
    schedule = generate_schedule(TEAMS)
    assert schedule is not None, "Backtracking should find a schedule for 4 teams"
    result = validate_schedule(schedule, TEAMS)
    assert result.is_valid, result.violations


def test_generated_schedule_has_correct_size():
    schedule = generate_schedule(TEAMS)
    assert schedule is not None
    total_games, total_rounds, games_per_round = expected_counts(len(TEAMS))
    assert len(schedule) == total_games == 12
    rounds = {g.round_number for g in schedule}
    assert rounds == set(range(1, total_rounds + 1))
    for r in rounds:
        assert sum(1 for g in schedule if g.round_number == r) == games_per_round


def test_each_matchup_occurs_twice_with_home_away_reversed():
    schedule = generate_schedule(TEAMS)
    assert schedule is not None
    ordered_pairs = {(g.home, g.away) for g in schedule}
    for i, home in enumerate(TEAMS):
        for away in TEAMS[i + 1:]:
            assert (home, away) in ordered_pairs
            assert (away, home) in ordered_pairs


def test_generator_works_for_six_teams():
    teams = ["A", "B", "C", "D", "E", "F"]
    schedule = generate_schedule(teams)
    assert schedule is not None
    result = validate_schedule(schedule, teams)
    assert result.is_valid, result.violations


def test_generator_rejects_odd_team_count():
    with pytest.raises(ValueError):
        generate_schedule(["A", "B", "C"])
