"""Wrestling QAOA (p=1) on real IBM quantum hardware: prepared and guarded.

What this experiment tests
--------------------------
We take the SAME 14-qubit wrestling QAOA circuit that ran on the noiseless
simulator, with the SAME saved angles (no new optimization), and sample it on a
real IBM processor. The hardware result is then compared with:

  1. the saved simulator run for those angles (W5C sweep, p=1, seed 22),
  2. the exact noiseless probabilities for those angles (statevector),
  3. a local noisy prediction (FakeFez noise model, no QPU), and
  4. random guessing (exactly 1,289 of 16,384 selections are feasible).

Every sample is scored with the original W4 QUBO energy, and every distinct
feasible selection is checked by the independent mat validator.

Safety rules built into this script
-----------------------------------
* The default command (`preflight`) is fully local: FakeFez snapshot + Aer.
  It never connects to IBM and uses no QPU time.
* `check-live` connects with your SAVED IBM account (read from
  ~/.qiskit/qiskit-ibm.json by qiskit-ibm-runtime) to read the backend's
  current configuration and transpile against it. It submits NO job.
* `submit` sends exactly one sampling job and refuses to run unless
  `--i-approve-qpu-usage` is given.
* The API key comes either from the account saved by qiskit-ibm-runtime, or
  (with --credential NAME) from that Windows Credential Manager entry, read
  in memory only. It is never accepted on the command line, stored in this
  repo, printed, logged, or written to any file, and it is masked in errors.
* Results go to new files under results/hardware/. Existing files are never
  overwritten; recorded simulator results are only read.

Run (from the project folder):
    python -m hardware.qaoa_hardware preflight
    python -m hardware.qaoa_hardware check-live --backend ibm_fez
    python -m hardware.qaoa_hardware submit --backend ibm_fez --i-approve-qpu-usage
    python -m hardware.qaoa_hardware fetch --job-id <JOB_ID>
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import time
from pathlib import Path

import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit.library import qaoa_ansatz
from qiskit.quantum_info import Statevector
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from scipy.stats import binomtest

from wrestling.mat_qaoa import analyze_samples, bitstring_to_selection, qubo_to_ising
from wrestling.mat_qubo import (build_qubo_instance, exhaustive_verification,
                                extract_snapshot, is_feasible, qubo_energy)

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
OUT_DIR = RESULTS / "hardware"
SWEEP_FILE = RESULTS / "wrestling_qaoa_sweep_results.json"

DEFAULT_BACKEND = "ibm_fez"
DEFAULT_DEPTH = 1          # p=1: shallowest circuit (fewest two-qubit gates)
DEFAULT_SEED = 22          # best p=1 simulator run in the W5C sweep (23.475 % feasible)
DEFAULT_SHOTS = 4000       # same number of final shots as the simulator runs
TRANSPILE_LEVELS = (2, 3)
TRANSPILE_SEEDS = tuple(range(20))
N_ASSIGNMENTS = 2 ** 14
RANDOM_FEASIBLE = 1289 / N_ASSIGNMENTS
RANDOM_OPTIMAL = 1 / N_ASSIGNMENTS
OPEN_PLAN_MONTHLY_SECONDS = 600     # IBM Quantum Open Plan: 10 minutes per 28 days


# ---------------------------------------------------------------------------
# Problem instance and saved parameters (read-only)
# ---------------------------------------------------------------------------

def load_instance() -> tuple[dict, dict, int]:
    """The verified W4 instance (seed 42, slot 17) and its optimal score."""
    snapshot = extract_snapshot(42)
    inst = build_qubo_instance(snapshot)
    optimal_score = exhaustive_verification(inst)["optimal_score"]
    return inst, snapshot, optimal_score


def load_saved_parameters(depth: int = DEFAULT_DEPTH, seed: int = DEFAULT_SEED,
                          sweep_file: Path = SWEEP_FILE) -> dict:
    """Optimized angles and simulator outcome of one recorded sweep trial."""
    sweep = json.loads(sweep_file.read_text(encoding="utf-8"))
    matches = [t for t in sweep["trials"] if t["depth"] == depth and t["seed"] == seed]
    if len(matches) != 1:
        raise ValueError(f"no unique sweep trial for depth={depth}, seed={seed}")
    t = matches[0]
    return {
        "source_file": str(sweep_file.relative_to(ROOT)) if sweep_file.is_relative_to(ROOT) else str(sweep_file),
        "depth": depth,
        "seed": seed,
        "parameters": list(t["optimal_parameters"]),
        "simulator_feasible_percent": t["feasible_percent"],
        "simulator_optimal_shots": t["optimal_shots"],
        "simulator_final_shots": sum(t["final_counts"].values()),
        "simulator_two_qubit_gates_logical": t["two_qubit_gates"],
        "simulator_circuit_depth_logical": t["circuit_depth"],
    }


# ---------------------------------------------------------------------------
# Circuits
# ---------------------------------------------------------------------------

def _ansatz(inst: dict, depth: int) -> QuantumCircuit:
    """Same construction as wrestling.mat_qaoa.build_circuit (normalized cost)."""
    op, _ = qubo_to_ising(inst)
    scale = float(np.max(np.abs(op.coeffs.real)))
    return qaoa_ansatz(cost_operator=op / scale, reps=depth)


def bind_saved_parameters(circuit: QuantumCircuit, params: list[float]) -> QuantumCircuit:
    """Parameters are stored in Qiskit's sorted order (beta..., gamma...),
    the same order `list(circuit.parameters)` used in the research runs."""
    plist = list(circuit.parameters)
    if len(plist) != len(params):
        raise ValueError(f"circuit has {len(plist)} parameters, got {len(params)}")
    return circuit.assign_parameters(dict(zip(plist, params)))


def build_logical_circuit(inst: dict, depth: int, params: list[float]) -> QuantumCircuit:
    """Bound, measured 14-qubit QAOA circuit (hardware-independent)."""
    qc = bind_saved_parameters(_ansatz(inst, depth), params)
    qc.measure_all()
    return qc


def exact_logical_distribution(inst: dict, depth: int, params: list[float]) -> np.ndarray:
    """Noiseless probabilities indexed by assignment integer x (qubit i = bit i)."""
    return Statevector(bind_saved_parameters(_ansatz(inst, depth), params)).probabilities()


def transpile_for_backend(logical: QuantumCircuit, backend,
                          levels=TRANSPILE_LEVELS, seeds=TRANSPILE_SEEDS) -> tuple[QuantumCircuit, dict]:
    """Try several optimization levels and layout seeds; keep the circuit with
    the fewest two-qubit gates (then smallest depth). Deterministic."""
    trials, best, best_key = [], None, None
    for level in levels:
        for seed in seeds:
            pm = generate_preset_pass_manager(optimization_level=level, backend=backend,
                                              seed_transpiler=seed)
            isa = pm.run(logical)
            n2q = two_qubit_count(isa)
            key = (n2q, isa.depth(), level, seed)
            trials.append({"level": level, "seed": seed, "two_qubit_gates": n2q, "depth": isa.depth()})
            if best_key is None or key < best_key:
                best, best_key = isa, key
    info = {
        "selected_optimization_level": best_key[2],
        "selected_seed_transpiler": best_key[3],
        "candidates_tried": len(trials),
        "two_qubit_gates_range": [min(t["two_qubit_gates"] for t in trials),
                                  max(t["two_qubit_gates"] for t in trials)],
        "depth_range": [min(t["depth"] for t in trials), max(t["depth"] for t in trials)],
    }
    return best, info


def two_qubit_count(circuit: QuantumCircuit) -> int:
    return sum(1 for ci in circuit.data
               if ci.operation.num_qubits == 2 and ci.operation.name not in ("barrier",))


def active_qubits(circuit: QuantumCircuit) -> list[int]:
    used = set()
    for ci in circuit.data:
        if ci.operation.name in ("barrier", "delay"):
            continue
        used.update(circuit.find_bit(q).index for q in ci.qubits)
    return sorted(used)


def compact_ideal_distribution(isa: QuantumCircuit, n_virtual: int = 14) -> np.ndarray:
    """Noiseless probabilities of the TRANSPILED circuit, mapped back to the
    logical bit order (x with virtual qubit i = bit i). Idle physical qubits
    are dropped so the statevector stays small."""
    act = active_qubits(isa)
    index = {p: k for k, p in enumerate(act)}
    compact = QuantumCircuit(len(act))
    compact.global_phase = isa.global_phase
    for ci in isa.data:
        name = ci.operation.name
        if name in ("barrier", "delay", "measure"):
            continue
        compact.append(ci.operation, [index[isa.find_bit(q).index] for q in ci.qubits])
    final = isa.layout.final_index_layout()[:n_virtual]   # virtual i -> physical
    qargs = [index[p] for p in final]
    return Statevector(compact).probabilities(qargs=qargs)


def total_variation_distance(p: np.ndarray, q: np.ndarray) -> float:
    return 0.5 * float(np.abs(np.asarray(p) - np.asarray(q)).sum())


# ---------------------------------------------------------------------------
# Compatibility and QPU-time estimate
# ---------------------------------------------------------------------------

def compatibility_report(isa: QuantumCircuit, backend, shots: int, logical: QuantumCircuit) -> dict:
    target = backend.target
    unsupported = []
    for ci in isa.data:
        name = ci.operation.name
        if name == "barrier":
            continue
        qargs = tuple(isa.find_bit(q).index for q in ci.qubits)
        if not target.instruction_supported(name, qargs):
            unsupported.append([name, list(qargs)])
    ops = {k: int(v) for k, v in isa.count_ops().items()}
    act = active_qubits(isa)

    duration_s = float(isa.estimate_duration(target, unit="s"))
    rep_delay = getattr(backend.configuration(), "default_rep_delay", None) if hasattr(backend, "configuration") else None
    rep_delay = float(rep_delay) if rep_delay is not None else 250e-6
    per_shot = duration_s + rep_delay
    sampling_s = shots * per_shot

    report = {
        "backend": backend.name,
        "backend_qubits": backend.num_qubits,
        "logical_qubits": logical.num_qubits,
        # same basis and level as wrestling.mat_qaoa.build_circuit (research circuit)
        "logical_depth": generate_preset_pass_manager(
            optimization_level=1, basis_gates=["cx", "rz", "rx", "h"]).run(logical).depth(),
        "physical_qubits_used": len(act),
        "physical_qubit_indices": act,
        "fits_on_backend": len(act) <= backend.num_qubits,
        "isa_depth": isa.depth(),
        "isa_two_qubit_gates": two_qubit_count(isa),
        "isa_gate_counts": ops,
        "all_instructions_supported_by_target": not unsupported,
        "unsupported_instructions": unsupported[:10],
        "estimated_circuit_duration_us": round(duration_s * 1e6, 2),
        "rep_delay_us": round(rep_delay * 1e6, 1),
        "shots": shots,
        "estimated_sampling_seconds": round(sampling_s, 2),
        "qpu_time_note": (
            "Rough estimate: shots x (circuit duration + repetition delay). IBM also "
            "counts setup/readout overhead, so expect a few seconds in total; billed "
            f"usage is reported by IBM after the job. Open Plan allowance: {OPEN_PLAN_MONTHLY_SECONDS} s per 28 days."
        ),
    }
    # crude success estimate from reported gate/readout errors (if available)
    try:
        props = backend.properties()
        log_f = 0.0
        for ci in isa.data:
            name = ci.operation.name
            if name in ("barrier", "delay", "measure"):
                continue
            qargs = [isa.find_bit(q).index for q in ci.qubits]
            if name == "rz":
                continue  # virtual gate, error-free
            err = props.gate_error(name, qargs)
            log_f += math.log(max(1e-12, 1 - err))
        measured = {isa.find_bit(ci.qubits[0]).index for ci in isa.data if ci.operation.name == "measure"}
        for p in measured:
            log_f += math.log(max(1e-12, 1 - props.readout_error(p)))
        report["product_of_gate_and_readout_fidelities"] = round(math.exp(log_f), 4)
        report["fidelity_note"] = ("Ignores decoherence and crosstalk, so the real circuit fidelity "
                                   "is likely lower. Values near 0 mean results close to random.")
    except Exception as exc:  # properties are not available for every backend
        report["product_of_gate_and_readout_fidelities"] = None
        report["fidelity_note"] = f"backend properties unavailable: {type(exc).__name__}"
    return report


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze_counts(counts: dict[str, int], inst: dict, snapshot: dict, optimal_score: int,
                   validate: bool = True) -> dict:
    """Score samples with the original W4 functions and compare with random guessing."""
    a = analyze_samples(counts, inst, snapshot, optimal_score, validate=validate)
    shots = a["shots"]
    mean_e = sum(qubo_energy(bitstring_to_selection(b), inst) * c for b, c in counts.items()) / shots
    ci = binomtest(a["feasible_shots"], shots).proportion_ci(confidence_level=0.95, method="exact")
    vs_random = binomtest(a["feasible_shots"], shots, RANDOM_FEASIBLE, alternative="greater")
    return {
        **{k: a[k] for k in ("shots", "feasible_shots", "feasible_percent", "optimal_shots",
                             "optimal_percent", "best_feasible_score", "best_energy",
                             "n_distinct_bitstrings", "n_distinct_feasible", "validation")},
        "mean_qubo_energy": mean_e,
        "feasible_percent_ci95_clopper_pearson": [100 * ci.low, 100 * ci.high],
        "random_feasible_percent": 100 * RANDOM_FEASIBLE,
        "random_mean_qubo_energy": 61.5,
        "p_value_feasible_greater_than_random": float(vs_random.pvalue),
        "expected_optimal_hits_if_random": shots * RANDOM_OPTIMAL,
    }


def distribution_summary(probs: np.ndarray, inst: dict, optimal_x: int) -> dict:
    feas = np.array([is_feasible(x, inst) for x in range(len(probs))])
    energies = np.array([qubo_energy(x, inst) for x in range(len(probs))])
    return {
        "feasible_percent": 100 * float(probs[feas].sum()),
        "optimal_percent": 100 * float(probs[optimal_x]),
        "mean_qubo_energy": float(probs @ energies),
    }


def noisy_prediction(isa: QuantumCircuit, backend, shots: int, seed: int = 2026) -> dict[str, int]:
    """Local noisy simulation with the backend's noise model (no QPU)."""
    from qiskit_aer import AerSimulator
    sim = AerSimulator.from_backend(backend)
    return sim.run(isa, shots=shots, seed_simulator=seed).result().get_counts()


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def safe_write_json(path: Path, data: dict) -> Path:
    """Write a NEW file; never overwrite existing evidence."""
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"{path} already exists; refusing to overwrite.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    return path


