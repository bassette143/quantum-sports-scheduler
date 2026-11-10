"""Tests for the RobinX parser and hard-constraint validator.

Three layers:
1. Official QOBLIB data (Addition_000_Small, 8 teams): provenance checksums,
   parsing, and verification of the published feasible solution.
2. Real-data negatives: small mutations of the official solution that keep
   the double round-robin structure valid but break a specific constraint of
   each supported type (CA4, GA1, BR1, BR2), plus structural mutations.
3. Hand-checkable 4-team cases that pin the exact semantics of each
   constraint and confirm that unsupported constraints are reported.
"""

import hashlib
from pathlib import Path

import pytest

from robinx.parser import (
    parse_instance,
    parse_instance_xml,
    parse_meetings,
    parse_mip_solution,
    parse_solution,
)
from robinx.validator import main, validate

DATA = Path(__file__).resolve().parent.parent / "data" / "robinx"
INSTANCE = DATA / "Addition_000_Small.xml.gz"
SOLUTION_XML = DATA / "Addition_000_Small.solution.xml.gz"
SOLUTION_SOL = DATA / "Addition_000_Small.opt.sol"

CHECKSUMS = {
    INSTANCE: "d118db22bb0bf98c308e9137004775d3de80c4ae5742677a0d759ffe93392870",
    SOLUTION_XML: "920b9b76015cb371da0bd2e2a57b5963f336cd8f0984f99093dfcc94fbd65f96",
    SOLUTION_SOL: "ea1fd7b954ffe94fb800cc92ea990be09597562462c85a316eead96d76532abf",
}


@pytest.fixture(scope="module")
def instance():
    return parse_instance(INSTANCE)


@pytest.fixture(scope="module")
def official_games():
    return parse_solution(SOLUTION_XML).games


def flip_pair(games, i, j):
    """Swap home/away for BOTH meetings of teams i and j (structure stays valid)."""
    return [(a, h, s) if {h, a} == {i, j} else (h, a, s) for h, a, s in games]


def violated_labels(report):
    return {r.label: r for r in report.violated}


# ---------------------------------------------------------------------------
# 1. Official data
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", list(CHECKSUMS))
def test_vendored_files_match_recorded_checksums(path):
    assert hashlib.sha256(path.read_bytes()).hexdigest() == CHECKSUMS[path]


def test_instance_structure(instance):
    assert instance.name == "Additional_0_Small8.xml"
    assert instance.teams == list(range(8))
    assert instance.slots == list(range(14))
    assert (instance.number_round_robin, instance.compactness, instance.game_mode) == (2, "C", "P")
    assert instance.n_games == 56


def test_constraint_inventory(instance):
    counts = {}
    for c in instance.constraints:
        counts[c.tag] = counts.get(c.tag, 0) + 1
        assert c.is_hard
    assert counts == {"CA4": 85, "GA1": 31, "BR1": 44, "BR2": 1}


def test_both_official_solution_files_agree():
    xml_sol = parse_solution(SOLUTION_XML)
    mip_sol = parse_mip_solution(SOLUTION_SOL)
    assert len(xml_sol.games) == 56
    assert sorted(xml_sol.games) == sorted(mip_sol.games)
    assert xml_sol.metadata["ObjectiveValue"]["infeasibility"] == "0"
    assert mip_sol.metadata["objective"] == "0"


def test_official_solution_is_fully_verified(instance, official_games):
    report = validate(instance, official_games)
    assert report.structure_violations == []
    assert report.unsupported == []
    assert report.soft_ignored == []
    assert report.violated == []
    assert report.fully_verified
    summary = report.summary_by_tag()
    assert {t: s["checked"] for t, s in summary.items()} == {"CA4": 85, "GA1": 31, "BR1": 44, "BR2": 1}


def test_cli_reports_fully_verified(capsys):
    assert main([str(INSTANCE), str(SOLUTION_XML)]) == 0
    assert "FULLY VERIFIED" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 2. Real-data negatives
# ---------------------------------------------------------------------------

