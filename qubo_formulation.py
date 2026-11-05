"""QUBO formulation of the simplified 4-team SINGLE round-robin problem.

This is the mathematical model approved in Phase 2A. No Qiskit here:
everything is plain Python so the model can be verified exhaustively
before any quantum code exists.

The problem
-----------
4 teams (A, B, C, D), 3 rounds, 6 unordered matchups. One binary decision
per (matchup, round):

    x[m, r] = 1  if matchup m is played in round r, else 0

giving 6 x 3 = 18 binary variables. An assignment of all 18 bits is encoded
as a single Python integer (bit i = variable i), so the full search space is
the integers 0 .. 2**18 - 1 (262,144 assignments).

The energy function (QUBO)
--------------------------
    H(x) = A * sum_m   (1 - sum_r x[m,r])**2          "each matchup once"
         + B * sum_t,r (1 - sum_{m contains t} x[m,r])**2
                                                      "each team once per round"

with A = B = 1. Every term is a square, so H >= 0 and H == 0 exactly when
the assignment is a valid single round-robin schedule.

Mirroring (classical post-processing)
-------------------------------------
A valid single round-robin (rounds 1-3) is deterministically extended to a
full DOUBLE round-robin (rounds 1-6):

  * rounds 1-3: the alphabetically first team of each pair is the home team
  * rounds 4-6: the same games repeated with home and away swapped

The result must satisfy the original Phase 1 validator unchanged.
"""

import itertools
import time

from schedule_validator import Game

TEAMS = ["A", "B", "C", "D"]
MATCHUPS: list[tuple[str, str]] = list(itertools.combinations(TEAMS, 2))
N_ROUNDS = 3  # single round-robin
N_VARS = len(MATCHUPS) * N_ROUNDS  # 18
N_ASSIGNMENTS = 2**N_VARS  # 262,144


def var_index(matchup_idx: int, round_idx: int) -> int:
    """Map (matchup 0-5, round 0-2) to a bit position 0-17."""
    return matchup_idx * N_ROUNDS + round_idx


def _constraint_groups() -> list[int]:
    """Each hard constraint as a bitmask over the 18 variables.

    A group's constraint reads: 'exactly ONE of the variables in this mask
    must be 1'. There are 6 matchup groups + 4 teams * 3 rounds = 18 groups.
    """
    groups: list[int] = []

    # Each matchup is played exactly once (in exactly one round).
    for m in range(len(MATCHUPS)):
        mask = 0
        for r in range(N_ROUNDS):
            mask |= 1 << var_index(m, r)
        groups.append(mask)

    # Each team plays exactly once in each round.
    for team in TEAMS:
        member_matchups = [
            m for m, pair in enumerate(MATCHUPS) if team in pair
        ]
        for r in range(N_ROUNDS):
            mask = 0
            for m in member_matchups:
                mask |= 1 << var_index(m, r)
            groups.append(mask)

    return groups


CONSTRAINT_GROUPS = _constraint_groups()


def energy(assignment: int) -> int:
    """H(x) computed directly from the constraint definition.

    For each group, count the set bits and add (1 - count)**2.
    Zero energy <=> valid single round-robin schedule.
    """
    total = 0
    for mask in CONSTRAINT_GROUPS:
        count = (assignment & mask).bit_count()
        total += (1 - count) ** 2
    return total


def build_qubo() -> tuple[int, dict[int, int], dict[tuple[int, int], int]]:
    """Expand the squared penalties into explicit QUBO coefficients.

    Returns (offset, linear, quadratic) such that

        H(x) = offset + sum_i linear[i]*x_i + sum_{i<j} quadratic[i,j]*x_i*x_j

    Derivation per group g with variables {x_1..x_k} (using x**2 == x for
    binary variables):

        (1 - sum x)**2 = 1 - 2*sum x_i + (sum x_i)**2
                       = 1 - 2*sum x_i + sum x_i + 2*sum_{i<j} x_i x_j
                       = 1 -   sum x_i          + 2*sum_{i<j} x_i x_j

    This coefficient form is what gets translated to an Ising Hamiltonian
    for QAOA in Phase 2B Part 2.
    """
    offset = 0
    linear: dict[int, int] = {}
    quadratic: dict[tuple[int, int], int] = {}

    for mask in CONSTRAINT_GROUPS:
        members = [i for i in range(N_VARS) if mask & (1 << i)]
        offset += 1
        for i in members:
            linear[i] = linear.get(i, 0) - 1
        for i, j in itertools.combinations(members, 2):
            key = (min(i, j), max(i, j))
            quadratic[key] = quadratic.get(key, 0) + 2

    return offset, linear, quadratic