def _stamp() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")


# ---------------------------------------------------------------------------
# Experiment steps
# ---------------------------------------------------------------------------

def prepare(backend, depth=DEFAULT_DEPTH, seed=DEFAULT_SEED, shots=DEFAULT_SHOTS,
            levels=TRANSPILE_LEVELS, seeds=TRANSPILE_SEEDS) -> dict:
    """Everything up to (not including) submission. No network unless
    `backend` is a live IBM backend object."""
    inst, snapshot, optimal_score = load_instance()
    saved = load_saved_parameters(depth, seed)
    logical = build_logical_circuit(inst, depth, saved["parameters"])
    t0 = time.perf_counter()
    isa, tinfo = transpile_for_backend(logical, backend, levels, seeds)
    tinfo["transpile_seconds"] = round(time.perf_counter() - t0, 2)

    exact = exact_logical_distribution(inst, depth, saved["parameters"])
    isa_ideal = compact_ideal_distribution(isa)
    optimal_x = exhaustive_verification(inst)["ground_states"][0]
    return {
        "inst": inst, "snapshot": snapshot, "optimal_score": optimal_score, "optimal_x": optimal_x,
        "saved": saved, "logical": logical, "isa": isa, "transpile": tinfo,
        "exact": exact,
        "equivalence_tvd": total_variation_distance(exact, isa_ideal),
        "compatibility": compatibility_report(isa, backend, shots, logical),
        "shots": shots,
    }


