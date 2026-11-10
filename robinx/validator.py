"""Independent hard-constraint validator for RobinX (ITC2021) timetables.

Semantics follow the ITC2021 problem description (OrganizationITC2021_V7.pdf,
section 2.4). Where the manual leaves details open, this validator follows the
QOBLIB reference model (05-sports/misc/itc2mip.py):

* A team has a *break* in slot s (s >= 1) when its home/away status in slot
  s-1 equals its status in slot s. Slot 0 can never contain a break.
* CA4 counts x[i,j] (mode1 = "H"), x[j,i] (mode1 = "A") or both ("HA") over
  i in teams1, j in teams2, i != j.

Supported hard constraints: CA4, GA1, BR1, BR2, plus the structural
requirements of a time-constrained (compact) double round-robin, phased or
not. Everything else is listed in ``ValidationReport.unsupported`` with a
reason and is never silently skipped. A schedule counts as *fully verified*
only if the structure is valid, every checked constraint is satisfied, and no
hard constraint was unsupported.

QOBLIB's quantum benchmark ignores soft constraints. Any soft constraints are
listed in ``ValidationReport.soft_ignored``.
"""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from robinx.parser import (
    Constraint,
    Game,
    Instance,
    parse_id_list,
    parse_instance,
    parse_meetings,
    parse_solution,
)

SUPPORTED_TAGS = ("CA4", "GA1", "BR1", "BR2")
_GROUP_ATTRS = ("teamGroups", "teamGroups1", "teamGroups2", "slotGroups")


@dataclass
class ConstraintResult:
    label: str
    tag: str
    deviation: int
    details: list[str] = field(default_factory=list)

    @property
    def satisfied(self) -> bool:
        return self.deviation == 0


