"""Independent validator for wrestling mat schedules (Phase W3).

Knows nothing about HOW a mat schedule was produced. Checks a proposed
assignment of contested matches to (mat, time-slot) pairs against the
hard scheduling rules:

  1. Every contested match (match/placeholder slot in the brackets) is
     scheduled exactly once; no unknown match ids are scheduled.
  2. Mats are within range and time slots are positive integers.
  3. A mat hosts at most one match per time slot.
  4. Bracket order with rest: a match must start at least
     (1 + rest_slots) slots after every contested match that feeds it
     (the feeder's winner needs the rest). Bye feeders impose no wait.
  5. No wrestler KNOWN to be in two matches (round-1 entrants and
     bye-advanced participants) is booked twice in the same time slot.

An assignment is a mapping: match_id -> {"mat": int, "slot": int}.
"""

from dataclasses import dataclass, field


@dataclass
class MatValidationResult:
    is_valid: bool
    violations: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        if self.is_valid:
            return "VALID mat schedule (all hard constraints satisfied)"
        lines = [f"INVALID mat schedule ({len(self.violations)} violation(s)):"]
        lines += [f"  - {v}" for v in self.violations]
        return "\n".join(lines)


def contested_slots(bracket_data: dict) -> dict[str, dict]:
    """All contested bracket slots (type match/placeholder) by id, with
    their contested feeders and known participants."""
    slots: dict[str, dict] = {}
    for bracket in bracket_data["brackets"].values():
        by_id = {
            s["id"]: s for rnd in bracket["rounds"] for s in rnd["slots"]
        }
        for s in by_id.values():
            if s["type"] == "bye":
                continue
            if s["type"] == "match":
                feeders, known = [], [w for w in s["wrestlers"]]
            else:  # placeholder
                feeders = [
                    fid for fid in s["fed_by"]
                    if by_id[fid]["type"] != "bye"
                ]
                known = [p for p in s["participants"] if p is not None]
            slots[s["id"]] = {
                "weight": bracket["weight"],
                "round": s["round"],
                "contested_feeders": feeders,
                "known_participants": known,
            }
    return slots


def validate_mat_schedule(
    bracket_data: dict,
    assignments: dict[str, dict],
    n_mats: int,
    rest_slots: int,
) -> MatValidationResult:
    violations: list[str] = []
    expected = contested_slots(bracket_data)

    # --- 1. Exactly the contested matches, each scheduled once ---
    missing = set(expected) - set(assignments)
    unknown = set(assignments) - set(expected)
    if missing:
        violations.append(f"Unscheduled matches: {sorted(missing)}")
    if unknown:
        violations.append(f"Unknown scheduled ids: {sorted(unknown)}")

    # --- 2. Mats and slots in range ---
    for mid, a in assignments.items():
        if not (1 <= a["mat"] <= n_mats):
            violations.append(f"{mid}: mat {a['mat']} outside 1..{n_mats}")
        if a["slot"] < 1:
            violations.append(f"{mid}: slot {a['slot']} is not positive")

    # --- 3. One match per (mat, slot) ---
    seen: dict[tuple[int, int], str] = {}
    for mid in sorted(assignments):
        key = (assignments[mid]["mat"], assignments[mid]["slot"])
        if key in seen:
            violations.append(
                f"Mat {key[0]} slot {key[1]}: double-booked "
                f"({seen[key]} and {mid})"
            )
        else:
            seen[key] = mid

    # --- 4. Bracket order + rest ---
    for mid, meta in expected.items():
        if mid not in assignments:
            continue
        t = assignments[mid]["slot"]
        for fid in meta["contested_feeders"]:
            if fid not in assignments:
                continue
            tf = assignments[fid]["slot"]
            if t < tf + 1 + rest_slots:
                violations.append(
                    f"{mid} (slot {t}) starts too soon after feeder "
                    f"{fid} (slot {tf}); needs >= {tf + 1 + rest_slots}"
                )

    # --- 5. Known wrestlers not double-booked in one slot ---
    busy: dict[tuple[str, int, int], str] = {}
    for mid in sorted(assignments):
        if mid not in expected:
            continue
        t = assignments[mid]["slot"]
        weight = expected[mid]["weight"]
        for wrestler in expected[mid]["known_participants"]:
            key = (wrestler, weight, t)
            if key in busy:
                violations.append(
                    f"Slot {t}: {wrestler} ({weight} lbs) booked in both "
                    f"{busy[key]} and {mid}"
                )
            else:
                busy[key] = mid

    return MatValidationResult(is_valid=not violations, violations=violations)