def _base_record(prep: dict, kind: str) -> dict:
    return {
        "experiment": "wrestling_qaoa_hardware_sampling",
        "record_type": kind,
        "created": dt.datetime.now().isoformat(timespec="seconds"),
        "problem": "W4 mat selection, seed 42, slot 17, 14 variables, k=6, A=B=13, C=1",
        "saved_simulator_parameters": prep["saved"],
        "transpilation": prep["transpile"],
        "compatibility": prep["compatibility"],
        "equivalence_check": {
            "total_variation_distance_ideal_isa_vs_logical": prep["equivalence_tvd"],
            "passes_1e-6": prep["equivalence_tvd"] < 1e-6,
        },
        "exact_noiseless_for_saved_parameters": distribution_summary(prep["exact"], prep["inst"], prep["optimal_x"]),
        "random_guessing": {"feasible_percent": 100 * RANDOM_FEASIBLE,
                            "optimal_percent": 100 * RANDOM_OPTIMAL, "mean_qubo_energy": 61.5},
    }


def print_report(rec: dict) -> None:
    c, s = rec["compatibility"], rec["saved_simulator_parameters"]
    ex, eq = rec["exact_noiseless_for_saved_parameters"], rec["equivalence_check"]
    print(f"\n=== {rec['record_type']} on {c['backend']} ===")
    print(f"Saved angles: p={s['depth']}, sweep seed {s['seed']} -> {[round(v, 4) for v in s['parameters']]}")
    print(f"Qubits: logical {c['logical_qubits']}, physical used {c['physical_qubits_used']} of {c['backend_qubits']}")
    print(f"Depth: logical {c['logical_depth']} -> hardware {c['isa_depth']}")
    print(f"Two-qubit gates on hardware: {c['isa_two_qubit_gates']} "
          f"(range over {rec['transpilation']['candidates_tried']} transpile candidates: "
          f"{rec['transpilation']['two_qubit_gates_range']})")
    print(f"Gate counts: {c['isa_gate_counts']}")
    print(f"All instructions supported by backend: {c['all_instructions_supported_by_target']}")
    print(f"Ideal-equivalence TVD (hardware circuit vs. logical): {eq['total_variation_distance_ideal_isa_vs_logical']:.2e} "
          f"-> {'PASS' if eq['passes_1e-6'] else 'FAIL'}")
    print(f"Estimated circuit duration: {c['estimated_circuit_duration_us']} us; "
          f"sampling time for {c['shots']} shots ~ {c['estimated_sampling_seconds']} s (+ IBM overhead)")
    print(f"Product of gate & readout fidelities (optimistic): {c['product_of_gate_and_readout_fidelities']}")
    print(f"\nExpected if hardware were perfect:  feasible {ex['feasible_percent']:.2f}%, optimal {ex['optimal_percent']:.4f}%")
    print(f"Saved simulator run (4,000 shots):  feasible {s['simulator_feasible_percent']:.2f}%, optimal hits {s['simulator_optimal_shots']}")
    print(f"Random guessing:                    feasible {100 * RANDOM_FEASIBLE:.2f}%, optimal {100 * RANDOM_OPTIMAL:.4f}%")
    for key, label in (("noisy_prediction", "Local noisy prediction (FakeFez)"), ("hardware", "REAL HARDWARE")):
        if key in rec:
            a = rec[key]
            print(f"{label + ':':<35} feasible {a['feasible_percent']:.2f}% "
                  f"[95% CI {a['feasible_percent_ci95_clopper_pearson'][0]:.1f}-{a['feasible_percent_ci95_clopper_pearson'][1]:.1f}], "
                  f"optimal hits {a['optimal_shots']}, mean energy {a['mean_qubo_energy']:.1f}, "
                  f"p(>random) = {a['p_value_feasible_greater_than_random']:.2g}")


