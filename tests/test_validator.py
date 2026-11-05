"""Tests for the independent schedule validator.

Each test either feeds the validator a correct schedule (must be accepted)
or deliberately breaks ONE constraint (must be rejected with a matching
violation message).
"""

from classical_scheduler import REFERENCE_SCHEDULE, TEAMS
from schedule_validator import Game, expected_counts, validate_schedule


def test_reference_schedule_is_valid():
    result = validate_schedule(REFERENCE_SCHEDULE, TEAMS)
    assert result.is_valid, result.violations


def test_expected_counts_for_four_teams():
    total_games, total_rounds, games_per_round = expected_counts(4)
    assert total_games == 12
    assert total_rounds == 6
    assert games_per_round == 2


def test_rejects_wrong_number_of_games():
    schedule = REFERENCE_SCHEDULE[:-1]  # drop one game -> only 11 games
    result = validate_schedule(schedule, TEAMS)
    assert not result.is_valid
    assert any("Expected 12 games" in v for v in result.violations)


def test_rejects_missing_round():
    # Move round 6's games into round 5 -> round 6 missing, round 5 overloaded.
    schedule = [
        Game(5, g.home, g.away) if g.round_number == 6 else g
        for g in REFERENCE_SCHEDULE
    ]
    result = validate_schedule(schedule, TEAMS)
    assert not result.is_valid
    assert any("Missing rounds: [6]" in v for v in result.violations)


def test_rejects_team_playing_twice_in_same_round():
    # Round 1 becomes A vs B and A vs D -> A plays twice, C idle.
    schedule = list(REFERENCE_SCHEDULE)
    schedule[1] = Game(1, "A", "D")
    result = validate_schedule(schedule, TEAMS)
    assert not result.is_valid
    assert any("plays more than one game" in v for v in result.violations)
    assert any("do not play" in v for v in result.violations)


def test_rejects_duplicate_home_away_matchup():
    # Replace "C vs D" with a second "A vs B" in a different round.
    schedule = list(REFERENCE_SCHEDULE)
    schedule[1] = Game(1, "C", "D")  # keep round 1 intact
    schedule[11] = Game(6, "A", "B")  # duplicates round 1's A vs B
    result = validate_schedule(schedule, TEAMS)
    assert not result.is_valid
    assert any("Duplicate matchup: A (home) vs B" in v for v in result.violations)


def test_rejects_missing_matchup():
    # Removing a game means one ordered pair never happens.
    schedule = [g for g in REFERENCE_SCHEDULE if not (g.home == "C" and g.away == "A")]
    result = validate_schedule(schedule, TEAMS)
    assert not result.is_valid
    assert any("Missing matchup: C (home) vs A" in v for v in result.violations)


def test_rejects_team_playing_itself():
    schedule = list(REFERENCE_SCHEDULE)
    schedule[0] = Game(1, "A", "A")
    result = validate_schedule(schedule, TEAMS)
    assert not result.is_valid
    assert any("plays itself" in v for v in result.violations)


def test_rejects_unknown_team():
    schedule = list(REFERENCE_SCHEDULE)
    schedule[0] = Game(1, "A", "Z")
    result = validate_schedule(schedule, TEAMS)
    assert not result.is_valid
    assert any("unknown team" in v for v in result.violations)


def test_reports_all_violations_not_just_first():
    schedule = REFERENCE_SCHEDULE[:4]  # massively incomplete schedule
    result = validate_schedule(schedule, TEAMS)
    assert not result.is_valid
    assert len(result.violations) > 1
