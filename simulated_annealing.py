"""Simulated annealing solver for the verified 18-variable scheduling QUBO.

Third solver family in the comparison (after classical backtracking and
QAOA). Simulated annealing (SA) is a classical heuristic that explores the
same energy landscape QAOA samples from:

  1. Start from a random 18-bit assignment.
  2. Propose a neighbor by flipping ONE randomly chosen bit.
  3. Always accept the neighbor if its energy is lower or equal; accept a
     HIGHER-energy neighbor with the Metropolis probability
     exp(-delta_E / T). This controlled willingness to go uphill is what
     lets SA escape local minima.
  4. Slowly lower the temperature T (geometric cooling: T <- T * rate), so
     the search gradually shifts from exploration to exploitation.
  5. Stop early as soon as a zero-energy (valid) schedule is found, or
     after a fixed iteration budget.

The energy function is the UNCHANGED, exhaustively verified
qubo_formulation.energy(). Every zero-energy solution is mirrored to a
double round-robin and checked by the independent Phase 1 validator.

NumPy is used only for its seedable random generator (already a project
dependency via Qiskit).

Run a quick demonstration:  python simulated_annealing.py
"""

import math
import time

import numpy as np

from qubo_formulation import (
    N_ASSIGNMENTS,
    N_VARS,
    TEAMS,
    energy,
    mirror_to_double_round_robin,
)
from schedule_validator import validate_schedule

DEFAULT_MAX_ITERATIONS = 50_000
DEFAULT_INITIAL_TEMPERATURE = 3.0
DEFAULT_COOLING_RATE = 0.9995


def metropolis_accept(delta: float, temperature: float, rng) -> bool:
    """Metropolis criterion: always accept improvements; accept a worse
    candidate with probability exp(-delta / T)."""
    if delta <= 0:
        return True
    if temperature <= 0:
        return False
    return rng.random() < math.exp(-delta / temperature)


def run_simulated_annealing(
    seed: int = 0,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    initial_temperature: float = DEFAULT_INITIAL_TEMPERATURE,
    cooling_rate: float = DEFAULT_COOLING_RATE,
    initial_assignment: int | None = None,
) -> dict:
    """One independent, reproducible simulated annealing run.

    Returns a dict with the best assignment/energy found, iteration and
    energy-evaluation counts, measured runtimes, and (when a valid
    schedule was found) confirmation from the independent validator.
    """
    rng = np.random.default_rng(seed)
    start = time.perf_counter()

    if initial_assignment is None:
        current = int(rng.integers(0, N_ASSIGNMENTS))
    else:
        if not 0 <= initial_assignment < N_ASSIGNMENTS:
            raise ValueError("initial_assignment out of range")
        current = initial_assignment

    current_energy = energy(current)
    energy_evaluations = 1
    best, best_energy = current, current_energy
    time_to_valid = time.perf_counter() - start if best_energy == 0 else None

    temperature = initial_temperature
    iterations = 0

    while iterations < max_iterations and best_energy != 0:
        iterations += 1

        # Neighbor: flip one random bit.
        bit = int(rng.integers(0, N_VARS))
        candidate = current ^ (1 << bit)
        candidate_energy = energy(candidate)
        energy_evaluations += 1

        if metropolis_accept(
            candidate_energy - current_energy, temperature, rng
        ):
            current, current_energy = candidate, candidate_energy
            if current_energy < best_energy:
                best, best_energy = current, current_energy
                if best_energy == 0:  # early termination on valid schedule
                    time_to_valid = time.perf_counter() - start

        temperature *= cooling_rate

    elapsed = time.perf_counter() - start

    found = best_energy == 0
    validator_confirmed = False
    if found:
        result = validate_schedule(mirror_to_double_round_robin(best), TEAMS)
        validator_confirmed = result.is_valid

    return {
        "method": "simulated_annealing",
        "seed": seed,
        "settings": {
            "max_iterations": max_iterations,
            "initial_temperature": initial_temperature,
            "cooling_rate": cooling_rate,
        },
        "found_valid_solution": found,
        "best_assignment": best,
        "best_energy": best_energy,
        "final_energy": current_energy,
        "iterations_used": iterations,
        "energy_evaluations": energy_evaluations,
        "time_s": elapsed,
        "time_to_valid_s": time_to_valid,
        "validator_confirmed": validator_confirmed,
    }


def main() -> None:
    print("=== Simulated annealing demonstration (one run, seed 0) ===")
    result = run_simulated_annealing(seed=0)
    for key in (
        "found_valid_solution",
        "best_energy",
        "iterations_used",
        "energy_evaluations",
        "time_s",
        "time_to_valid_s",
        "validator_confirmed",
    ):
        print(f"  {key}: {result[key]}")


if __name__ == "__main__":
    main()
