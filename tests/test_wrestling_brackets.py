"""Tests for the Phase W2 wrestling bracket generator."""

import json

from wrestling.brackets import (
    build_bracket,
    eligible_entrants,
    generate_all_brackets,
    save_brackets,
)
from wrestling.rosters import WEIGHT_CLASSES, generate_rosters


def all_slots(bracket: dict) -> list[dict]:
    return [slot for rnd in bracket["rounds"] for slot in rnd["slots"]]


# ---------- full tournament generation ----------

def test_all_fourteen_brackets_generated():
    data = generate_all_brackets(seed=42)
    assert data["summary"]["n_brackets"] == 14
    assert sorted(data["brackets"].keys()) == sorted(WEIGHT_CLASSES)


def test_bracket_entrants_match_phase_w1_rosters():
    rosters = generate_rosters(seed=42)
    data = generate_all_brackets(seed=42)
    for weight in WEIGHT_CLASSES:
        expected = [r.school for r in rosters if weight in r.filled_weights]
        assert data["brackets"][weight]["entrants"] == expected


def test_every_entrant_appears_exactly_once_in_positions():
    data = generate_all_brackets(seed=42)
    for b in data["brackets"].values():
        filled = [p for p in b["positions"] if p is not None]
        assert sorted(filled) == sorted(b["entrants"])
        assert len(filled) == len(set(filled))  # no double placement


def test_no_wrestler_faces_themselves():
    data = generate_all_brackets(seed=42)
    for b in data["brackets"].values():
        for slot in all_slots(b):
            if slot["type"] == "match":
                a, c = slot["wrestlers"]
                assert a != c


def test_every_position_is_wrestler_or_bye():
    data = generate_all_brackets(seed=42)
    for b in data["brackets"].values():
        assert len(b["positions"]) == b["bracket_size"]
        for p in b["positions"]:
            assert p is None or p in b["entrants"]


def test_bracket_capacity_is_power_of_two():
    data = generate_all_brackets(seed=42)
    for b in data["brackets"].values():
        size = b["bracket_size"]
        if b["n_entrants"] >= 1:
            assert size >= 1
            assert size & (size - 1) == 0  # power of two
            assert size >= b["n_entrants"]


def test_bye_counts_are_correct():
    data = generate_all_brackets(seed=42)
    for b in data["brackets"].values():
        if b["n_entrants"] >= 2:
            assert b["byes"] == b["bracket_size"] - b["n_entrants"]
            bye_slots = [
                s for s in b["rounds"][0]["slots"] if s["type"] == "bye"
            ]
            assert len(bye_slots) == b["byes"]


def test_no_round_one_slot_pairs_two_empty_positions():
    data = generate_all_brackets(seed=42)
    for b in data["brackets"].values():
        if b["n_entrants"] >= 2:
            for slot in b["rounds"][0]["slots"]:
                assert slot["wrestlers"][0] is not None


# ---------- the six-entrant example from the specification ----------

def test_six_entrants_make_eight_bracket_with_two_byes():
    entrants = [f"School {i}" for i in range(1, 7)]
    b = build_bracket(152, entrants)
    assert b["bracket_size"] == 8
    assert b["byes"] == 2
    assert b["projected_contested_matches"] == 5
    round1 = b["rounds"][0]["slots"]
    assert sum(1 for s in round1 if s["type"] == "bye") == 2
    assert sum(1 for s in round1 if s["type"] == "match") == 2
    # semifinal and final placeholders
    assert len(b["rounds"][1]["slots"]) == 2
    assert len(b["rounds"][2]["slots"]) == 1


def test_byes_are_not_contested_matches_and_advance_automatically():
    b = build_bracket(152, [f"School {i}" for i in range(1, 7)])
    for slot in all_slots(b):
        if slot["type"] == "bye":
            assert "winner" not in slot  # byes have no winner at all
            assert slot["advances"] == slot["wrestlers"][0]
    # bye advancement is propagated into round-2 known participants
    round2_known = [
        p for s in b["rounds"][1]["slots"] for p in s["participants"]
        if p is not None
    ]
    assert len(round2_known) == 2


def test_no_winners_are_invented():
    data = generate_all_brackets(seed=42)
    for b in data["brackets"].values():
        for slot in all_slots(b):
            if slot["type"] in ("match", "placeholder"):
                assert slot["winner"] is None
        if b["n_entrants"] >= 2:
            assert b["champion"] is None


# ---------- edge cases ----------

def test_zero_entrants_bracket_is_empty():
    b = build_bracket(285, [])
    assert b["n_entrants"] == 0
    assert b["rounds"] == []
    assert b["projected_contested_matches"] == 0
    assert b["champion"] is None


def test_one_entrant_is_champion_without_a_match():
    b = build_bracket(285, ["School 9"])
    assert b["projected_contested_matches"] == 0
    assert b["rounds"] == []
    assert b["champion"] == "School 9"
    assert b["byes"] == 0


def test_two_entrants_single_final():
    b = build_bracket(120, ["School 1", "School 2"])
    assert b["bracket_size"] == 2
    assert b["byes"] == 0
    assert b["projected_contested_matches"] == 1
    assert len(b["rounds"]) == 1
    assert b["rounds"][0]["slots"][0]["type"] == "match"


def test_contested_matches_equal_entrants_minus_one():
    for n in range(2, 13):
        b = build_bracket(132, [f"School {i}" for i in range(1, n + 1)])
        assert b["projected_contested_matches"] == n - 1


# ---------- placeholders and identifiers ----------

def test_later_round_placeholders_structure():
    data = generate_all_brackets(seed=42)
    for b in data["brackets"].values():
        if b["n_entrants"] < 2:
            continue
        for rnd in b["rounds"][1:]:
            for slot in rnd["slots"]:
                assert slot["type"] == "placeholder"
                assert len(slot["fed_by"]) == 2
        # each round halves the slot count down to the final
        sizes = [len(rnd["slots"]) for rnd in b["rounds"]]
        assert sizes[-1] == 1
        for earlier, later in zip(sizes, sizes[1:]):
            assert earlier == 2 * later


def test_match_identifiers_are_unique_across_tournament():
    data = generate_all_brackets(seed=42)
    ids = [
        slot["id"]
        for b in data["brackets"].values()
        for slot in all_slots(b)
    ]
    assert len(ids) == len(set(ids))


def test_identical_input_produces_identical_brackets():
    a = generate_all_brackets(seed=42)
    b = generate_all_brackets(seed=42)
    assert a == b


# ---------- JSON persistence ----------

def test_json_roundtrip(tmp_path):
    data = generate_all_brackets(seed=42)
    path = tmp_path / "brackets.json"
    save_brackets(data, path)
    loaded = json.loads(path.read_text())
    assert loaded["settings"]["seed"] == 42
    assert loaded["summary"] == data["summary"]
    # JSON stringifies integer keys; structures must survive the roundtrip
    assert loaded["brackets"]["106"]["n_entrants"] == (
        data["brackets"][106]["n_entrants"]
    )
    assert loaded["brackets"]["106"]["rounds"] == (
        data["brackets"][106]["rounds"]
    )


def test_eligible_entrants_consistent_with_rosters():
    rosters = generate_rosters(seed=42)
    for weight in WEIGHT_CLASSES:
        entrants = eligible_entrants(rosters, weight)
        for r in rosters:
            assert (r.school in entrants) == (weight in r.filled_weights)