def energy_from_qubo(assignment: int) -> int:
    """H(x) computed from the expanded QUBO coefficients.

    Used in tests to prove the algebraic expansion in build_qubo() matches
    the constraint-based energy() definition exactly.
    """
    offset, linear, quadratic = build_qubo()
    total = offset
    for i, coeff in linear.items():
        if assignment & (1 << i):
            total += coeff
    for (i, j), coeff in quadratic.items():
        if assignment & (1 << i) and assignment & (1 << j):
            total += coeff
    return total


def decode(assignment: int) -> dict[int, list[tuple[str, str]]]:
    """Turn an 18-bit assignment into {round (1-based): [matchups]}."""
    rounds: dict[int, list[tuple[str, str]]] = {
        r + 1: [] for r in range(N_ROUNDS)
    }
    for m, pair in enumerate(MATCHUPS):
        for r in range(N_ROUNDS):
            if assignment & (1 << var_index(m, r)):
                rounds[r + 1].append(pair)
    return rounds


def mirror_to_double_round_robin(assignment: int) -> list[Game]:
    """Deterministically extend a single round-robin to a double one.

    Home/away convention: in rounds 1-3 the alphabetically first team of
    each pair is home (MATCHUPS pairs are already alphabetical). Rounds 4-6
    replay rounds 1-3 with home and away swapped.
    """
    single = decode(assignment)
    games: list[Game] = []
    for r in range(1, N_ROUNDS + 1):
        for first, second in single[r]:
            games.append(Game(r, first, second))
            games.append(Game(r + N_ROUNDS, second, first))
    return games


def generate_single_rr_backtracking(
    teams: list[str],
) -> tuple[list[tuple[int, tuple[str, str]]] | None, float]:
    """Classical baseline: solve the SAME simplified problem by backtracking.

    Fills rounds one at a time with a set of unused matchups in which every
    team appears exactly once (a perfect matching). Returns
    (schedule as [(round, matchup), ...] or None, elapsed_seconds).
    """
    n_teams = len(teams)
    if n_teams % 2 != 0:
        raise ValueError("Number of teams must be even")
    matchups = list(itertools.combinations(teams, 2))
    n_rounds = n_teams - 1
    games_per_round = n_teams // 2

    schedule: list[tuple[int, tuple[str, str]]] = []
    used: set[tuple[str, str]] = set()

    def backtrack(round_number: int) -> bool:
        if round_number > n_rounds:
            return True
        available = [m for m in matchups if m not in used]
        for combo in itertools.combinations(available, games_per_round):
            involved = [t for pair in combo for t in pair]
            if len(set(involved)) != n_teams:
                continue
            for pair in combo:
                schedule.append((round_number, pair))
                used.add(pair)
            if backtrack(round_number + 1):
                return True
            for pair in combo:
                schedule.pop()
                used.remove(pair)
        return False

    start = time.perf_counter()
    found = backtrack(1)
    elapsed = time.perf_counter() - start
    return (schedule if found else None), elapsed


def single_rr_to_assignment(
    schedule: list[tuple[int, tuple[str, str]]],
) -> int:
    """Encode a [(round, matchup)] single round-robin as an 18-bit integer,
    so classical solutions can be scored by the same energy function."""
    assignment = 0
    for round_number, pair in schedule:
        m = MATCHUPS.index(pair)
        assignment |= 1 << var_index(m, round_number - 1)
    return assignment