def run_preflight(shots=DEFAULT_SHOTS, save=True) -> dict:
    from qiskit_ibm_runtime.fake_provider import FakeFez
    backend = FakeFez()
    prep = prepare(backend, shots=shots)
    rec = _base_record(prep, "local_preflight_fake_backend_no_qpu")
    rec["note"] = ("FakeFez is a static local snapshot of ibm_fez calibration data. "
                   "The noisy prediction is a model, not a hardware measurement.")
    counts = noisy_prediction(prep["isa"], backend, shots)
    rec["noisy_prediction"] = analyze_counts(counts, prep["inst"], prep["snapshot"], prep["optimal_score"])
    rec["noisy_prediction_counts"] = counts
    print_report(rec)
    if save:
        path = safe_write_json(OUT_DIR / f"preflight_fakefez_{_stamp()}.json", rec)
        print(f"\nSaved local preflight to {path.relative_to(ROOT)}")
    return rec


def _read_windows_credential(target: str) -> str:
    """Read a Generic credential's secret from Windows Credential Manager
    (CredReadW). The secret is returned in memory only: never printed,
    logged or written to disk by this script."""
    import ctypes
    from ctypes import wintypes

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                    ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                    ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                    ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
                    ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    advapi32.CredReadW.restype = wintypes.BOOL
    advapi32.CredFree.argtypes = [ctypes.c_void_p]
    pcred = ctypes.POINTER(CREDENTIAL)()
    CRED_TYPE_GENERIC = 1
    if not advapi32.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(pcred)):
        raise LookupError(f"Windows credential {target!r} not found "
                          f"(Win32 error {ctypes.get_last_error()}).")
    try:
        c = pcred.contents
        blob = bytes(c.CredentialBlob[:c.CredentialBlobSize])
    finally:
        advapi32.CredFree(pcred)
    # Credential Manager / cmdkey store UTF-16LE; fall back to UTF-8.
    for enc in ("utf-16-le", "utf-8"):
        try:
            value = blob.decode(enc).strip().strip("\x00")
        except UnicodeDecodeError:
            continue
        if value and value.isascii() and value.isprintable():
            return value
    raise ValueError(f"Windows credential {target!r} is empty or not readable text.")


