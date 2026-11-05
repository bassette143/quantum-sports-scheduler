"""Phase W4: QUBO feasibility study for wrestling mat-slot selection.

Why this problem?
-----------------
The Phase W3 greedy schedule already achieves the provable 20-slot lower
bound, so NO solver (classical or quantum) can shorten the tournament
under the current model. We therefore do NOT pose makespan reduction as
the quantum task. Instead we study the decision made at a single time
slot, with one ADDITIONAL realistic preference the W3 model ignored:

    At most one match per weight class should run simultaneously
    (tournaments commonly progress each weight class on one mat at a
    time, letting coaches, wrestlers, and spectators follow it).

The decision problem (one snapshot slot of the real tournament):

    From the pool of READY matches, select exactly k matches to run now
    (k = number of available mats, capped by the distinct weights in the
    pool) such that no two selected matches share a weight class, while
    MAXIMIZING bracket progression.

Progression score per match (measurable objective):
    u = 2 if completing the match immediately unlocks its parent match
        (its sibling feeder is a bye or already completed) or it is a
        bracket final;
    u = 1 otherwise.

QUBO (binary x_i = 1 if ready match i is selected):

    H(x) = A * (sum_i x_i - k)^2                       [exactly k matches]
         + B * sum_{i<j, same weight} x_i x_j          [one per weight]
         - C * sum_i u_i x_i                           [progression]

with C = 1 and A = B = (max possible score) + 1 so that no constraint
violation can ever be compensated by objective gain. Mats are identical,
so which selected match goes on which numbered mat is symmetric and left
to trivial classical post-processing - encoding (match x mat) variables
would only multiply qubits for no physical difference.

Everything here is classical mathematics: the model is verified
EXHAUSTIVELY (all 2^N assignments) and solved by classical baselines.
No Qiskit code, no QAOA - that is a later phase, pending approval.

Run:  python -m wrestling.mat_qubo
"""

import itertools
import json
import math
import time
from pathlib import Path

from wrestling.brackets import generate_all_brackets
from wrestling.mat_schedule import N_MATS, REST_SLOTS, schedule_matches
from wrestling.mat_validator import contested_slots, validate_mat_schedule
from wrestling.rosters import DEFAULT_SEED

MIN_POOL, MAX_POOL = 8, 16  # snapshot size bounds -> manageable qubit count


# ---------------------------------------------------------------------------
# Snapshot extraction from the real tournament
# ---------------------------------------------------------------------------

def ready_pool_at(jobs: dict, assignments: dict, t: int,
                  rest_slots: int = REST_SLOTS) -> list[str]:
    """Matches not yet run before slot t whose feeders finished early
    enough (greedy schedule replay)."""
    pool = []
    for mid, meta in jobs.items():
        if assignments[mid]["slot"] < t:
            continue  # already run earlier
        if all(
            assignments[fid]["slot"] + rest_slots < t
            for fid in meta["contested_feeders"]
        ):
            pool.append(mid)
    return sorted(pool)


def progression_score(mid: str, jobs: dict, assignments: dict, t: int) -> int:
    """2 if completing `mid` at slot t immediately unlocks its parent (or
    it is a final); 1 otherwise."""
    parent = next(
        (p for p, meta in jobs.items() if mid in meta["contested_feeders"]),
        None,
    )
    if parent is None:
        return 2  # bracket final: completing it crowns a champion
    siblings = [f for f in jobs[parent]["contested_feeders"] if f != mid]
    if all(assignments[s]["slot"] < t for s in siblings):
        return 2  # all other contested feeders already done (or none)
    return 1