@dataclass
class ValidationReport:
    instance_name: str
    structure_violations: list[str] = field(default_factory=list)
    results: list[ConstraintResult] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    soft_ignored: list[str] = field(default_factory=list)

    @property
    def violated(self) -> list[ConstraintResult]:
        return [r for r in self.results if not r.satisfied]

    @property
    def checked_constraints_satisfied(self) -> bool:
        """True if the structure is valid and every *checked* hard constraint holds."""
        return not self.structure_violations and not self.violated

    @property
    def fully_verified(self) -> bool:
        """True only if every hard constraint was checked and all of them hold."""
        return self.checked_constraints_satisfied and not self.unsupported

    def summary_by_tag(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for r in self.results:
            entry = out.setdefault(r.tag, {"checked": 0, "violated": 0, "deviation": 0})
            entry["checked"] += 1
            entry["violated"] += 0 if r.satisfied else 1
            entry["deviation"] += r.deviation
        return out

    def __str__(self) -> str:
        lines = [f"RobinX validation: {self.instance_name}"]
        lines.append(
            "  Structure (compact double round-robin): "
            + ("VALID" if not self.structure_violations else f"{len(self.structure_violations)} violation(s)")
        )
        lines += [f"    - {v}" for v in self.structure_violations]
        for tag, s in sorted(self.summary_by_tag().items()):
            lines.append(
                f"  {tag}: {s['checked']} checked, {s['violated']} violated "
                f"(total deviation {s['deviation']})"
            )
        for r in self.violated:
            lines.append(f"    - {r.label}: deviation {r.deviation}; " + "; ".join(r.details))
        lines.append(f"  Unsupported hard constraints: {len(self.unsupported)}")
        lines += [f"    - {u}" for u in self.unsupported]
        if self.soft_ignored:
            lines.append(f"  Soft constraints ignored (not part of QOBLIB feasibility benchmark): {len(self.soft_ignored)}")
        if self.fully_verified:
            verdict = "FULLY VERIFIED: every hard constraint checked and satisfied"
        elif self.checked_constraints_satisfied:
            verdict = "NOT FULLY VERIFIED: checked constraints hold, but some hard constraints are unsupported"
        else:
            verdict = "INFEASIBLE: violations found"
        lines.append(f"  Verdict: {verdict}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Support checks
# ---------------------------------------------------------------------------

def unsupported_reason(c: Constraint, instance: Instance) -> str | None:
    """Return why a hard constraint cannot be validated, or None if supported."""
    a = c.attrs
    if c.tag not in SUPPORTED_TAGS:
        return f"constraint type {c.tag} is not implemented"
    for g in _GROUP_ATTRS:
        if a.get(g):
            return f"uses {g}={a[g]!r}; group references are not supported"
    try:
        team_ids = set()
        for key in ("teams", "teams1", "teams2"):
            team_ids |= set(parse_id_list(a.get(key)))
        for h, aw in parse_meetings(a.get("meetings")):
            team_ids |= {h, aw}
        slot_ids = set(parse_id_list(a.get("slots")))
    except ValueError as exc:
        return f"could not parse attribute lists ({exc})"
    if not team_ids <= set(instance.teams):
        return f"references unknown team ids {sorted(team_ids - set(instance.teams))}"
    if not slot_ids <= set(instance.slots):
        return f"references unknown slot ids {sorted(slot_ids - set(instance.slots))}"

    if c.tag == "CA4":
        if int(a.get("min", "0")) != 0:
            return "CA4 with min > 0 is not defined in the ITC2021 manual"
        if a.get("mode1") not in ("H", "A", "HA"):
            return f"unknown CA4 mode1={a.get('mode1')!r}"
        if a.get("mode2") not in ("GLOBAL", "EVERY"):
            return f"unknown CA4 mode2={a.get('mode2')!r}"
    elif c.tag == "BR1":
        if a.get("mode1", "LEQ") != "LEQ":
            return f"unknown BR1 mode1={a.get('mode1')!r}"
        if a.get("mode2") not in ("H", "A", "HA"):
            return f"unknown BR1 mode2={a.get('mode2')!r}"
    elif c.tag == "BR2":
        if a.get("homeMode") != "HA":
            return f"unknown BR2 homeMode={a.get('homeMode')!r}"
        if a.get("mode2") != "LEQ":
            return f"unknown BR2 mode2={a.get('mode2')!r}"
    return None


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

def check_structure(instance: Instance, games: list[Game]) -> list[str]:
    """Time-constrained double round-robin checks (and phasing when gameMode = P)."""
    v: list[str] = []
    teams, slots = set(instance.teams), set(instance.slots)

    for h, a, s in games:
        if h not in teams or a not in teams:
            v.append(f"game ({h},{a}) in slot {s} uses an unknown team")
        if s not in slots:
            v.append(f"game ({h},{a}) uses unknown slot {s}")
        if h == a:
            v.append(f"team {h} plays itself in slot {s}")

    if len(games) != instance.n_games:
        v.append(f"expected {instance.n_games} games, found {len(games)}")

    pair_counts = Counter((h, a) for h, a, _ in games)
    for h in instance.teams:
        for a in instance.teams:
            if h != a and pair_counts[(h, a)] != 1:
                v.append(f"game ({h} home, {a} away) appears {pair_counts[(h, a)]} times, expected 1")

    for s in instance.slots:
        played = Counter()
        for h, a, gs in games:
            if gs == s:
                played[h] += 1
                played[a] += 1
        for t in instance.teams:
            if played[t] != 1:
                v.append(f"team {t} plays {played[t]} games in slot {s}, expected 1 (compact timetable)")

    if instance.game_mode == "P":
        half = set(sorted(instance.slots)[: len(instance.slots) // 2])
        first_half = Counter(frozenset((h, a)) for h, a, s in games if s in half)
        for i in instance.teams:
            for j in instance.teams:
                if i < j and first_half[frozenset((i, j))] != 1:
                    v.append(
                        f"phased: teams {i} and {j} meet {first_half[frozenset((i, j))]} times "
                        f"in the first half, expected 1"
                    )
    elif instance.game_mode != "NULL":
        v.append(f"unknown gameMode {instance.game_mode!r}")
    return v


# ---------------------------------------------------------------------------
# Constraint checks
# ---------------------------------------------------------------------------

def _venue(instance: Instance, games: list[Game]) -> dict[tuple[int, int], str]:
    """(team, slot) -> 'H' or 'A'."""
    status: dict[tuple[int, int], str] = {}
    for h, a, s in games:
        status.setdefault((h, s), "H")
        status.setdefault((a, s), "A")
    return status


def _breaks(status, team: int, slot: int) -> tuple[int, int]:
    """(home break, away break) for team in slot; slot 0 never has a break."""
    if slot == 0:
        return 0, 0
    prev, cur = status.get((team, slot - 1)), status.get((team, slot))
    if prev is None or cur is None or prev != cur:
        return 0, 0
    return (1, 0) if cur == "H" else (0, 1)


def check_ca4(c: Constraint, games: list[Game]) -> ConstraintResult:
    a = c.attrs
    t1, t2 = set(parse_id_list(a["teams1"])), set(parse_id_list(a["teams2"]))
    slots, mx, mode1 = parse_id_list(a["slots"]), int(a["max"]), a["mode1"]

    def count(slot_set: set[int]) -> int:
        n = 0
        for h, aw, s in games:
            if s not in slot_set:
                continue
            if mode1 in ("H", "HA") and h in t1 and aw in t2:
                n += 1
            if mode1 in ("A", "HA") and aw in t1 and h in t2:
                n += 1
        return n

    details, dev = [], 0
    if a["mode2"] == "GLOBAL":
        k = count(set(slots))
        dev = max(0, k - mx)
        if dev:
            details.append(f"{k} {mode1}-games of teams {sorted(t1)} vs {sorted(t2)} in slots {sorted(slots)} > max {mx}")
    else:  # EVERY
        for s in sorted(slots):
            k = count({s})
            if k > mx:
                dev += k - mx
                details.append(f"slot {s}: {k} {mode1}-games > max {mx}")
    return ConstraintResult(c.label, c.tag, dev, details)


def check_ga1(c: Constraint, games: list[Game]) -> ConstraintResult:
    a = c.attrs
    meetings = parse_meetings(a["meetings"])
    slots = set(parse_id_list(a["slots"]))
    mn, mx = int(a.get("min", "0")), int(a["max"])
    k = sum(1 for h, aw, s in games if s in slots for m in meetings if m == (h, aw))
    dev = max(0, mn - k) + max(0, k - mx)
    details = [f"{k} of games {meetings} in slots {sorted(slots)}, allowed {mn}..{mx}"] if dev else []
    return ConstraintResult(c.label, c.tag, dev, details)


def check_br1(c: Constraint, status) -> ConstraintResult:
    a = c.attrs
    teams, slots = parse_id_list(a["teams"]), parse_id_list(a["slots"])
    intp, mode2 = int(a["intp"]), a["mode2"]
    dev, details = 0, []
    for t in teams:
        n = 0
        for s in slots:
            hb, ab = _breaks(status, t, s)
            n += (hb if mode2 in ("H", "HA") else 0) + (ab if mode2 in ("A", "HA") else 0)
        if n > intp:
            dev += n - intp
            details.append(f"team {t} has {n} {mode2}-breaks in slots {sorted(slots)} > {intp}")
    return ConstraintResult(c.label, c.tag, dev, details)


def check_br2(c: Constraint, status) -> ConstraintResult:
    a = c.attrs
    teams, slots, intp = parse_id_list(a["teams"]), parse_id_list(a["slots"]), int(a["intp"])
    total = sum(sum(_breaks(status, t, s)) for t in teams for s in slots)
    dev = max(0, total - intp)
    details = [f"{total} breaks for teams {sorted(teams)} > {intp}"] if dev else []
    return ConstraintResult(c.label, c.tag, dev, details)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def validate(instance: Instance, games: list[Game]) -> ValidationReport:
    report = ValidationReport(instance_name=instance.name)

    if instance.number_round_robin != 2 or instance.compactness != "C":
        report.unsupported.append(
            f"format numberRoundRobin={instance.number_round_robin}, compactness="
            f"{instance.compactness}: only compact double round-robins are supported"
        )
    report.structure_violations = check_structure(instance, games)
    status = _venue(instance, games)

    for c in instance.constraints:
        if not c.is_hard:
            if c.type == "SOFT":
                report.soft_ignored.append(c.label)
            else:
                report.unsupported.append(f"{c.label}: unknown constraint type attribute {c.type!r}")
            continue
        reason = unsupported_reason(c, instance)
        if reason:
            report.unsupported.append(f"{c.label}: {reason}")
            continue
        if c.tag == "CA4":
            report.results.append(check_ca4(c, games))
        elif c.tag == "GA1":
            report.results.append(check_ga1(c, games))
        elif c.tag == "BR1":
            report.results.append(check_br1(c, status))
        elif c.tag == "BR2":
            report.results.append(check_br2(c, status))
    return report


DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "robinx"


def main(argv: list[str] | None = None) -> int:
    """Print a validation report. Reads files only; writes nothing."""
    argv = sys.argv[1:] if argv is None else argv
    inst_path = Path(argv[0]) if argv else DATA_DIR / "Addition_000_Small.xml.gz"
    sol_path = Path(argv[1]) if len(argv) > 1 else DATA_DIR / "Addition_000_Small.solution.xml.gz"
    instance = parse_instance(inst_path)
    solution = parse_solution(sol_path)
    print(f"Instance: {inst_path.name} ({instance.n_teams} teams, {instance.n_slots} slots, "
          f"gameMode {instance.game_mode})")
    print(f"Solution: {sol_path.name} ({len(solution.games)} games)\n")
    report = validate(instance, solution.games)
    print(report)
    return 0 if report.fully_verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
