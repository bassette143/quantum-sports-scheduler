"""Tests for the Phase W5B depth runner (wrestling/mat_qaoa_depth.py).

No QAOA is executed here: the tests cover output-path protection, the
instance-consistency guard, and the result calculations, using the
stored p=1 / p=2 JSON files read-only.
"""

import hashlib
import json
from pathlib import Path

import pytest

import wrestling.mat_qaoa_depth as depth_mod
from wrestling.mat_qaoa import analyze_samples
from wrestling.mat_qaoa_depth import (
    INSTANCE_KEYS,
    instance_matches,
    output_path,
    summarize,
)
from wrestling.mat_qubo import build_qubo_instance, extract_snapshot

RESULTS = Path(__file__).parent.parent / "results"
P1 = RESULTS / "wrestling_qaoa_result.json"
P2 = RESULTS / "wrestling_qaoa_p2_result.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------- output-path protection ----------

def test_output_path_refuses_p1():
    with pytest.raises(SystemExit):
        output_path(1)


def test_output_path_refuses_existing_file(tmp_path):
    existing = tmp_path / "wrestling_qaoa_p2_result.json"
    existing.write_text('{"keep": true}')
    with pytest.raises(SystemExit):
        output_path(2, tmp_path)
    assert existing.read_text() == '{"keep": true}'


def test_output_path_allows_new_file(tmp_path):
    out = output_path(3, tmp_path)  # path only; nothing is run or written
    assert out == tmp_path / "wrestling_qaoa_p3_result.json"
    assert not out.exists()


def test_main_refuses_before_running_when_output_exists(tmp_path, monkeypatch):
    # main() must stop at the path check, before any QAOA work.
    existing = tmp_path / "wrestling_qaoa_p2_result.json"
    existing.write_text("original")
    monkeypatch.setattr(depth_mod, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(depth_mod, "run_qaoa",
                        lambda *a, **k: pytest.fail("QAOA must not run"))
    with pytest.raises(SystemExit):
        depth_mod.main(2)
    assert existing.read_text() == "original"


def test_stored_p2_file_is_protected_and_unchanged():
    before = sha(P2)
    with pytest.raises(SystemExit):
        output_path(2)  # real results dir: the p=2 file exists
    assert sha(P2) == before


# ---------- QUBO / instance consistency ----------

def test_current_instance_matches_both_recorded_runs():
    inst = build_qubo_instance(extract_snapshot(42))
    p1 = json.loads(P1.read_text())
    assert instance_matches(p1["instance"], inst)
    p2 = json.loads(P2.read_text())
    assert p2["instance_identical_to_p1"] is True


@pytest.mark.parametrize("key", INSTANCE_KEYS)
def test_instance_guard_detects_any_change(key):
    inst = build_qubo_instance(extract_snapshot(42))
    recorded = json.loads(P1.read_text())["instance"]
    tampered = dict(recorded)
    value = tampered[key]
    tampered[key] = (value + 1 if isinstance(value, int)
                     else list(reversed(value)))
    assert not instance_matches(tampered, inst)


# ---------- result calculations ----------

def test_summarize_reports_recorded_p2_metrics():
    p2 = json.loads(P2.read_text())
    s = summarize(p2["main"])
    assert s["depth_p"] == 2
    assert s["shots"] == 4000
    assert s["feasible_shots"] == 832
    assert abs(s["feasible_percent"] - 20.8) < 1e-9
    assert s["optimal_shots"] == 3
    assert abs(s["optimal_percent"] - 0.075) < 1e-9
    assert s["best_feasible_score"] == 12
    assert s["best_qubo_energy"] == -12
    assert s["two_qubit_gates"] == 364
    assert s["total_shots"] == 36 * 1000 + 4000


def test_stored_p2_analysis_recomputes_from_raw_counts():
    # Independently re-score the saved final counts with the original W4
    # functions; the stored analysis must match exactly.
    p2 = json.loads(P2.read_text())
    snap = extract_snapshot(42)
    inst = build_qubo_instance(snap)
    a = analyze_samples(p2["main"]["final_counts"], inst, snap,
                        optimal_score=12, validate=False)
    stored = p2["main"]["analysis"]
    for key in ("shots", "feasible_shots", "optimal_shots", "best_energy",
                "best_feasible_score", "n_distinct_feasible"):
        assert a[key] == stored[key], key


def test_comparison_block_matches_main_runs():
    p1 = json.loads(P1.read_text())
    p2 = json.loads(P2.read_text())
    assert p2["comparison"]["p1_stored"] == summarize(p1["main"])
    assert p2["comparison"]["p2"] == summarize(p2["main"])
