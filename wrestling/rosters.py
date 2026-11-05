"""Random roster generator and bracket statistics for a simulated high
school wrestling tournament (Phase W1).

Simulation rules:
  * 12 fictional schools ("School 1" .. "School 12").
  * 14 weight classes (sample labels, not verified competition rules).
  * At most one wrestler per school per weight class.
  * Roster sizes are random between 8 and 14, so every school is missing
    wrestlers in some randomly chosen weight classes.
  * Fully reproducible from a random seed (default 42).

Wrestlers are identified only as "<school> @ <weight>" - entirely
fictional, no names or personal information.

Important modeling note: a MISSING roster entry simply means that school
enters nobody in that weight class, so the weight class has fewer
entrants. That is NOT a forfeit. A forfeit would be a registered wrestler
failing to compete in a scheduled match; this simulation registers no
such events. The only non-contested "results" modeled here are BYES:
free passes awarded in round one because single-elimination brackets are
sized to the next power of two above the number of entrants.

This module does NOT schedule actual matches yet - it only generates
rosters and projects bracket statistics.

Run:  python -m wrestling.rosters
"""

import random
from dataclasses import dataclass, field

WEIGHT_CLASSES: list[int] = [
    106, 113, 120, 126, 132, 138, 145, 152, 160, 170, 182, 195, 220, 285,
]
N_SCHOOLS = 12
SCHOOL_NAMES: list[str] = [f"School {i}" for i in range(1, N_SCHOOLS + 1)]
MIN_ROSTER = 8
MAX_ROSTER = 14
DEFAULT_SEED = 42


@dataclass
class TeamRoster:
    """One school's roster: which weight classes it fills and misses."""

    school: str
    filled_weights: list[int] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.filled_weights)

    @property
    def missing_weights(self) -> list[int]:
        return sorted(set(WEIGHT_CLASSES) - set(self.filled_weights))


def generate_rosters(seed: int = DEFAULT_SEED) -> list[TeamRoster]:
    """Generate the 12 random team rosters, reproducibly from `seed`.

    For each school: pick a roster size in [8, 14], then sample that many
    distinct weight classes (which automatically enforces the
    one-wrestler-per-school-per-weight rule).
    """
    rng = random.Random(seed)
    rosters = []
    for school in SCHOOL_NAMES:
        size = rng.randint(MIN_ROSTER, MAX_ROSTER)
        filled = sorted(rng.sample(WEIGHT_CLASSES, size))
        rosters.append(TeamRoster(school=school, filled_weights=filled))
    return rosters


def next_power_of_two(n: int) -> int:
    """Smallest power of two >= n (defined for n >= 1)."""
    if n < 1:
        raise ValueError("next_power_of_two requires n >= 1")
    power = 1
    while power < n:
        power *= 2
    return power


def bracket_stats(entrants: int) -> dict:
    """Single-elimination championship bracket statistics for one weight.

    * 0 entrants: empty weight class - no bracket, no byes, no matches.
    * 1 entrant: champion by default (walkover) - no byes, no matches.
    * >= 2 entrants: bracket capacity is the next power of two;
        byes    = capacity - entrants (first-round free passes)
        matches = entrants - 1 (every contested single-elimination
                  tournament eliminates all but one wrestler, and each
                  match eliminates exactly one)
    """
    if entrants < 0:
        raise ValueError("entrants cannot be negative")
    if entrants == 0:
        return {"entrants": 0, "bracket_size": 0, "byes": 0, "matches": 0}
    if entrants == 1:
        return {"entrants": 1, "bracket_size": 1, "byes": 0, "matches": 0}
    size = next_power_of_two(entrants)
    return {
        "entrants": entrants,
        "bracket_size": size,
        "byes": size - entrants,
        "matches": entrants - 1,
    }


def tournament_statistics(rosters: list[TeamRoster]) -> dict:
    """All Phase W1 statistics for a set of rosters."""
    entrants_by_weight = {
        w: sum(1 for r in rosters if w in r.filled_weights)
        for w in WEIGHT_CLASSES
    }
    per_weight = {w: bracket_stats(n) for w, n in entrants_by_weight.items()}
    total_wrestlers = sum(r.size for r in rosters)
    total_positions = len(rosters) * len(WEIGHT_CLASSES)
    return {
        "total_schools": len(rosters),
        "total_wrestlers": total_wrestlers,
        "total_possible_positions": total_positions,
        "total_missing_positions": total_positions - total_wrestlers,
        "per_weight": per_weight,
        "total_byes": sum(s["byes"] for s in per_weight.values()),
        "total_matches": sum(s["matches"] for s in per_weight.values()),
    }


def display(rosters: list[TeamRoster], stats: dict) -> None:
    """Readable terminal report of rosters and bracket statistics."""
    print("=== Wrestling tournament simulation (Phase W1, seed-reproducible) ===")
    print("NOTE: rosters are fictional and randomly generated; weight class")
    print("labels are samples. This phase projects bracket statistics only -")
    print("no actual matches are scheduled yet.\n")

    print("Team Roster Summary")
    print(f"{'School':<12}{'Wrestlers':<11}Missing Weight Classes")
    print("-" * 78)
    for r in rosters:
        missing = ", ".join(str(w) for w in r.missing_weights) or "none"
        print(f"{r.school:<12}{r.size:<11}{missing}")

    print("\nWeight Class Summary (single-elimination championship bracket)")
    print(f"{'Weight':<8}{'Entrants':<10}{'Bracket Size':<14}{'Byes':<6}{'Matches':<8}")
    print("-" * 46)
    for w in WEIGHT_CLASSES:
        s = stats["per_weight"][w]
        print(
            f"{w:<8}{s['entrants']:<10}{s['bracket_size']:<14}"
            f"{s['byes']:<6}{s['matches']:<8}"
        )

    print("\nTournament totals")
    print(f"  Participating schools:          {stats['total_schools']}")
    print(f"  Registered wrestlers:           {stats['total_wrestlers']}")
    print(f"  Possible roster positions:      {stats['total_possible_positions']}")
    print(f"  Missing roster positions:       {stats['total_missing_positions']}")
    print(f"  First-round byes (all weights): {stats['total_byes']}")
    print(f"  Projected championship matches: {stats['total_matches']}")
    print("\n  (Missing roster entries reduce entrant counts; they are NOT")
    print("   forfeits. Byes are bracket free passes, not forfeited matches.)")


def main(seed: int = DEFAULT_SEED) -> None:
    rosters = generate_rosters(seed)
    stats = tournament_statistics(rosters)
    display(rosters, stats)


if __name__ == "__main__":
    main()
