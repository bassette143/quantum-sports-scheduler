"""Local tests for the guarded IBM hardware QAOA script. No network, no QPU."""

import json
import re
from pathlib import Path

import numpy as np
import pytest
from qiskit.quantum_info import Statevector

from hardware import qaoa_hardware as hw
from wrestling.mat_qaoa import build_circuit


@pytest.fixture(scope="module")
def problem():
    return hw.load_instance()


@pytest.fixture(scope="module")
def saved():
    return hw.load_saved_parameters()


@pytest.fixture(scope="module")
def fakefez_prep():
    from qiskit_ibm_runtime.fake_provider import FakeFez
    backend = FakeFez()
    return backend, hw.prepare(backend, levels=(2,), seeds=(0, 1))


def test_saved_parameters_are_the_recorded_sweep_trial(saved):
    sweep = json.loads(hw.SWEEP_FILE.read_text(encoding="utf-8"))
    trial = next(t for t in sweep["trials"] if t["depth"] == 1 and t["seed"] == 22)
    assert saved["parameters"] == trial["optimal_parameters"]
    assert saved["simulator_feasible_percent"] == pytest.approx(23.475)
    assert saved["simulator_final_shots"] == 4000


def test_unknown_trial_is_rejected():
    with pytest.raises(ValueError):
        hw.load_saved_parameters(depth=1, seed=999)


def test_logical_circuit_matches_research_circuit(problem, saved):
    """Same angles in the research circuit (wrestling.mat_qaoa.build_circuit)
    and in the hardware script must give identical ideal probabilities."""
    inst, _, _ = problem
    research, *_ = build_circuit(inst, 1)
    research = hw.bind_saved_parameters(research.remove_final_measurements(inplace=False),
                                        saved["parameters"])
    p_research = Statevector(research).probabilities()
    p_hw = hw.exact_logical_distribution(inst, 1, saved["parameters"])
    assert hw.total_variation_distance(p_research, p_hw) < 1e-9


def test_exact_feasible_probability_matches_notebook(problem, saved):
    inst, _, _ = problem
    probs = hw.exact_logical_distribution(inst, 1, saved["parameters"])
    feas = np.array([hw.is_feasible(x, inst) for x in range(2 ** 14)])
    assert 100 * probs[feas].sum() == pytest.approx(23.58, abs=0.01)


def test_fakefez_circuit_is_valid_isa_and_equivalent(fakefez_prep):
    _, prep = fakefez_prep
    c = prep["compatibility"]
    assert c["all_instructions_supported_by_target"]
    assert c["fits_on_backend"]
    assert c["logical_qubits"] == 14
    assert 14 <= c["physical_qubits_used"] <= 30
    assert c["logical_depth"] == 79          # research circuit depth (RESULTS.md)
    assert set(c["isa_gate_counts"]) <= {"cz", "sx", "rz", "x", "measure", "barrier", "delay"}
    assert prep["equivalence_tvd"] < 1e-6


def test_qpu_time_estimate_is_small(fakefez_prep):
    _, prep = fakefez_prep
    c = prep["compatibility"]
    assert 0 < c["estimated_circuit_duration_us"] < 200
    assert c["estimated_sampling_seconds"] < 10      # far below the 600 s Open Plan allowance


def test_analyze_counts_scores_and_compares_with_random(problem):
    inst, snapshot, optimal = problem
    from wrestling.mat_qubo import exhaustive_verification
    x_opt = exhaustive_verification(inst)["ground_states"][0]
    counts = {format(x_opt, "014b"): 10, format(0, "014b"): 90}
    a = hw.analyze_counts(counts, inst, snapshot, optimal)
    assert a["shots"] == 100
    assert a["feasible_percent"] == pytest.approx(10.0)
    assert a["optimal_shots"] == 10
    assert a["validation"]["validator_failures"] == 0
    lo, hi = a["feasible_percent_ci95_clopper_pearson"]
    assert lo < 10 < hi
    assert a["random_feasible_percent"] == pytest.approx(7.867, abs=0.001)


def test_submission_requires_explicit_approval(monkeypatch):
    def no_network():
        raise AssertionError("must not connect to IBM without approval")
    monkeypatch.setattr(hw, "_service", no_network)
    with pytest.raises(PermissionError):
        hw.submit_to_ibm(approve=False)


def test_cli_submit_without_flag_sends_nothing(monkeypatch):
    def no_network():
        raise AssertionError("must not connect to IBM without approval")
    monkeypatch.setattr(hw, "_service", no_network)
    with pytest.raises(PermissionError):
        hw.main(["submit"])


def test_safe_write_refuses_to_overwrite(tmp_path):
    path = tmp_path / "out.json"
    hw.safe_write_json(path, {"a": 1})
    with pytest.raises(FileExistsError):
        hw.safe_write_json(path, {"a": 2})
    assert json.loads(path.read_text()) == {"a": 1}


def test_outputs_go_to_a_separate_hardware_folder():
    assert hw.OUT_DIR == hw.RESULTS / "hardware"


def test_script_never_stores_prints_or_hardcodes_an_api_key():
    src = Path(hw.__file__).read_text(encoding="utf-8")
    assert "save_account" not in src                       # never persists credentials
    literals = re.findall(r"""["']([A-Za-z0-9_\-]{40,})["']""", src)
    key_like = [s for s in literals if re.search(r"\d", s) and re.search(r"[A-Z]", s)]
    assert not key_like                                    # no hard-coded key
    # the only key source is Windows Credential Manager, used in memory
    assert re.findall(r"token\s*=\s*(\w+)", src) == ["secret"]
    for line in src.splitlines():
        if "secret" in line:
            assert not re.search(r"\b(print|log\w*|write\w*|dump\w*)\(", line), line
    assert "replace(secret, '***')" in src                 # masked in error messages


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="Windows Credential Manager only")
def test_missing_windows_credential_is_reported_without_secrets():
    with pytest.raises(LookupError, match="not found"):
        hw._read_windows_credential("qss-test-credential-that-does-not-exist-7f3a")
