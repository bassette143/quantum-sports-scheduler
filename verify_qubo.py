"""Exhaustive verification of the 18-variable QUBO model.

Checks, by enumerating ALL 2**18 = 262,144 assignments:

  1. Exactly 6 assignments have zero energy (the 6 valid single
     round-robin schedules for 4 teams). Each round must be a perfect
     matching of the 4 teams, and there are exactly 3 of them
     ({AB,CD}, {AC,BD}, {AD,BC}). A single round-robin uses each matching
     once, so the only freedom is the order of the 3 rounds: 3! = 6.
  2. Every zero-energy assignment decodes to a valid 3-round single
     round-robin and, after deterministic mirroring, passes the ORIGINAL
     Phase 1 double round-robin validator unchanged.
  3. Every other assignment has strictly positive energy.

Also runs the classical backtracking baseline on the same simplified
problem and records real measured runtimes for both.

Run:  python verify_qubo.py
"""

import json
import time
from pathlib import Path

from qubo_formulation import (
    MATCHUPS,
    N_ASSIGNMENTS,
    N_VARS,
    TEAMS,
    decode,
    energy,
    generate_single_rr_backtracking,
    mirror_to_double_round_robin,
    single_rr_to_assignment,
)
from schedule_validator import validate_schedule


def enumerate_ground_states() -> tuple[list[int], int, float]:
    """Score every assignment. Returns (zero-energy assignments,
    minimum nonzero energy, elapsed seconds)."""
    ground_states: list[int] = []
    min_nonzero = None
    start = time.perf_counter()
    for assignment in range(N_ASSIGNMENTS):
        e = energy(assignment)
        if e == 0:
            ground_states.append(assignment)
        elif min_nonzero is None or e < min_nonzero:
            min_nonzero = e
    elapsed = time.perf_counter() - start
    return ground_states, min_nonzero, elapsed


def main() -> None:
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)

    print("=== QUBO brute-force verification ===")
    print(f"Variables: {N_VARS}  |  Assignments to check: {N_ASSIGNMENTS:,}\n")

    # --- 1. Exhaustive enumeration (timed) ---
    ground_states, min_nonzero, enum_time = enumerate_ground_states()
    print(f"Enumeration time (measured): {enum_time:.3f} s")
    print(f"Zero-energy assignments found: {len(ground_states)} (expected 6)")
    print(f"Minimum nonzero energy: {min_nonzero} (must be > 0)\n")

    # --- 2. Validate every ground state through the Phase 1 validator ---
    all_mirrored_valid = True
    for idx, assignment in enumerate(ground_states, start=1):
        single = decode(assignment)
        double = mirror_to_double_round_robin(assignment)
        result = validate_schedule(double, TEAMS)
        status = "VALID" if result.is_valid else "INVALID"
        if not result.is_valid:
            all_mirrored_valid = False
        rounds_text = "; ".join(
            f"R{r}: " + ", ".join(f"{a}-{b}" for a, b in games)
            for r, games in single.items()
        )
        print(f"Ground state {idx}: {rounds_text}")
        print(f"  -> mirrored to 6 rounds: {status}")
        if not result.is_valid:
            for v in result.violations:
                print(f"     violation: {v}")
    print()

    # --- 3. Classical backtracking baseline on the SAME problem (timed) ---
    baseline, backtrack_time = generate_single_rr_backtracking(TEAMS)
    baseline_ok = baseline is not None
    baseline_energy = None
    baseline_mirror_valid = False
    if baseline is not None:
        baseline_assignment = single_rr_to_assignment(baseline)
        baseline_energy = energy(baseline_assignment)
        mirror_result = validate_schedule(
            mirror_to_double_round_robin(baseline_assignment), TEAMS
        )
        baseline_mirror_valid = mirror_result.is_valid
    print("Classical backtracking baseline (same simplified problem):")
    print(f"  Solution found: {baseline_ok}")
    print(f"  Energy of solution: {baseline_energy} (expected 0)")
    print(f"  Mirrored schedule valid: {baseline_mirror_valid}")
    print(f"  Backtracking time (measured): {backtrack_time:.6f} s\n")

    # --- Verdict ---
    checks = {
        "exactly_six_ground_states": len(ground_states) == 6,
        "all_other_assignments_positive_energy": (min_nonzero or 0) > 0,
        "all_mirrored_schedules_pass_phase1_validator": all_mirrored_valid,
        "backtracking_solution_found": baseline_ok,
        "backtracking_solution_has_zero_energy": baseline_energy == 0,
        "backtracking_mirrored_schedule_valid": baseline_mirror_valid,
    }
    all_passed = all(checks.values())
    print("Checks:")
    for name, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    print(f"\nOverall: {'ALL CHECKS PASSED' if all_passed else 'FAILURES FOUND'}")

    record = {
        "experiment": "qubo_brute_force_verification",
        "teams": TEAMS,
        "n_matchups": len(MATCHUPS),
        "n_rounds_single_rr": 3,
        "n_binary_variables": N_VARS,
        "n_assignments_checked": N_ASSIGNMENTS,
        "n_zero_energy_assignments": len(ground_states),
        "zero_energy_assignments": ground_states,
        "min_nonzero_energy": min_nonzero,
        "enumeration_time_seconds": enum_time,
        "backtracking_time_seconds": backtrack_time,
        "checks": checks,
        "all_checks_passed": all_passed,
    }
    out_path = results_dir / "qubo_verification.json"
    out_path.write_text(json.dumps(record, indent=2))
    print(f"Results saved to {out_path}")


if __name__ == "__main__":
    main()