def test_real_ga1_violation_detected(instance, official_games):
    # GA1#23 forbids game (1 home, 3 away) in slot 5. The official solution
    # has (3, 1) in slot 5; flipping the pair creates the forbidden game.
    report = validate(instance, flip_pair(official_games, 1, 3))
    assert report.structure_violations == []
    v = violated_labels(report)
    assert "GA1#23" in v and v["GA1#23"].deviation == 1
    assert not report.fully_verified


def test_real_ca4_violation_detected(instance, official_games):
    # CA4#45 (EVERY, slot 9): teams {1, 7} host at most 1 game. Flipping
    # pair 0-1 makes team 1 host in slot 9 alongside team 7.
    report = validate(instance, flip_pair(official_games, 0, 1))
    assert report.structure_violations == []
    v = violated_labels(report)
    assert "CA4#45" in v and v["CA4#45"].deviation == 1
    assert "slot 9: 2 H-games > max 1" in v["CA4#45"].details


def test_real_br1_violation_detected(instance, official_games):
    # BR1#7: team 0 has at most 2 breaks in slots {1,2,6,9,10,12}. Flipping
    # pair 0-1 adds breaks at slots 6 and 9 (3 in total).
    report = validate(instance, flip_pair(official_games, 0, 1))
    v = violated_labels(report)
    assert "BR1#7" in v and v["BR1#7"].deviation == 1
    assert "team 0 has 3 HA-breaks" in v["BR1#7"].details[0]


def test_real_br2_violation_detected(instance, official_games):
    # BR2#0: at most 26 breaks in total. Flipping pair 0-1 gives 28.
    report = validate(instance, flip_pair(official_games, 0, 1))
    v = violated_labels(report)
    assert "BR2#0" in v and v["BR2#0"].deviation == 2


def test_missing_game_is_structural_violation(instance, official_games):
    report = validate(instance, official_games[1:])
    assert any("expected 56 games" in s for s in report.structure_violations)
    assert not report.fully_verified


def test_team_twice_in_slot_detected(instance, official_games):
    h, a, s = official_games[0]
    other_slot = next(gs for gh, ga, gs in official_games if gs != s)
    moved = [(h, a, other_slot)] + official_games[1:]
    report = validate(instance, moved)
    assert any("expected 1 (compact timetable)" in s for s in report.structure_violations)


def test_phase_violation_detected(instance, official_games):
    # Swapping slot 0 (first half) with slot 7 (second half) keeps the
    # timetable compact but moves meetings across the half-season boundary.
    swapped = [(h, a, 7 if s == 0 else 0 if s == 7 else s) for h, a, s in official_games]
    report = validate(instance, swapped)
    assert any(s.startswith("phased:") for s in report.structure_violations)


def test_self_play_detected(instance, official_games):
    h, a, s = official_games[0]
    report = validate(instance, [(h, h, s)] + official_games[1:])
    assert any("plays itself" in s for s in report.structure_violations)


# ---------------------------------------------------------------------------
# 3. Hand-checkable 4-team cases
# ---------------------------------------------------------------------------
# Phased compact double round-robin, teams 0-3, slots 0-5:
#   s0: (0,1) (2,3)   s1: (2,0) (3,1)   s2: (0,3) (1,2)
#   s3: (1,0) (3,2)   s4: (0,2) (1,3)   s5: (3,0) (2,1)
# Venues: t0 HAHAHA (0 breaks)   t1 AAHHHA (s1 away, s3 home, s4 home)
#         t2 HHAAAH (s1 home, s3 away, s4 away)   t3 AHAHAH (0 breaks)
# Total breaks: 6.

TINY_GAMES = [
    (0, 1, 0), (2, 3, 0), (2, 0, 1), (3, 1, 1), (0, 3, 2), (1, 2, 2),
    (1, 0, 3), (3, 2, 3), (0, 2, 4), (1, 3, 4), (3, 0, 5), (2, 1, 5),
]
ALL = "0;1;2;3;4;5"


