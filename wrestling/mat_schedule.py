"""Classical mat scheduler for the wrestling tournament (Phase W3).

Assigns every contested championship match from the Phase W2 brackets to a
(mat, time-slot) pair using deterministic greedy list scheduling:

  * Time advances in discrete slots 1, 2, 3, ...
  * In each slot, up to n_mats matches run simultaneously.
  * A match is READY when every contested match feeding it finished at
    least (1 + rest_slots) slots earlier - the feeder's winner needs rest.
    Round-1 matches are ready immediately; bye feeders impose no wait.
  * Ready matches are taken in a fixed priority order (round, then weight,
    then slot number), so the same input always yields the same schedule.

This is a heuristic (greedy is not guaranteed optimal), but every output
is checked by the INDEPENDENT validator in wrestling/mat_validator.py and
measured against the theoretical lower bound on the number of slots:

    max( ceil(total_matches / n_mats),  longest feeder chain with rest )

Defaults (approved for Phase W3): 6 mats, 1 slot minimum rest.

Run:  python -m wrestling.mat_schedule
"""

import json
import math
import time
from pathlib import Path

from wrestling.brackets import generate_all_brackets
from wrestling.mat_validator import contested_slots, validate_mat_schedule
from wrestling.rosters import DEFAULT_SEED

N_MATS = 6
REST_SLOTS = 1


def schedule_matches(
    bracket_data: dict,
    n_mats: int = N_MATS,
    rest_slots: int = REST_SLOTS,
) -> dict[str, dict]:
    """Greedy list scheduling. Returns {match_id: {"mat": m, "slot": t}}."""
    jobs = contested_slots(bracket_data)
    # Deterministic priority: earlier rounds first, then lighter weight,
    # then slot id (stable, human-predictable order).
    priority = sorted(
        jobs, key=lambda mid: (jobs[mid]["round"], jobs[mid]["weight"], mid)
    )

    assignments: dict[str, dict] = {}
    finished_at: dict[str, int] = {}
    t = 0
    while len(assignments) < len(jobs):
        t += 1
        mat = 1
        for mid in priority:
            if mid in assignments or mat > n_mats:
                continue
            ready = all(
                fid in finished_at and finished_at[fid] + 1 + rest_slots <= t
                for fid in jobs[mid]["contested_feeders"]
            )
            if ready:
                assignments[mid] = {"mat": mat, "slot": t}
                finished_at[mid] = t
                mat += 1
    return assignments


def longest_chain_with_rest(jobs: dict[str, dict], rest_slots: int) -> int:
    """Minimum slots needed by the deepest feeder chain alone."""
    memo: dict[str, int] = {}

    def depth(mid: str) -> int:
        if mid not in memo:
            feeders = jobs[mid]["contested_feeders"]
            memo[mid] = 1 + max(
                (depth(f) + rest_slots for f in feeders), default=0
            )
        return memo[mid]

    return max(depth(mid) for mid in jobs)


def schedule_statistics(
    bracket_data: dict,
    assignments: dict[str, dict],
    n_mats: int,
    rest_slots: int,
) -> dict:
    jobs = contested_slots(bracket_data)
    makespan = max(a["slot"] for a in assignments.values())
    lower_bound = max(
        math.ceil(len(jobs) / n_mats),
        longest_chain_with_rest(jobs, rest_slots),
    )
    used = len(assignments)
    return {
        "n_matches_scheduled": used,
        "n_mats": n_mats,
        "rest_slots": rest_slots,
        "makespan_slots": makespan,
        "theoretical_lower_bound_slots": lower_bound,
        "mat_slot_capacity": makespan * n_mats,
        "mat_utilization_percent": round(100 * used / (makespan * n_mats), 1),
    }


def display(stats: dict, validation, assignments: dict[str, dict]) -> None:
    print("=== Wrestling mat schedule (Phase W3, classical greedy) ===")
    print(f"Mats: {stats['n_mats']}  |  Min rest: {stats['rest_slots']} slot(s)\n")
    print(f"Matches scheduled:        {stats['n_matches_scheduled']}")
    print(f"Schedule length:          {stats['makespan_slots']} time slots")
    print(f"Theoretical lower bound:  {stats['theoretical_lower_bound_slots']} slots")
    print(f"Mat utilization:          {stats['mat_utilization_percent']}%")
    print(f"Independent validator:    {validation}")

    print("\nFirst two time slots (example):")
    for t in (1, 2):
        in_slot = sorted(
            (a["mat"], mid) for mid, a in assignments.items()
            if a["slot"] == t
        )
        row = "   ".join(f"mat{m}:{mid}" for m, mid in in_slot)
        print(f"  slot {t}: {row if row else '(empty)'}")


def main(seed: int = DEFAULT_SEED) -> None:
    bracket_data = generate_all_brackets(seed)

    start = time.perf_counter()
    assignments = schedule_matches(bracket_data, N_MATS, REST_SLOTS)
    elapsed = time.perf_counter() - start

    validation = validate_mat_schedule(
        bracket_data, assignments, N_MATS, REST_SLOTS
    )
    stats = schedule_statistics(bracket_data, assignments, N_MATS, REST_SLOTS)
    display(stats, validation, assignments)
    print(f"\nScheduling time (measured): {elapsed:.4f} s")

    record = {
        "experiment": "wrestling_mat_schedule_phase_w3",
        "settings": {
            "seed": seed,
            "n_mats": N_MATS,
            "rest_slots": REST_SLOTS,
            "algorithm": "deterministic greedy list scheduling (heuristic)",
        },
        "assignments": assignments,
        "statistics": stats,
        "is_valid": validation.is_valid,
        "violations": validation.violations,
        "scheduling_time_seconds": elapsed,
    }
    out_path = Path(__file__).parent.parent / "results" / "wrestling_mat_schedule.json"
    out_path.write_text(json.dumps(record, indent=2))
    print(f"Results saved to {out_path}")


if __name__ == "__main__":
    main()