def extract_snapshot(seed: int = DEFAULT_SEED) -> dict:
    """Deterministically pick the earliest slot whose ready pool fits the
    target qubit range, and build the selection instance."""
    bracket_data = generate_all_brackets(seed)
    jobs = contested_slots(bracket_data)
    assignments = schedule_matches(bracket_data, N_MATS, REST_SLOTS)
    makespan = max(a["slot"] for a in assignments.values())

    for t in range(1, makespan + 1):
        pool = ready_pool_at(jobs, assignments, t)
        if MIN_POOL <= len(pool) <= MAX_POOL:
            weights = {jobs[m]["weight"] for m in pool}
            k = min(N_MATS, len(weights), len(pool))
            return {
                "seed": seed,
                "slot": t,
                "pool": pool,
                "scores": {
                    m: progression_score(m, jobs, assignments, t)
                    for m in pool
                },
                "weights": {m: jobs[m]["weight"] for m in pool},
                "k": k,
                "n_variables": len(pool),
                "bracket_data": bracket_data,
                "jobs": jobs,
                "greedy_assignments": assignments,
            }
    raise RuntimeError(
        f"No slot has a ready pool of size {MIN_POOL}..{MAX_POOL}"
    )


# ---------------------------------------------------------------------------
# QUBO energy model
# ---------------------------------------------------------------------------

def build_qubo_instance(snapshot: dict) -> dict:
    """Penalty weights and index mappings for the snapshot instance."""
    pool = snapshot["pool"]
    scores = [snapshot["scores"][m] for m in pool]
    weights = [snapshot["weights"][m] for m in pool]
    k = snapshot["k"]
    # Max achievable objective: sum of the k largest scores.
    max_score = sum(sorted(scores, reverse=True)[:k])
    penalty = max_score + 1  # A = B: dominates any objective gain
    same_weight_pairs = [
        (i, j)
        for i, j in itertools.combinations(range(len(pool)), 2)
        if weights[i] == weights[j]
    ]
    return {
        "pool": pool,
        "scores": scores,
        "weights": weights,
        "k": k,
        "penalty_A": penalty,
        "penalty_B": penalty,
        "objective_C": 1,
        "same_weight_pairs": same_weight_pairs,
        "max_score": max_score,
    }


def qubo_energy(x: int, inst: dict) -> int:
    """H(x) for an N-bit selection encoded as an integer."""
    n = len(inst["pool"])
    bits = [(x >> i) & 1 for i in range(n)]
    cardinality = sum(bits)
    h = inst["penalty_A"] * (cardinality - inst["k"]) ** 2
    h += inst["penalty_B"] * sum(
        bits[i] * bits[j] for i, j in inst["same_weight_pairs"]
    )
    h -= inst["objective_C"] * sum(
        s * b for s, b in zip(inst["scores"], bits)
    )
    return h


def is_feasible(x: int, inst: dict) -> bool:
    """Hard constraints only: exactly k selected, one per weight class."""
    n = len(inst["pool"])
    bits = [(x >> i) & 1 for i in range(n)]
    if sum(bits) != inst["k"]:
        return False
    return all(
        not (bits[i] and bits[j]) for i, j in inst["same_weight_pairs"]
    )


def selection_score(x: int, inst: dict) -> int:
    n = len(inst["pool"])
    return sum(
        inst["scores"][i] for i in range(n) if (x >> i) & 1
    )


# ---------------------------------------------------------------------------
# Exhaustive verification and classical baselines
# ---------------------------------------------------------------------------

def exhaustive_verification(inst: dict) -> dict:
    """Check every 2^N assignment against the model's guarantees."""
    n = len(inst["pool"])
    start = time.perf_counter()
    feasible_energies, infeasible_min_penalty = [], None
    ground_energy, ground_states = None, []
    for x in range(2 ** n):
        e = qubo_energy(x, inst)
        feas = is_feasible(x, inst)
        if feas:
            feasible_energies.append(e)
            # Energy of a feasible state must be exactly -score.
            assert e == -selection_score(x, inst)
        else:
            pen = e + selection_score(x, inst)  # penalty part only
            if infeasible_min_penalty is None or pen < infeasible_min_penalty:
                infeasible_min_penalty = pen
        if ground_energy is None or e < ground_energy:
            ground_energy, ground_states = e, [x]
        elif e == ground_energy:
            ground_states.append(x)
    elapsed = time.perf_counter() - start

    best_feasible = min(feasible_energies)
    return {
        "n_assignments": 2 ** n,
        "n_feasible": len(feasible_energies),
        "ground_energy": ground_energy,
        "ground_states": ground_states,
        "all_ground_states_feasible": all(
            is_feasible(x, inst) for x in ground_states
        ),
        "ground_equals_best_feasible": ground_energy == best_feasible,
        "optimal_score": -ground_energy,
        "min_infeasible_penalty": infeasible_min_penalty,
        "enumeration_time_s": elapsed,
    }


