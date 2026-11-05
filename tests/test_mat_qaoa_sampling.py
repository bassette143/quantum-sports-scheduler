"""Regression tests for the Phase W5D sampling-strategy experiment."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from qiskit.quantum_info import Statevector

import wrestling.mat_qaoa_sampling as samp
from wrestling.mat_qaoa import build_circuit, qubo_to_ising, run_qaoa
from wrestling.mat_qaoa_sampling import (
    energy_tables,
    evaluation_seeds,
    exact_distribution,
    final_seed,
    high_shot_seed,
    paired,
    run_trial,
    stream_check,
    summarize,
)
from wrestling.mat_qubo import (
    build_qubo_instance,
    extract_snapshot,
    qubo_energy,
)

RESULTS = Path(__file__).parent.parent / "results"
STORED = RESULTS / "wrestling_qaoa_sampling_results.json"
SMALL = dict(opt_shots=100, final_shots=200, maxiter=4)

# SHA-256 of evidence files recorded before Phase W5D began.
PRESERVED = {
    "wrestling_qaoa_result.json":
        "1754dbb685274d84520e5ea1614e382b2aefa359cbd6306d603992f1fd14a0f1",
    "wrestling_qaoa_p2_result.json":
        "b23f6250e8d9a43e87f7e3629ad4448d300a39a4c02c169e63da59a057ee50f2",
    "wrestling_qaoa_sweep_results.json":
        "b91ad3e5cdda04d38e0aca2969be25e7d87bf0849ba0acf0c9573a34b22c019b",
}
_c = {}


def ctx():
    if not _c:
        snap = extract_snapshot(42)
        inst = build_qubo_instance(snap)
        _c.update(snap=snap, inst=inst, tables=energy_tables(inst, 12),
                  stored=json.loads(STORED.read_text()))
    return _c


# ---------- independent sampling streams ----------

def test_stream_safeguards_hold():
    checks = stream_check(ctx()["inst"])
    assert all(checks.values()), checks


def test_seed_derivation_is_deterministic_and_distinct():
    assert evaluation_seeds(11) == evaluation_seeds(11)
    assert evaluation_seeds(11) != evaluation_seeds(22)
    seeds = evaluation_seeds(11)
    assert len(set(seeds)) == len(seeds)
    assert final_seed(11) not in seeds and high_shot_seed(11) not in seeds
    assert final_seed(11) != high_shot_seed(11)


def test_independent_strategy_uses_a_new_seed_per_evaluation():
    c = ctx()
    t = run_trial(c["inst"], c["snap"], c["tables"], 12, "independent", 11,
                  high_shots=500, validate=False, **SMALL)
    used = t["seeds"]["evaluation_seeds"]
    assert len(used) == t["optimizer_evaluations"]
    assert used == evaluation_seeds(11)[:len(used)]
    assert t["seeds"]["final_sample_seed"] == final_seed(11)


# ---------- reproducibility ----------

def test_fixed_strategy_equals_original_run_qaoa():
    c = ctx()
    a = run_trial(c["inst"], c["snap"], c["tables"], 12, "fixed", 5,
                  high_shots=500, validate=False, **SMALL)
    b = run_qaoa(c["inst"], c["snap"], 12, reps=1, seed=5, validate=False,
                 **SMALL)
    assert a["final_counts"] == b["final_counts"]
    assert a["objective_history"] == b["mean_energy_history"]


def test_independent_strategy_is_reproducible():
    c = ctx()
    kw = dict(high_shots=500, validate=False, **SMALL)
    r1 = run_trial(c["inst"], c["snap"], c["tables"], 12, "independent", 7, **kw)
    r2 = run_trial(c["inst"], c["snap"], c["tables"], 12, "independent", 7, **kw)
    assert r1["final_counts"] == r2["final_counts"]
    assert r1["objective_history"] == r2["objective_history"]
    assert r1["exact_final_energy"] == r2["exact_final_energy"]


def test_matched_initial_parameters_across_strategies():
    st = ctx()["stored"]
    for s in st["settings"]["paired_seeds"]:
        a, b = (next(t for t in st["trials"]
                     if t["trial_seed"] == s and t["strategy"] == k)
                for k in ("fixed", "independent"))
        assert a["initial_parameters"] == b["initial_parameters"]


def test_stored_strategy_A_matches_stored_w5c_runs():
    st = ctx()["stored"]
    w5c = json.loads((RESULTS / "wrestling_qaoa_sweep_results.json").read_text())
    for old in (t for t in w5c["trials"] if t["depth"] == 1):
        new = next(t for t in st["trials"]
                   if t["strategy"] == "fixed" and t["trial_seed"] == old["seed"])
        assert new["final_counts"] == old["final_counts"]
        assert new["objective_history"] == old["objective_history"]


# ---------- bitstring decoding ----------

def test_exact_distribution_uses_sampler_bit_order():
    # The exact probability of the most likely assignment must match its
    # sampled frequency; a bit-reversed index would not.
    c = ctx()
    inst = c["inst"]
    circuit, _, _, _ = build_circuit(inst, 1)
    params = list(circuit.parameters)
    theta = [0.6, 0.15]
    probs = exact_distribution(inst, 1, {p.name: v for p, v in zip(params, theta)})
    from qiskit_aer.primitives import SamplerV2
    shots = 40_000
    counts = SamplerV2(seed=3).run(
        [circuit.assign_parameters(dict(zip(params, theta)))],
        shots=shots).result()[0].data.meas.get_counts()
    x = int(np.argmax(probs))
    freq = counts.get(format(x, "014b"), 0) / shots
    se = (probs[x] * (1 - probs[x]) / shots) ** 0.5
    assert abs(freq - probs[x]) < 5 * se
    rev = int(format(x, "014b")[::-1], 2)
    assert rev == x or abs(probs[rev] - probs[x]) > 5 * se


# ---------- original QUBO energy evaluation ----------

def test_energy_table_is_original_qubo_energy():
    c = ctx()
    E = c["tables"]["energy"]
    for x in range(0, len(E), 11):
        assert E[x] == qubo_energy(x, c["inst"])
    assert c["tables"]["feasible"].sum() == 1289
    assert c["tables"]["optimal"].sum() == 1


def test_exact_energy_equals_ising_expectation():
    # Independent route: <psi| H_ising |psi> + offset.
    c = ctx()
    inst = c["inst"]
    op, offset = qubo_to_ising(inst)
    circuit, _, _, scale = build_circuit(inst, 1)
    names = [p.name for p in circuit.parameters]
    theta = {n: v for n, v in zip(names, [0.4, 0.25])}
    probs = exact_distribution(inst, 1, theta)
    from qiskit.circuit.library import qaoa_ansatz
    ans = qaoa_ansatz(cost_operator=op / scale, reps=1)
    sv = Statevector(ans.assign_parameters({p: theta[p.name] for p in ans.parameters}))
    expect = float(sv.expectation_value(op).real) + offset
    assert abs(float(probs @ c["tables"]["energy"]) - expect) < 1e-8


# ---------- stored results and preservation ----------

@pytest.mark.parametrize("name,digest", PRESERVED.items())
def test_earlier_evidence_files_unchanged(name, digest):
    assert hashlib.sha256((RESULTS / name).read_bytes()).hexdigest() == digest


def test_main_refuses_to_overwrite(tmp_path, monkeypatch):
    out = tmp_path / "s.json"
    out.write_text("keep")
    monkeypatch.setattr(samp, "OUT", out)
    monkeypatch.setattr(samp, "run_trial", lambda *a, **k: pytest.fail("ran"))
    with pytest.raises(SystemExit):
        samp.main()
    assert out.read_text() == "keep"


def test_stored_summaries_and_paired_stats_recompute():
    st = ctx()["stored"]
    for s in st["summaries"]:
        assert summarize([t for t in st["trials"]
                          if t["strategy"] == s["strategy"]]) == s
    assert paired(st["trials"]) == st["paired_comparison_B_minus_A"]


def test_stored_gaps_are_exact_minus_best_estimate():
    for t in ctx()["stored"]["trials"]:
        assert t["objective_best_estimate"] == min(t["objective_history"])
        assert abs(t["gap_exact_minus_best_estimate"]
                   - (t["exact_final_energy"] - t["objective_best_estimate"])) < 1e-12