def _service(credential: str | None = None):
    """Connect to IBM Quantum.

    * credential=None: use the account saved by qiskit-ibm-runtime
      (~/.qiskit/qiskit-ibm.json).
    * credential="<name>": read the API key from that Windows Credential
      Manager entry and authenticate in memory only (nothing is saved).
    """
    from qiskit_ibm_runtime import QiskitRuntimeService
    if credential is None:
        return QiskitRuntimeService()
    secret = _read_windows_credential(credential)
    try:
        return QiskitRuntimeService(channel="ibm_quantum_platform", token=secret)
    except Exception as exc:
        # never let the secret appear in an error message
        raise RuntimeError(f"IBM authentication failed ({type(exc).__name__}): "
                           f"{str(exc).replace(secret, '***')}") from None
    finally:
        del secret


def run_check_live(backend_name=DEFAULT_BACKEND, shots=DEFAULT_SHOTS, credential=None) -> dict:
    service = _service(credential)
    backend = service.backend(backend_name)
    status = backend.status()
    try:
        usage = service.usage()
        print("Account usage (from IBM):", {k: v for k, v in usage.items()
                                            if "usage" in k or "period" in k or k == "plan_id"})
    except Exception as exc:
        print(f"Account usage not available ({type(exc).__name__}).")
    prep = prepare(backend, shots=shots)
    rec = _base_record(prep, "live_backend_check_no_job_submitted")
    rec["backend_status"] = {"operational": status.operational, "pending_jobs": status.pending_jobs,
                             "status_msg": status.status_msg}
    print_report(rec)
    print(f"Backend status: operational={status.operational}, pending jobs={status.pending_jobs}")
    print("No job was submitted.")
    return rec


