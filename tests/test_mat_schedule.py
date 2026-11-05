"""Tests for the Phase W3 mat scheduler and its independent validator."""

import json

from wrestling.brackets import build_bracket, generate_all_brackets
from wrestling.mat_schedule import (
    N_MATS,
    REST_SLOTS,
    longest_chain_with_rest,
    schedule_matches,
    schedule_statistics,
)
from wrestling.mat_validator import contested_slots, validate_mat_schedule


def full_data():
    return generate_all_brackets(seed=42)


# ---------- scheduling the real tournament ----------

def test_all_contested_matches_scheduled_exactly_once():
    data = full_data()
    assignments = schedule_matches(data)
    jobs = contested_slots(data)
    assert len(jobs) == 118  # verified Phase W2 total
    assert set(assignments) == set(jobs)


def test_schedule_passes_independent_validator():
    data = full_data()
    assignments = schedule_matches(data)
    result = validate_mat_schedule(data, assignments, N_MATS, REST_SLOTS)
    assert result.is_valid, result.violations


def test_no_mat_double_booking():
    assignments = schedule_matches(full_data())
    keys = [(a["mat"], a["slot"]) for a in assignments.values()]
    assert len(keys) == len(set(keys))


def test_bracket_order_and_rest_respected():
    data = full_data()
    assignments = schedule_matches(data)
    jobs = contested_slots(data)
    for mid, meta in jobs.items():
        for fid in meta["contested_feeders"]:
            assert (
                assignments[mid]["slot"]
                >= assignments[fid]["slot"] + 1 + REST_SLOTS
            )


def test_makespan_at_least_lower_bound():
    data = full_data()
    assignments = schedule_matches(data)
    stats = schedule_statistics(data, assignments, N_MATS, REST_SLOTS)
    assert stats["makespan_slots"] >= stats["theoretical_lower_bound_slots"]


def test_scheduling_is_deterministic():
    data = full_data()
    assert schedule_matches(data) == schedule_matches(data)


# ---------- validator rejects broken schedules ----------

def test_validator_rejects_missing_match():
    data = full_data()
    assignments = schedule_matches(data)
    broken = dict(assignments)
    removed = sorted(broken)[0]
    del broken[removed]
    result = validate_mat_schedule(data, broken, N_MATS, REST_SLOTS)
    assert not result.is_valid
    assert any("Unscheduled" in v for v in result.violations)


def test_validator_rejects_double_booked_mat():
    data = full_data()
    assignments = {k: dict(v) for k, v in schedule_matches(data).items()}
    ids = sorted(assignments)
    assignments[ids[1]]["mat"] = assignments[ids[0]]["mat"]
    assignments[ids[1]]["slot"] = assignments[ids[0]]["slot"]
    result = validate_mat_schedule(data, assignments, N_MATS, REST_SLOTS)
    assert not result.is_valid
    assert any("double-booked" in v for v in result.violations)


def test_validator_rejects_rest_violation():
    data = full_data()
    assignments = {k: dict(v) for k, v in schedule_matches(data).items()}
    jobs = contested_slots(data)
    # Find a match with a contested feeder and schedule it right after it.
    mid = next(m for m, j in jobs.items() if j["contested_feeders"])
    fid = jobs[mid]["contested_feeders"][0]
    assignments[mid]["slot"] = assignments[fid]["slot"] + 1  # rest violated
    assignments[mid]["mat"] = N_MATS  # avoid an unrelated double-booking
    result = validate_mat_schedule(data, assignments, N_MATS, REST_SLOTS)
    assert not result.is_valid
    assert any("too soon" in v for v in result.violations)


def test_validator_rejects_out_of_range_mat():
    data = full_data()
    assignments = {k: dict(v) for k, v in schedule_matches(data).items()}
    first = sorted(assignments)[0]
    assignments[first]["mat"] = N_MATS + 1
    result = validate_mat_schedule(data, assignments, N_MATS, REST_SLOTS)
    assert not result.is_valid
    assert any("outside" in v for v in result.violations)


def test_validator_rejects_known_wrestler_conflict():
    # Synthetic bracket: 2 entrants -> one final. Duplicate the bracket's
    # only match into a fake second match sharing a wrestler and time slot
    # is impossible via real data, so instead schedule two ROUND-1 matches
    # of a 4-entrant bracket into the same slot after swapping a wrestler.
    b = build_bracket(126, ["School 1", "School 2", "School 3", "School 4"])
    # Corrupt the bracket data locally: make both round-1 matches share
    # School 1 (the validator must catch the double booking).
    b["rounds"][0]["slots"][1]["wrestlers"] = ["School 1", "School 4"]
    data = {"brackets": {126: b}}
    assignments = {
        b["rounds"][0]["slots"][0]["id"]: {"mat": 1, "slot": 1},
        b["rounds"][0]["slots"][1]["id"]: {"mat": 2, "slot": 1},
        b["rounds"][1]["slots"][0]["id"]: {"mat": 1, "slot": 3},
    }
    result = validate_mat_schedule(data, assignments, 6, 1)
    assert not result.is_valid
    assert any("booked in both" in v for v in result.violations)


# ---------- chain bound and small cases ----------

def test_longest_chain_with_rest_small_bracket():
    b = build_bracket(106, [f"School {i}" for i in range(1, 9)])  # 8 -> 3 rounds
    jobs = contested_slots({"brackets": {106: b}})
    # 3 rounds, rest 1 between: slots 1, 3, 5 -> chain length 5
    assert longest_chain_with_rest(jobs, rest_slots=1) == 5


def test_single_bracket_schedules_validly():
    b = build_bracket(106, [f"School {i}" for i in range(1, 7)])  # 6 entrants
    data = {"brackets": {106: b}}
    assignments = schedule_matches(data, n_mats=2, rest_slots=1)
    result = validate_mat_schedule(data, assignments, 2, 1)
    assert result.is_valid, result.violations
    assert len(assignments) == 5  # entrants - 1


# ---------- persistence ----------

def test_results_json_roundtrip(tmp_path):
    data = full_data()
    assignments = schedule_matches(data)
    stats = schedule_statistics(data, assignments, N_MATS, REST_SLOTS)
    path = tmp_path / "mat_schedule.json"
    path.write_text(json.dumps({"assignments": assignments, "stats": stats}))
    loaded = json.loads(path.read_text())
    assert loaded["stats"]["n_matches_scheduled"] == 118
    assert len(loaded["assignments"]) == 118