def tiny_instance(constraints: str = "", n_rr: int = 2, compact: str = "C", mode: str = "P"):
    teams = "".join(f'<team id="{i}" league="0" name="T{i}"/>' for i in range(4))
    slots = "".join(f'<slot id="{i}" name="S{i}"/>' for i in range(6))
    xml = (
        "<Instance><MetaData><InstanceName>tiny</InstanceName></MetaData>"
        f"<Structure><Format leagueIds=\"0\"><numberRoundRobin>{n_rr}</numberRoundRobin>"
        f"<compactness>{compact}</compactness><gameMode>{mode}</gameMode></Format></Structure>"
        f"<Resources><Teams>{teams}</Teams><Slots>{slots}</Slots></Resources>"
        f"<Constraints><Misc>{constraints}</Misc></Constraints></Instance>"
    )
    return parse_instance_xml(xml.encode())


def check_one(constraint_xml: str):
    report = validate(tiny_instance(constraint_xml), TINY_GAMES)
    assert report.structure_violations == [] and report.unsupported == []
    assert len(report.results) == 1
    return report.results[0]


def test_tiny_schedule_is_valid_with_no_constraints():
    report = validate(tiny_instance(), TINY_GAMES)
    assert report.fully_verified


def test_parse_meetings_handles_trailing_separator():
    assert parse_meetings("1,4;4,3;") == [(1, 4), (4, 3)]
    assert parse_meetings("") == []


@pytest.mark.parametrize(
    "xml, deviation",
    [
        # GLOBAL, mode H: team 0 hosts 1 and 3 in slots 0-2 -> 2 games.
        ('<CA4 teams1="0" teams2="1;2;3" mode1="H" mode2="GLOBAL" min="0" max="1" slots="0;1;2" type="HARD"/>', 1),
        ('<CA4 teams1="0" teams2="1;2;3" mode1="H" mode2="GLOBAL" min="0" max="2" slots="0;1;2" type="HARD"/>', 0),
        # mode A: team 1 plays away in s0, s1, s5 -> 3 games.
        ('<CA4 teams1="1" teams2="0;2;3" mode1="A" mode2="GLOBAL" min="0" max="2" slots="' + ALL + '" type="HARD"/>', 1),
        # mode HA: teams 0 and 1 meet twice.
        ('<CA4 teams1="0" teams2="1" mode1="HA" mode2="GLOBAL" min="0" max="1" slots="' + ALL + '" type="HARD"/>', 1),
        # EVERY: home games of teams {0,2} per slot are 2, 1, 1 in slots 0-2.
        ('<CA4 teams1="0;2" teams2="0;1;2;3" mode1="H" mode2="EVERY" min="0" max="1" slots="0;1;2" type="HARD"/>', 1),
        ('<CA4 teams1="0;2" teams2="0;1;2;3" mode1="H" mode2="EVERY" min="0" max="0" slots="0;1;2" type="HARD"/>', 4),
    ],
)
def test_ca4_semantics(xml, deviation):
    assert check_one(xml).deviation == deviation


@pytest.mark.parametrize(
    "xml, deviation",
    [
        ('<GA1 meetings="1,0;" slots="3" min="0" max="0" type="HARD"/>', 1),   # (1,0) is in s3
        ('<GA1 meetings="0,1;" slots="3" min="0" max="0" type="HARD"/>', 0),   # orientation matters
        ('<GA1 meetings="0,1;2,3;" slots="0" min="2" max="2" type="HARD"/>', 0),
        ('<GA1 meetings="0,1;" slots="1;2" min="1" max="1" type="HARD"/>', 1),  # min not reached
    ],
)
def test_ga1_semantics(xml, deviation):
    assert check_one(xml).deviation == deviation


