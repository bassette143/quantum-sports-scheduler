"""Phase W5B: controlled QAOA depth experiment on the wrestling mat QUBO.

Runs ONE depth (default p=2) with the identical 14-variable W4 QUBO,
penalties (A = B = 13, C = 1), seed 42 and optimizer/shot settings as the
committed p=1 experiment (wrestling/mat_qaoa.py), then compares against the
stored p=1 results in results/wrestling_qaoa_result.json.

Safety rules:
  * Pilot first; the main run is skipped if its estimated time exceeds
    PILOT_BUDGET_SECONDS.
  * Output goes to results/wrestling_qaoa_p<depth>_result.json and an
    existing file is NEVER overwritten (the p=1 file has a different name
    and is only read).
  * Depth must be given explicitly; nothing escalates to higher p
    automatically.

Run:  python -m wrestling.mat_qaoa_depth          (p=2)
"""

import json
import sys
from pathlib import Path

from wrestling.mat_qaoa import (
    MAIN,
    PILOT,
    PILOT_BUDGET_SECONDS,
    QAOA_SEED,
    run_qaoa,
)
from wrestling.mat_qubo import (
    build_qubo_instance,
    classical_brute_force,
    extract_snapshot,
    is_feasible,
)
from wrestling.rosters import DEFAULT_SEED

RESULTS_DIR = Path(__file__).parent.parent / "results"
P1_FILE = RESULTS_DIR / "wrestling_qaoa_result.json"


INSTANCE_KEYS = ("pool", "weights", "scores", "k", "penalty_A", "penalty_B",
                 "objective_C")


def output_path(depth: int, results_dir: Path | None = None) -> Path:
    """Where a depth's results go; raises SystemExit for p<2 or if the
    file already exists (existing evidence is never overwritten)."""
    if depth < 2:
        raise SystemExit("Use wrestling.mat_qaoa for p=1 (already recorded).")
    out = (results_dir or RESULTS_DIR) / f"wrestling_qaoa_p{depth}_result.json"
    if out.exists():
        raise SystemExit(f"{out.name} already exists; refusing to overwrite.")
    return out


def instance_matches(recorded: dict, inst: dict) -> bool:
    """True only if the QUBO instance equals the recorded p=1 instance."""
    return all(recorded.get(k) == inst.get(k) for k in INSTANCE_KEYS)


def summarize(run: dict) -> dict:
    """The comparison metrics requested for each depth."""
    a, t = run["analysis"], run["timings_seconds"]
    return {
        "depth_p": run["qaoa_depth_p"],
        "feasible_percent": a["feasible_percent"],
        "optimal_percent": a["optimal_percent"],
        "feasible_shots": a["feasible_shots"],
        "optimal_shots": a["optimal_shots"],
        "shots": a["shots"],
        "best_feasible_score": a["best_feasible_score"],
        "best_qubo_energy": a["best_energy"],
        "final_mean_energy": run["final_mean_energy"],
        "best_mean_energy": run["best_mean_energy"],
        "optimizer_evaluations": run["optimizer_evaluations"],
        "optimizer_maxiter": run["optimizer_maxiter"],
        "total_shots": run["total_shots"],
        "circuit_depth": run["circuit_depth"],
        "two_qubit_gates": run["two_qubit_gates"],
        "quantum_pipeline_time_s": t["quantum_pipeline_total"],
        "sampling_time_s": t["circuit_sampling_only"],
        "validator": a["validation"],
    }