def classical_brute_force(inst: dict) -> dict:
    """Optimal selection by enumerating k-subsets (the fair baseline)."""
    n = len(inst["pool"])
    start = time.perf_counter()
    best_score, best_subsets = -1, []
    for combo in itertools.combinations(range(n), inst["k"]):
        chosen = set(combo)
        if any(
            i in chosen and j in chosen
            for i, j in inst["same_weight_pairs"]
        ):
            continue
        score = sum(inst["scores"][i] for i in combo)
        if score > best_score:
            best_score, best_subsets = score, [combo]
        elif score == best_score:
            best_subsets.append(combo)
    elapsed = time.perf_counter() - start
    return {
        "best_score": best_score,
        "n_optimal_subsets": len(best_subsets),
        "example_subset": best_subsets[0] if best_subsets else None,
        "time_s": elapsed,
    }


def classical_greedy(inst: dict) -> dict:
    """Fast heuristic: take highest-score matches, one per weight."""
    start = time.perf_counter()
    order = sorted(
        range(len(inst["pool"])),
        key=lambda i: (-inst["scores"][i], i),
    )
    chosen, used_weights = [], set()
    for i in order:
        if len(chosen) == inst["k"]:
            break
        if inst["weights"][i] not in used_weights:
            chosen.append(i)
            used_weights.add(inst["weights"][i])
    elapsed = time.perf_counter() - start
    return {
        "score": sum(inst["scores"][i] for i in chosen),
        "selection": chosen,
        "time_s": elapsed,
    }


def validator_agreement(snapshot: dict, selection_bits: int) -> bool:
    """Complete the tournament schedule with this selection at the
    snapshot slot and confirm the INDEPENDENT validator accepts it."""
    jobs = snapshot["jobs"]
    greedy = snapshot["greedy_assignments"]
    t = snapshot["slot"]
    pool = snapshot["pool"]

    fixed: dict[str, dict] = {
        mid: dict(a) for mid, a in greedy.items() if a["slot"] < t
    }
    mat = 1
    for i, mid in enumerate(pool):
        if (selection_bits >> i) & 1:
            fixed[mid] = {"mat": mat, "slot": t}
            mat += 1

    # Greedy continuation for everything else (same rules as Phase W3).
    remaining = [m for m in jobs if m not in fixed]
    priority = sorted(
        remaining, key=lambda m: (jobs[m]["round"], jobs[m]["weight"], m)
    )
    finished = {m: a["slot"] for m, a in fixed.items()}
    tt = t
    while remaining:
        tt += 1
        mat = 1
        for mid in list(priority):
            if mid not in remaining or mat > N_MATS:
                continue
            if all(
                f in finished and finished[f] + 1 + REST_SLOTS <= tt
                for f in jobs[mid]["contested_feeders"]
            ):
                fixed[mid] = {"mat": mat, "slot": tt}
                finished[mid] = tt
                mat += 1
                remaining.remove(mid)

    result = validate_mat_schedule(
        snapshot["bracket_data"], fixed, N_MATS, REST_SLOTS
    )
    return result.is_valid


# ---------------------------------------------------------------------------
# Feasibility study report
# ---------------------------------------------------------------------------