def submit_to_ibm(backend_name=DEFAULT_BACKEND, shots=DEFAULT_SHOTS, approve=False,
                  credential=None) -> dict:
    """Send ONE sampling job. Requires explicit approval."""
    if not approve:
        raise PermissionError("Hardware submission requires explicit approval "
                              "(--i-approve-qpu-usage). Nothing was sent.")
    from qiskit_ibm_runtime import SamplerV2
    backend = _service(credential).backend(backend_name)
    prep = prepare(backend, shots=shots)
    if not prep["compatibility"]["all_instructions_supported_by_target"]:
        raise RuntimeError("Transpiled circuit contains unsupported instructions; not submitting.")
    if prep["equivalence_tvd"] >= 1e-6:
        raise RuntimeError("Hardware circuit is not equivalent to the logical circuit; not submitting.")

    rec = _base_record(prep, "ibm_hardware_run")
    pending = safe_write_json(OUT_DIR / f"hardware_job_{backend_name}_{_stamp()}_submitted.json", rec)

    sampler = SamplerV2(mode=backend)
    job = sampler.run([prep["isa"]], shots=shots)
    job_id = job.job_id()
    print(f"Submitted job {job_id} to {backend_name}. Waiting for results...")
    rec["job"] = {"job_id": job_id, "backend": backend_name, "shots": shots,
                  "submitted": dt.datetime.now().isoformat(timespec="seconds"),
                  "sampler_options": "qiskit-ibm-runtime SamplerV2 defaults (no error mitigation)"}
    # record the job id immediately in a second new file, in case waiting is interrupted
    safe_write_json(pending.with_name(pending.stem.replace("_submitted", f"_{job_id}_id") + ".json"),
                    {"job_id": job_id, "backend": backend_name, "shots": shots})
    return _finish(rec, job, prep)


