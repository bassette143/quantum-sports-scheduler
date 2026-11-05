# Quantum vs. Classical Sports Tournament Scheduling

A hackathon research project for the **Florida Qiskit Fallfest** comparing a
classical Python solver against a quantum QAOA experiment on the same
sports-scheduling problem.

**Research question:** Can quantum optimization solve sports scheduling
problems efficiently compared with traditional Python algorithms?

**Honest headline result:** QAOA (18 qubits, simulated) found genuinely valid
tournament schedules far more often than random guessing, and deeper circuits
improved reliability — but classical methods dominated on the same problem:
exact backtracking in microseconds and simulated annealing (a classical
heuristic on the identical QUBO) in milliseconds, both with 100% success.
We claim no quantum advantage. See [RESULTS.md](./RESULTS.md).

## The problem

Schedule a 4-team double round-robin tournament (teams A, B, C, D):

- Each team plays every other team twice (once at each team's home venue).
- Each team plays exactly one game per round.
- 6 rounds, 2 games per round, 12 games total.

Why this matters in the real world: see [USE-CASE.md](./USE-CASE.md).
What we simplified and why: see [LIMITATIONS.md](./LIMITATIONS.md).

## Project structure

| File | Purpose |
|---|---|
| `classical_scheduler.py` | Classical backtracking solver for the full double round-robin |
| `schedule_validator.py` | Independent constraint validator (judges classical AND quantum output) |
| `qubo_formulation.py` | 18-variable QUBO model of the simplified single round-robin + mirroring |
| `verify_qubo.py` | Exhaustive proof (all 262,144 assignments) that the QUBO is correct |
| `quantum_scheduler.py` | 18-qubit QAOA experiment (Qiskit + Aer simulator) |
| `simulated_annealing.py` | Classical simulated-annealing solver on the same QUBO |
| `wrestling/` | Wrestling tournament simulation: rosters (W1), brackets (W2), mat scheduling + independent validator (W3), mat-selection QUBO feasibility study (W4, classical only) |
| `benchmark.py` | Controlled depth sweep (p=1,2,3 x 5 seeds) vs classical/random baselines |
| `benchmark_sa.py` | Simulated annealing benchmark (30 seeds) vs stored QAOA results |
| `tests/` | 111 automated pytest tests |
| `results/` | Reproducible JSON results and charts |

## Installation

Requires Windows/macOS/Linux with **Python 3.11** (tested on 3.11.9,
Windows 11).

```powershell
# from the project folder
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Exact tested package versions are pinned in [requirements.txt](./requirements.txt)
(qiskit 2.6.1, qiskit-aer 0.18.2, scipy 1.17.1, numpy 2.4.6,
matplotlib 3.11.2, pytest 9.2.0).

## Reproducing every result

All experiments use fixed random seeds. Run from the project folder with the
venv Python:

```powershell
# 1. Classical solver for the full 4-team double round-robin
.\.venv\Scripts\python.exe classical_scheduler.py

# 2. Exhaustive QUBO verification (checks all 262,144 assignments)
.\.venv\Scripts\python.exe verify_qubo.py

# 3. Single QAOA experiment (p=1, seed 42)
.\.venv\Scripts\python.exe quantum_scheduler.py

# 4. Full benchmark sweep (p=1,2,3 x 5 seeds + baselines + charts, ~2 min)
.\.venv\Scripts\python.exe benchmark.py

# 5. Simulated annealing benchmark (pilot + 30 seeds, seconds)
.\.venv\Scripts\python.exe benchmark_sa.py

# 6. Wrestling simulation (rosters -> brackets -> mat schedule -> QUBO study)
.\.venv\Scripts\python.exe -m wrestling.rosters
.\.venv\Scripts\python.exe -m wrestling.brackets
.\.venv\Scripts\python.exe -m wrestling.mat_schedule
.\.venv\Scripts\python.exe -m wrestling.mat_qubo

# 7. Test suite (111 tests)
.\.venv\Scripts\python.exe -m pytest -v
```

Outputs are written to `results/` as JSON plus `benchmark_charts.png` and
`solver_comparison_charts.png`. Note: every step except `wrestling.rosters`
and the test suite **overwrites** its file in `results/`. Copy the folder
first if you want to keep the recorded measurements.

## How it works, briefly

1. **Classical:** exact backtracking fills the schedule round by round,
   undoing choices that lead to dead ends. For 4 teams this takes
   microseconds and always succeeds.
2. **Quantum:** the simplified scheduling problem is encoded as a QUBO —
   an energy function over 18 binary variables ("matchup m happens in
   round r") where energy 0 means a valid schedule. The QUBO was verified
   by brute force before any quantum code was written. QAOA, a hybrid
   quantum-classical algorithm, prepares an 18-qubit state whose
   measurement outcomes are biased toward low energy, and a classical
   optimizer (COBYLA) tunes the circuit parameters.
3. **Fair judging:** every schedule — classical or quantum — must pass the
   same independent validator, and the quantum bitstrings are scored with
   the same exhaustively verified energy function.

Full methodology and the measured numbers: [RESULTS.md](./RESULTS.md).

## Scientific honesty rules used throughout

- No quantum advantage claimed; none was measured.
- All reported values are actual measurements (`time.perf_counter()`,
  fixed seeds, saved JSON). Nothing is estimated or invented.
- The classical baseline was never artificially slowed down.
- Limitations are documented openly in [LIMITATIONS.md](./LIMITATIONS.md).

## Research reference

Problem class based on the sports scheduling benchmark in the
[Quantum Optimization Benchmarking Library (QOBLIB)](https://git.zib.de/qopt/qoblib-quantum-optimization-benchmarking-library/-/tree/main/05-sports?ref_type=heads).
Our 4-team experiment is a deliberately simplified educational instance, not
a reproduction of the QOBLIB benchmark (see LIMITATIONS.md).