def main(seed: int = DEFAULT_SEED) -> None:
    print("=== Phase W4: wrestling mat-selection QUBO feasibility study ===\n")

    snapshot = extract_snapshot(seed)
    inst = build_qubo_instance(snapshot)
    n = len(inst["pool"])
    # The cardinality penalty (sum x - k)^2 already couples EVERY pair, so
    # same-weight pairs only increase existing coefficients: the number of
    # distinct quadratic terms is C(n, 2), not C(n, 2) + same-weight pairs.
    n_quad = math.comb(n, 2)

    print(f"Snapshot: time slot {snapshot['slot']} of the real greedy schedule")
    print(f"Ready pool: {n} matches -> {n} binary variables = {n} qubits")
    print(f"Select k={inst['k']} (mats={N_MATS}, distinct weights="
          f"{len(set(inst['weights']))})")
    print(f"Penalties: A=B={inst['penalty_A']}, objective C=1")
    print(f"Distinct quadratic terms: {n_quad} (all pairs, from the "
          f"cardinality penalty; {len(inst['same_weight_pairs'])} of them "
          f"also carry the same-weight penalty)")
    print("Pool (match, weight, progression score):")
    for i, mid in enumerate(inst["pool"]):
        print(f"  x{i:>2}: {mid:<14} {inst['weights'][i]:>4} lbs  "
              f"u={inst['scores'][i]}")

    print("\nExhaustive verification over all assignments...")
    ver = exhaustive_verification(inst)
    print(f"  assignments checked: {ver['n_assignments']:,} "
          f"in {ver['enumeration_time_s']:.3f} s")
    print(f"  feasible selections: {ver['n_feasible']:,}")
    print(f"  ground energy: {ver['ground_energy']} "
          f"(optimal score {ver['optimal_score']})")
    print(f"  ground states: {len(ver['ground_states'])}, all feasible: "
          f"{ver['all_ground_states_feasible']}")
    print(f"  ground = best feasible: {ver['ground_equals_best_feasible']}")
    print(f"  min infeasible penalty: {ver['min_infeasible_penalty']} (> 0)")

    print("\nClassical baselines (identical problem):")
    brute = classical_brute_force(inst)
    greedy = classical_greedy(inst)
    print(f"  brute force: score {brute['best_score']} "
          f"({brute['n_optimal_subsets']} optimal subsets) "
          f"in {brute['time_s']*1000:.2f} ms")
    print(f"  greedy:      score {greedy['score']} "
          f"in {greedy['time_s']*1000:.3f} ms")

    print("\nIndependent validator agreement (ground states -> full schedule):")
    agree = all(
        validator_agreement(snapshot, g) for g in ver["ground_states"]
    )
    print(f"  all {len(ver['ground_states'])} optimal selections complete "
          f"to VALID tournament schedules: {agree}")

    checks = {
        "all_ground_states_feasible": ver["all_ground_states_feasible"],
        "ground_equals_best_feasible": ver["ground_equals_best_feasible"],
        "invalid_assignments_positively_penalized":
            (ver["min_infeasible_penalty"] or 0) > 0,
        "brute_force_matches_qubo_optimum":
            brute["best_score"] == ver["optimal_score"],
        "validator_accepts_all_optimal_selections": agree,
    }
    print("\nChecks:")
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")

    record = {
        "experiment": "wrestling_mat_qubo_feasibility_phase_w4",
        "settings": {
            "seed": seed, "n_mats": N_MATS, "rest_slots": REST_SLOTS,
            "snapshot_slot": snapshot["slot"],
            "objective": "maximize bracket progression (u in {1,2})",
            "added_constraint": "at most one match per weight class per slot",
        },
        "instance": {
            "pool": inst["pool"],
            "weights": inst["weights"],
            "scores": inst["scores"],
            "k": inst["k"],
            "n_variables": n,
            "n_qubits_required": n,
            "n_quadratic_terms": n_quad,
            "penalty_A": inst["penalty_A"],
            "penalty_B": inst["penalty_B"],
        },
        "verification": {k: v for k, v in ver.items() if k != "ground_states"},
        "n_ground_states": len(ver["ground_states"]),
        "classical_brute_force": {
            k: (list(v) if isinstance(v, tuple) else v)
            for k, v in brute.items()
        },
        "classical_greedy": greedy,
        "checks": checks,
        "all_checks_passed": all(checks.values()),
    }
    out = Path(__file__).parent.parent / "results" / "wrestling_qubo_feasibility.json"
    out.write_text(json.dumps(record, indent=2))
    print(f"\nResults saved to {out}")


if __name__ == "__main__":
    main()