def _finish(rec: dict, job, prep: dict) -> dict:
    result = job.result()
    counts = result[0].data.meas.get_counts()
    rec["hardware"] = analyze_counts(counts, prep["inst"], prep["snapshot"], prep["optimal_score"])
    rec["hardware_counts"] = counts
    try:
        rec["job"]["usage_seconds_reported_by_ibm"] = job.usage()
    except Exception:
        rec["job"]["usage_seconds_reported_by_ibm"] = None
    rec["job"]["status"] = str(job.status())
    print_report(rec)
    path = safe_write_json(OUT_DIR / f"hardware_result_{rec['job']['backend']}_{rec['job']['job_id']}.json", rec)
    print(f"\nSaved hardware result to {path.relative_to(ROOT)}")
    return rec


def fetch_job(job_id: str, credential=None) -> dict:
    """Re-attach to a finished job (e.g. after a disconnect) and analyze it."""
    service = _service(credential)
    job = service.job(job_id)
    backend = job.backend()
    prep = prepare(backend, shots=DEFAULT_SHOTS)
    rec = _base_record(prep, "ibm_hardware_run")
    rec["job"] = {"job_id": job_id, "backend": backend.name, "shots": DEFAULT_SHOTS,
                  "note": "fetched after submission; transpilation re-derived deterministically"}
    return _finish(rec, job, prep)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("preflight", help="local only: FakeFez transpile + noisy prediction (default)")
    p.add_argument("--shots", type=int, default=DEFAULT_SHOTS)
    p.add_argument("--no-save", action="store_true")
    cred_help = ("name of a Windows Credential Manager entry holding the IBM API key "
                 "(default: use the account saved in ~/.qiskit)")
    c = sub.add_parser("check-live", help="read live backend + transpile; submits nothing")
    c.add_argument("--backend", default=DEFAULT_BACKEND)
    c.add_argument("--credential", default=None, help=cred_help)
    s = sub.add_parser("submit", help="send ONE sampling job (needs approval flag)")
    s.add_argument("--backend", default=DEFAULT_BACKEND)
    s.add_argument("--shots", type=int, default=DEFAULT_SHOTS)
    s.add_argument("--i-approve-qpu-usage", action="store_true", dest="approve")
    s.add_argument("--credential", default=None, help=cred_help)
    f = sub.add_parser("fetch", help="analyze a finished job by id")
    f.add_argument("--job-id", required=True)
    f.add_argument("--credential", default=None, help=cred_help)
    args = ap.parse_args(argv)

    if args.cmd in (None, "preflight"):
        run_preflight(shots=getattr(args, "shots", DEFAULT_SHOTS), save=not getattr(args, "no_save", False))
    elif args.cmd == "check-live":
        run_check_live(args.backend, credential=args.credential)
    elif args.cmd == "submit":
        submit_to_ibm(args.backend, args.shots, approve=args.approve, credential=args.credential)
    elif args.cmd == "fetch":
        fetch_job(args.job_id, credential=args.credential)


if __name__ == "__main__":
    main()
