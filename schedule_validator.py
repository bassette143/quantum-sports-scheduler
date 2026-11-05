"""Independent schedule validator for a double round-robin tournament.

This module knows nothing about HOW a schedule was produced (classical or
quantum). It only checks whether a proposed schedule satisfies the hard
constraints of a double round-robin tournament:

  1. Every pair of teams meets exactly twice: once at each team's home venue
     (i.e. every ordered (home, away) pair appears exactly once).
  2. Each team plays exactly one game per round.
  3. Every round contains exactly n_teams / 2 games.
  4. The tournament has exactly n_teams * (n_teams - 1) games in total and
     2 * (n_teams - 1) rounds.
  5. No team plays against itself.

A schedule is represented as a list of games, where each game is a
(round, home, away) tuple. Rounds are numbered starting from 1.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Game:
    """One game: `home` hosts `away` in round `round_number` (1-based)."""

    round_number: int
    home: str
    away: str


@dataclass
class ValidationResult:
    """Outcome of validating a schedule.

    `is_valid` is True only when there are zero violations.
    `violations` holds one human-readable message per broken constraint.
    """

    is_valid: bool
    violations: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        if self.is_valid:
            return "VALID schedule (all hard constraints satisfied)"
        lines = [f"INVALID schedule ({len(self.violations)} violation(s)):"]
        lines += [f"  - {v}" for v in self.violations]
        return "\n".join(lines)


def expected_counts(n_teams: int) -> tuple[int, int, int]:
    """Return (total_games, total_rounds, games_per_round) for a double
    round-robin with `n_teams` teams (n_teams must be even)."""
    total_games = n_teams * (n_teams - 1)
    total_rounds = 2 * (n_teams - 1)
    games_per_round = n_teams // 2
    return total_games, total_rounds, games_per_round


def validate_schedule(schedule: list[Game], teams: list[str]) -> ValidationResult:
    """Check every hard constraint and report ALL violations found."""
    violations: list[str] = []
    n_teams = len(teams)
    team_set = set(teams)
    total_games, total_rounds, games_per_round = expected_counts(n_teams)

    # --- Constraint: only known teams, and no team plays itself ---
    for game in schedule:
        if game.home not in team_set or game.away not in team_set:
            violations.append(
                f"Round {game.round_number}: unknown team in game "
                f"{game.home} vs {game.away}"
            )
        if game.home == game.away:
            violations.append(
                f"Round {game.round_number}: team {game.home} plays itself"
            )

    # --- Constraint: correct total number of games ---
    if len(schedule) != total_games:
        violations.append(
            f"Expected {total_games} games, found {len(schedule)}"
        )

    # --- Constraint: correct rounds (1..total_rounds, each with the right size) ---
    rounds_present = {g.round_number for g in schedule}
    expected_rounds = set(range(1, total_rounds + 1))
    missing = expected_rounds - rounds_present
    extra = rounds_present - expected_rounds
    if missing:
        violations.append(f"Missing rounds: {sorted(missing)}")
    if extra:
        violations.append(f"Unexpected round numbers: {sorted(extra)}")

    for r in sorted(rounds_present & expected_rounds):
        games_in_round = [g for g in schedule if g.round_number == r]
        if len(games_in_round) != games_per_round:
            violations.append(
                f"Round {r}: expected {games_per_round} games, "
                f"found {len(games_in_round)}"
            )
        # --- Constraint: each team plays at most once per round ---
        seen: set[str] = set()
        for g in games_in_round:
            for team in (g.home, g.away):
                if team in seen:
                    violations.append(
                        f"Round {r}: team {team} plays more than one game"
                    )
                seen.add(team)
        # --- Constraint: each team plays exactly once per round ---
        idle = team_set - seen
        if idle and len(games_in_round) == games_per_round:
            violations.append(f"Round {r}: team(s) {sorted(idle)} do not play")

    # --- Constraint: every ordered (home, away) pair appears exactly once ---
    pair_counts: dict[tuple[str, str], int] = {}
    for g in schedule:
        pair_counts[(g.home, g.away)] = pair_counts.get((g.home, g.away), 0) + 1

    for home in teams:
        for away in teams:
            if home == away:
                continue
            count = pair_counts.get((home, away), 0)
            if count == 0:
                violations.append(f"Missing matchup: {home} (home) vs {away}")
            elif count > 1:
                violations.append(
                    f"Duplicate matchup: {home} (home) vs {away} "
                    f"appears {count} times"
                )

    return ValidationResult(is_valid=not violations, violations=violations)