@pytest.mark.parametrize(
    "xml, deviation",
    [
        ('<BR1 teams="1" mode1="LEQ" mode2="HA" intp="2" slots="' + ALL + '" type="HARD"/>', 1),  # 3 breaks
        ('<BR1 teams="1" mode1="LEQ" mode2="H" intp="1" slots="' + ALL + '" type="HARD"/>', 1),   # 2 home breaks
        ('<BR1 teams="1" mode1="LEQ" mode2="A" intp="1" slots="' + ALL + '" type="HARD"/>', 0),   # 1 away break
        ('<BR1 teams="1" mode1="LEQ" mode2="HA" intp="0" slots="0" type="HARD"/>', 0),  # slot 0: never a break
        ('<BR1 teams="1" mode1="LEQ" mode2="HA" intp="0" slots="1" type="HARD"/>', 1),
        ('<BR1 teams="0" mode1="LEQ" mode2="HA" intp="0" slots="' + ALL + '" type="HARD"/>', 0),
    ],
)
def test_br1_semantics(xml, deviation):
    assert check_one(xml).deviation == deviation


@pytest.mark.parametrize(
    "xml, deviation",
    [
        ('<BR2 teams="0;1;2;3" homeMode="HA" mode2="LEQ" intp="6" slots="' + ALL + '" type="HARD"/>', 0),
        ('<BR2 teams="0;1;2;3" homeMode="HA" mode2="LEQ" intp="5" slots="' + ALL + '" type="HARD"/>', 1),
        ('<BR2 teams="1;2" homeMode="HA" mode2="LEQ" intp="1" slots="1" type="HARD"/>', 1),
    ],
)
def test_br2_semantics(xml, deviation):
    assert check_one(xml).deviation == deviation


# --- Unsupported constraints must be reported, never skipped ---

@pytest.mark.parametrize(
    "xml, reason_fragment",
    [
        ('<CA1 teams="0" max="0" mode="H" slots="0" type="HARD"/>', "CA1 is not implemented"),
        ('<SE1 teams="0;1" min="5" mode1="SLOTS" type="HARD"/>', "SE1 is not implemented"),
        ('<FA2 teams="0;1" mode="H" intp="1" slots="0;1" type="HARD"/>', "FA2 is not implemented"),
        ('<CA4 teams1="0" teams2="1" mode1="H" mode2="GLOBAL" min="1" max="1" slots="0" type="HARD"/>', "min > 0"),
        ('<BR1 teams="0" teamGroups="g1" mode1="LEQ" mode2="HA" intp="0" slots="1" type="HARD"/>', "group references"),
        ('<GA1 meetings="0,9;" slots="0" min="0" max="0" type="HARD"/>', "unknown team ids [9]"),
    ],
)
def test_unsupported_constraints_are_reported(xml, reason_fragment):
    report = validate(tiny_instance(xml), TINY_GAMES)
    assert len(report.unsupported) == 1 and reason_fragment in report.unsupported[0]
    assert report.results == []
    assert report.checked_constraints_satisfied   # nothing checked was violated...
    assert not report.fully_verified               # ...but the schedule is NOT fully verified


def test_unsupported_reported_alongside_checked_constraints():
    xml = (
        '<CA1 teams="0" max="0" mode="H" slots="0" type="HARD"/>'
        '<GA1 meetings="0,1;" slots="0" min="1" max="1" type="HARD"/>'
    )
    report = validate(tiny_instance(xml), TINY_GAMES)
    assert [r.label for r in report.results] == ["GA1#0"]
    assert report.unsupported[0].startswith("CA1#0:")
    assert not report.fully_verified


def test_soft_constraints_are_listed_not_checked():
    xml = '<CA1 teams="0" max="0" mode="H" slots="0" type="SOFT"/>'
    report = validate(tiny_instance(xml), TINY_GAMES)
    assert report.soft_ignored == ["CA1#0"]
    assert report.unsupported == [] and report.results == []
    assert report.fully_verified  # QOBLIB's feasibility benchmark ignores soft constraints


def test_non_compact_or_single_round_robin_format_is_unsupported():
    report = validate(tiny_instance(n_rr=1), TINY_GAMES)
    assert any("only compact double round-robins" in u for u in report.unsupported)
    assert not report.fully_verified
