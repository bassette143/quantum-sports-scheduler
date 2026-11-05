"""Classical scheduler for a double round-robin tournament.

Two things live here:

1. A manually written REFERENCE_SCHEDULE for the 4-team tournament
   (teams A, B, C, D) kept as a human-readable example.
2. An automatic backtracking generator that builds a valid schedule
   from scratch for any even number of teams.

Why backtracking? For a 4-team instance the search space is tiny, so an
exact, deterministic algorithm is the honest classical baseline: it either
finds a provably valid schedule or proves none exists. We deliberately do
NOT slow anything down - the recorded time is the real cost of solving the
problem classically.

Run directly to generate, validate, time, and save a schedule:

    python classical_scheduler.py
"""

import itertools
import json
import time
from pathlib import Path

from schedule_validator import Game, expected_counts, validate_schedule

TEAMS = ["A", "B", "C", "D"]

# Manually written example schedule (kept as a readable reference).
# 6 rounds x 2 games = 12 games; every ordered (home, away) pair once.
REFERENCE_SCHEDULE = [
    Game(1, "A", "B"), Game(1, "C", "D"),
    Game(2, "B", "C"), Game(2, "D", "A"),
    Game(3, "A", "C"), Game(3, "B", "D"),
    Game(4, "B", "A"), Game(4, "D", "C"),
    Game(5, "C", "B"), Game(5, "A", "D"),
    Game(6, "C", "A"), Game(6, "D", "B"),
]


def generate_schedule(teams: list[str]) -> list[Game] | None:
    """Build a valid double round-robin schedule using backtracking.

    We fill the schedule round by round. In each round we choose a set of
    ordered (home, away) pairs such that every team plays exactly once.
    A matchup may be used only once in the whole tournament. If a round
    cannot be completed, we backtrack and try a different combination.

    Returns the schedule, or None if no valid schedule exists.
    """
    n_teams = len(teams)
    if n_teams % 2 != 0:
        raise ValueError("Number of teams must be even")

    _, total_rounds, games_per_round = expected_counts(n_teams)

    # All ordered matchups that must appear exactly once in the tournament.
    all_matchups = [
        (h, a) for h, a in itertools.permutations(teams, 2)
    ]

    schedule: list[Game] = []
    used: set[tuple[str, str]] = set()

    def round_options(available: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
        """All ways to pick `games_per_round` matchups covering each team once."""
        options = []
        for combo in itertools.combinations(available, games_per_round):
            involved = [t for pair in combo for t in pair]
            if len(set(involved)) == n_teams:
                options.append(list(combo))
        return options

    def backtrack(round_number: int) -> bool:
        if round_number > total_rounds:
            return True
        available = [m for m in all_matchups if m not in used]
        for combo in round_options(available):
            for home, away in combo:
                schedule.append(Game(round_number, home, away))
                used.add((home, away))
            if backtrack(round_number + 1):
                return True
            # Undo this round's choices and try the next combination.
            for home, away in combo:
                schedule.pop()
                used.remove((home, away))
        return False

    found = backtrack(1)
    return schedule if found else None


def schedule_to_dict(schedule: list[Game]) -> list[dict]:
    """Convert a schedule to plain dictionaries for JSON storage."""
    return [
        {"round": g.round_number, "home": g.home, "away": g.away}
        for g in schedule
    ]


def print_schedule(schedule: list[Game]) -> None:
    rounds = sorted({g.round_number for g in schedule})
    for r in rounds:
        games = [g for g in schedule if g.round_number == r]
        line = "   ".join(f"{g.home} (home) vs {g.away}" for g in games)
        print(f"Round {r}: {line}")


def main() -> None:
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)

    print("=== Classical double round-robin scheduler ===")
    print(f"Teams: {TEAMS}\n")

    # 1. Validate the manually written reference schedule.
    ref_result = validate_schedule(REFERENCE_SCHEDULE, TEAMS)
    print("Reference (manually written) schedule:")
    print_schedule(REFERENCE_SCHEDULE)
    print(f"-> {ref_result}\n")

    # 2. Generate a schedule automatically and time it.
    start = time.perf_counter()
    generated = generate_schedule(TEAMS)
    elapsed = time.perf_counter() - start

    if generated is None:
        print("Backtracking found NO valid schedule.")
        gen_result = None
    else:
        print("Automatically generated schedule (backtracking):")
        print_schedule(generated)
        gen_result = validate_schedule(generated, TEAMS)
        print(f"-> {gen_result}")

    print(f"\nGeneration time: {elapsed:.6f} seconds")

    # 3. Save a reproducible record of this run.
    record = {
        "method": "classical_backtracking",
        "teams": TEAMS,
        "n_teams": len(TEAMS),
        "n_games": len(generated) if generated else 0,
        "n_rounds": expected_counts(len(TEAMS))[1],
        "solution_found": generated is not None,
        "is_valid": bool(gen_result and gen_result.is_valid),
        "violations": gen_result.violations if gen_result else [],
        "execution_time_seconds": elapsed,
        "schedule": schedule_to_dict(generated) if generated else [],
    }
    out_path = results_dir / "classical_result.json"
    out_path.write_text(json.dumps(record, indent=2))
    print(f"Result saved to {out_path}")


if __name__ == "__main__":
    main()