def main(depth: int = 2, seed: int = DEFAULT_SEED) -> None:
    out = output_path(depth)

    p1 = json.loads(P1_FILE.read_text())
    snapshot = extract_snapshot(seed)
    inst = build_qubo_instance(snapshot)
    n = len(inst["pool"])

    # Guard: the instance must be identical to the one p=1 used.
    if not instance_matches(p1["instance"], inst):
        raise SystemExit("STOP: instance differs from the recorded p=1 run.")
    optimal = classical_brute_force(inst)["best_score"]
    n_feasible = sum(1 for x in range(2 ** n) if is_feasible(x, inst))
    rand_feas, rand_opt = 100 * n_feasible / 2 ** n, 100 / 2 ** n

    print(f"=== Phase W5B: QAOA p={depth} on the wrestling mat QUBO ===")
    print("Instance identical to recorded p=1 run: True")
    print(f"Classical optimum {optimal}; random exact: feasible "
          f"{rand_feas:.3f}%, optimal {rand_opt:.4f}%\n")

    pilot_cfg = {**PILOT, "reps": depth}
    main_cfg = {**MAIN, "reps": depth}
    print(f"Pilot: {pilot_cfg}")
    pilot = run_qaoa(inst, snapshot, optimal, seed=QAOA_SEED,
                     validate=False, **pilot_cfg)
    pt = pilot["timings_seconds"]["quantum_pipeline_total"]
    est = pt * (main_cfg["maxiter"] * main_cfg["opt_shots"]
                + main_cfg["final_shots"]) / (
        pilot_cfg["maxiter"] * pilot_cfg["opt_shots"]
        + pilot_cfg["final_shots"])
    print(f"  pilot {pt:.2f} s -> main estimate ~{est:.0f} s "
          f"(budget {PILOT_BUDGET_SECONDS} s)\n")
    if est > PILOT_BUDGET_SECONDS:
        print("STOP: estimate exceeds budget; main run skipped.")
        return

    print(f"Main: {main_cfg}, seed {QAOA_SEED}")
    run = run_qaoa(inst, snapshot, optimal, seed=QAOA_SEED, **main_cfg)
    s_new = summarize(run)
    s_p1 = summarize(p1["main"])

    rows = [
        ("feasible samples %", "feasible_percent", ".2f"),
        ("optimal samples %", "optimal_percent", ".3f"),
        ("best feasible score", "best_feasible_score", ""),
        ("best QUBO energy", "best_qubo_energy", ""),
        ("final mean energy", "final_mean_energy", ".2f"),
        ("optimizer evaluations", "optimizer_evaluations", ""),
        ("total shots", "total_shots", ","),
        ("circuit depth", "circuit_depth", ""),
        ("two-qubit (CX) gates", "two_qubit_gates", ""),
        ("pipeline time (s)", "quantum_pipeline_time_s", ".2f"),
    ]
    print(f"\n{'metric':<24}{'p=1 (stored)':>14}{'p=' + str(depth):>12}")
    print("-" * 50)
    for label, key, fmt in rows:
        print(f"{label:<24}{format(s_p1[key], fmt):>14}"
              f"{format(s_new[key], fmt):>12}")
    print(f"{'random (exact)':<24}{'feasible ' + format(rand_feas, '.3f') + '%':>14}"
          f"{'opt ' + format(rand_opt, '.4f') + '%':>12}")
    v = s_new["validator"]
    print(f"\nIndependent validator (p={depth}): {v['distinct_feasible_checked']} "
          f"distinct feasible selections, {v['validator_failures']} failures")

    record = {
        "experiment": f"wrestling_mat_qaoa_phase_w5b_p{depth}",
        "instance_identical_to_p1": True,
        "classical_optimum": optimal,
        "uniform_random_exact": {"feasible_percent": rand_feas,
                                 "optimal_percent": rand_opt},
        "pilot": {k: v for k, v in pilot.items() if k != "final_counts"},
        "main": run,
        "comparison": {"p1_stored": s_p1, f"p{depth}": s_new},
        "notes": [
            "Single seed (42): exploratory, not a trend.",
            "Same QUBO, penalties, optimizer (COBYLA maxiter 40, rhobeg 0.5) "
            "and shot counts as p=1; p=2 has 4 parameters instead of 2.",
            "Noiseless Aer simulator; no hardware.",
        ],
    }
    out.write_text(json.dumps(record, indent=2))
    print(f"\nResults saved to {out}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 2)
