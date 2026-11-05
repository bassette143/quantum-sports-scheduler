"""Tests for the Phase W5C reproducibility sweep (wrestling/mat_qaoa_sweep.py)."""

import json
from pathlib import Path

import pytest

import wrestling.mat_qaoa_sweep as sweep
from wrestling.mat_qaoa_sweep import (
    analysis,
    clopper_pearson,
    mean_sd_ci,
    penalty_part,
    sample_metrics,
    summarize_depth,
    trial,
)
from wrestling.mat_qubo import (
    build_qubo_instance,
    classical_brute_force,
    extract_snapshot,
    qubo_energy,
)

STORED = Path(__file__).parent.parent / "results" / "wrestling_qaoa_sweep_results.json"
_c = {}


def ctx():
    if not _c:
        snap = extract_snapshot(42)
        inst = build_qubo_instance(snap)
        brute = classical_brute_force(inst)
        _c.update(snap=snap, inst=inst, n=len(inst["pool"]),
                  opt_x=sum(1 << i for i in brute["example_subset"]),
                  stored=json.loads(STORED.read_text()))
    return _c


def bs(x, n):
    return format(x, f"0{n}b")


# ---------- excessive-violation metric ----------

def test_penalty_part_values():
    c = ctx()
    inst = c["inst"]
    assert penalty_part(c["opt_x"], inst) == 0          # feasible: no penalty
    assert penalty_part(0, inst) == 13 * 36             # empty: A*k^2 = 468
    full = 2 ** c["n"] - 1
    assert penalty_part(full, inst) == 13 * 64 + 13 * 4  # 832 + 52


def test_threshold_is_sixteen_A():
    c = ctx()
    assert sweep.EXCESSIVE_PENALTY_MULTIPLE * c["inst"]["penalty_A"] == 208
    assert c["stored"]["settings"]["excessive_threshold_penalty"] == 208


def test_sample_metrics_on_constructed_counts():
    c = ctx()
    inst, n = c["inst"], c["n"]
    counts = {bs(c["opt_x"], n): 3, bs(0, n): 1}  # energies -12 and 468
    m = sample_metrics(counts, inst, threshold=208)
    assert m["excessive_shots"] == 1
    assert abs(m["excessive_percent"] - 25.0) < 1e-12
    assert abs(m["final_sample_mean_energy"] - (3 * -12 + 468) / 4) < 1e-12
    assert m["mean_energy_without_excessive"] == -12
    assert m["cardinality_distribution"][6] == 3
    assert m["cardinality_distribution"][0] == 1


# ---------- statistics helpers ----------

def test_clopper_pearson_known_values():
    lo, hi = clopper_pearson(0, 5)
    assert lo == 0.0 and abs(hi - 0.5218) < 1e-4
    lo, hi = clopper_pearson(5, 5)
    assert hi == 1.0 and abs(lo - 0.4782) < 1e-4
    lo, hi = clopper_pearson(3, 5)
    assert lo < 0.6 < hi


def test_mean_sd_ci_n5():
    s = mean_sd_ci([1.0, 2.0, 3.0, 4.0, 5.0])
    assert s["mean"] == 3.0
    assert abs(s["sd"] - 1.5811388) < 1e-6
    half = 2.776 * 1.5811388 / 5 ** 0.5
    assert abs(s["ci95_t"][1] - (3.0 + half)) < 1e-6


# ---------- protection ----------

def test_main_refuses_to_overwrite(tmp_path, monkeypatch):
    out = tmp_path / "sweep.json"
    out.write_text("keep")
    monkeypatch.setattr(sweep, "OUT", out)
    monkeypatch.setattr(sweep, "trial",
                        lambda *a, **k: pytest.fail("must not run"))
    with pytest.raises(SystemExit):
        sweep.main()
    assert out.read_text() == "keep"


# ---------- stored results are internally consistent ----------

def test_stored_summaries_recompute_from_trials():
    st = ctx()["stored"]
    for summary in st["summaries"]:
        trials = [t for t in st["trials"] if t["depth"] == summary["depth"]]
        assert summarize_depth(trials) == summary


def test_stored_analysis_recomputes_from_trials():
    st = ctx()["stored"]
    assert analysis(st["trials"]) == st["analysis"]


def test_stored_final_energy_matches_raw_counts():
    c = ctx()
    for t in c["stored"]["trials"]:
        counts = t["final_counts"]
        mean = sum(qubo_energy(int(b, 2), c["inst"]) * v
                   for b, v in counts.items()) / sum(counts.values())
        assert abs(mean - t["final_sample_mean_energy"]) < 1e-9


def test_corrected_gap_ci_uses_df9_and_matches_saved_trials():
    st = ctx()["stored"]
    # The original stored field is null (the bug being corrected) ...
    assert st["analysis"]["final_minus_optimizer_best_objective"]["ci95_t"] is None
    c = sweep.gap_ci95_corrected(st["trials"])
    assert c["n"] == 10 and c["df"] == 9
    assert abs(c["t_critical"] - 2.262157) < 1e-5
    # ... mean/sd agree with what was stored ...
    stored_gap = st["analysis"]["final_minus_optimizer_best_objective"]
    assert abs(c["mean"] - stored_gap["mean"]) < 1e-12
    assert abs(c["sd"] - stored_gap["sd"]) < 1e-12
    # ... and the interval matches the hand calculation in the W5C report.
    lo, hi = c["ci95_t"]
    assert abs(lo - 1.5999) < 1e-3 and abs(hi - 5.6702) < 1e-3
    assert c["all_gaps_positive"] is True


def test_ci_correction_sidecar_never_touches_sweep(tmp_path):
    import hashlib
    before = hashlib.sha256(STORED.read_bytes()).hexdigest()
    out = tmp_path / "ci.json"
    side = sweep.write_ci_correction(STORED, out)
    assert side["stored_value"] is None
    assert hashlib.sha256(STORED.read_bytes()).hexdigest() == before
    with pytest.raises(SystemExit):
        sweep.write_ci_correction(STORED, out)  # refuses overwrite


def test_t_ci95_matches_table_for_n5():
    s = sweep.t_ci95([1.0, 2.0, 3.0, 4.0, 5.0])
    assert abs(s["t_critical"] - 2.776445) < 1e-5


def test_stored_trial_reproduces_exactly():
    # Re-run the cheapest stored configuration and compare raw output.
    c = ctx()
    stored = next(t for t in c["stored"]["trials"]
                  if t["depth"] == 1 and t["seed"] == 11)
    again = trial(c["inst"], c["snap"], 12, 1, 11, 208)
    assert again["final_counts"] == stored["final_counts"]
    assert again["objective_history"] == stored["objective_history"]
    assert again["feasible_shots"] == stored["feasible_shots"]
