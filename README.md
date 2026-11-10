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

**Wrestling extension (W1–W5D):** a simulated 12-school wrestling
tournament was scheduled classically onto 6 mats in 20 time slots, which
equals the proven lower bound. One 14-variable mat-selection decision was
then solved with QAOA on a noiseless simulator. Over 5 seeds, QAOA reached
14.9% (p=1) and 18.7% (p=2) feasible samples against 7.9% for random
guessing, and found the optimum in only some runs. Classical greedy finds
the optimum in about 10 µs, every time. p=2 was not consistently better
than p=1, and no quantum advantage was demonstrated.

**Real IBM quantum hardware (Nov 10, 2026):** we ran the same 14-qubit
wrestling QAOA circuit on IBM's **`ibm_fez`** processor as one job of 4,000
shots (job `dbppooc4148s739v0lsg`). We reused the saved simulator angles
(p=1, seed 22), so nothing was optimized on the hardware. Compiled for the chip,
the circuit had depth 356 and 280 two-qubit gates, and we checked it gives the
same ideal probabilities as the simulator circuit. **Measured: 13.2% of hardware
samples were valid schedules (95% CI 12.2–14.3%) vs. 7.9% for random guessing**
(p ≈ 7×10⁻³¹). All 423 distinct valid answers passed the independent validator.
Noise mattered: the same angles give 23.5% in our simulator run, and a pre-run
FakeFez noise-model *prediction* was 17.4%. The single optimal answer did not
appear on hardware (best score 11 of 12). An earlier 2-qubit Bell-state test
(job `dbovmec4148s739tmr50`, 95/100 correlated outcomes) checked the workflow.
Raw data: [results/hardware/](./results/hardware/).

## Hackathon submission materials

| Item | File |
|---|---|
| Step-by-step notebook with saved outputs (simulator + hardware) | [submission_notebook.ipynb](./submission_notebook.ipynb) |
| Slides | [presentation/Quantum_Sports_Scheduler_Hackathon_2026_v3.pptx](./presentation/Quantum_Sports_Scheduler_Hackathon_2026_v3.pptx) |
| Submission description | [SUBMISSION_DESCRIPTION.md](./SUBMISSION_DESCRIPTION.md) |
| Five-minute video script | [FINAL_VIDEO_SCRIPT.md](./FINAL_VIDEO_SCRIPT.md) |
| Hardware script and results | [hardware/qaoa_hardware.py](./hardware/qaoa_hardware.py), [results/hardware/](./results/hardware/) |

**Official benchmark validation (RobinX / QOBLIB):** we built an
independent parser and hard-constraint validator for the official QOBLIB
05-sports benchmark format (RobinX XML). On the official 8-team instance
`Addition_000_Small` (56 games, 14 time slots, phased double round-robin),
it checks all **161 hard constraints** (CA4 ×85, GA1 ×31, BR1 ×44, BR2 ×1)
plus the round-robin structure. The **published feasible solution passes
with zero violations**. 46 new tests confirm this. They also deliberately
break each constraint type and check that the violation is caught, and that
unsupported constraint types are reported rather than skipped. **We validated
the official solution; we did not generate it, with QAOA or any of our
solvers.** Solving the benchmark is future work.

## The problems

**1. Round-robin.** Schedule a 4-team double round-robin tournament
(teams A, B, C, D):

- Each team plays every other team twice (once at each team's home venue).
- Each team plays exactly one game per round.
- 6 rounds, 2 games per round, 12 games total.

**2. Wrestling tournament.** 12 fictional schools, 14 weight classes, 132
wrestlers and 118 championship-bracket matches. Every match goes on one of 6
mats in a time slot, respecting bracket order and a 1-slot rest. The quantum
part chooses which 6 of the 14 matches ready at time slot 17 should run, one
per weight class, to maximize bracket progression.

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
| `benchmark.py` | Controlled depth sweep (p=1,2,3 x 5 seeds) vs classical/random baselines |
| `benchmark_sa.py` | Simulated annealing benchmark (30 seeds) vs stored QAOA results |
| `wrestling/rosters.py`, `brackets.py` | W1–W2: random rosters and single-elimination brackets |
| `wrestling/mat_schedule.py`, `mat_validator.py` | W3: greedy mat scheduler and independent mat-schedule validator |
| `wrestling/mat_qubo.py` | W4: 14-variable mat-selection QUBO, exhaustive verification, classical brute force and greedy |
| `wrestling/mat_qaoa.py` | W5: QAOA on the W4 QUBO (p=1, seed 42) |
| `wrestling/mat_qaoa_depth.py` | W5B: single p=2 run (refuses to overwrite) |
| `wrestling/mat_qaoa_sweep.py` | W5C: 5-seed sweep at p=1 and p=2, plus CI correction |
| `wrestling/mat_qaoa_sampling.py` | W5D: fixed vs independent sampling seeds, exact statevector evaluation |
| `robinx/parser.py` | Reads official RobinX/ITC2021 instance and solution files (XML or gzip) |
| `robinx/validator.py` | Independent hard-constraint validator (structure, CA4, GA1, BR1, BR2); reports any unsupported constraint explicitly |
| `data/robinx/` | Unmodified official QOBLIB instance `Addition_000_Small` and its published solution, with provenance and checksums in `SOURCE.md` |
| `hardware/qaoa_hardware.py` | Guarded IBM hardware run of the wrestling QAOA: local FakeFez preflight, read-only live check, one approved submission, analysis vs. simulator / prediction / random |
| `app.py` | Read-only Streamlit dashboard: schedule, classical vs. quantum, charts, IBM hardware, official benchmark |
| `submission_notebook.ipynb` | Beginner-friendly walkthrough of the whole project with saved outputs |
| `tests/` | 228 automated pytest tests (169 original + 46 RobinX + 13 hardware script) |
| `results/` | Reproducible JSON results and charts from the simulator and classical experiments |
| `results/hardware/` | IBM `ibm_fez` job record, raw hardware counts and analysis, plus the pre-run FakeFez prediction |
| `presentation/` | Final slides |
| `PRESENTATION.md` | Team presentation outline and safe demo script |

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
matplotlib 3.11.2, pytest 9.2.0; dashboard: streamlit 1.65.0, pandas 3.1.1;
IBM hardware and FakeFez: qiskit-ibm-runtime 0.51.0).

Check the installation by running the test suite. All 228 tests should pass:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The notebook opens directly on GitHub or in VS Code with its outputs already
saved. To re-run it yourself, also install Jupyter (`pip install jupyter`).

## Interactive dashboard

The quickest way to explore the project is the read-only Streamlit dashboard:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

It opens at `http://localhost:8501` and has five sections:

1. **Wrestling Schedule:** all 118 matches on 6 mats × 20 time slots.
2. **Classical vs. Quantum:** the 18-qubit round-robin, the 14-qubit wrestling
   snapshot and the full tournament, kept separate because they are different
   problems.
3. **Charts:** the saved benchmark charts.
4. **IBM Quantum Hardware:** the wrestling QAOA run on `ibm_fez` (measured
   result vs. simulator, noise-model prediction and random guessing), then the
   earlier 2-qubit Bell-state test and the local hardware-preparation report.
5. **Official Benchmark Validation:** the official QOBLIB 8-team solution checked
   against all 161 hard constraints, plus a live demo that introduces a mistake
   and shows the validator catching it.

The dashboard only reads saved files. It never reruns QAOA, regenerates
results, or submits IBM Quantum jobs.

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

# 7. Wrestling QAOA (Aer simulator, seconds each)
.\.venv\Scripts\python.exe -m wrestling.mat_qaoa            # W5: p=1, seed 42
.\.venv\Scripts\python.exe -m wrestling.mat_qaoa_depth      # W5B: p=2, seed 42
.\.venv\Scripts\python.exe -m wrestling.mat_qaoa_sweep      # W5C: 5 seeds x p=1,2
.\.venv\Scripts\python.exe -m wrestling.mat_qaoa_sampling   # W5D: 10 matched pairs

# 8. Test suite (228 tests)
.\.venv\Scripts\python.exe -m pytest -v

# 9. Validate the official RobinX benchmark solution (reads files only, writes nothing)
.\.venv\Scripts\python.exe -m robinx.validator

# 10. IBM hardware experiment (see "Running on IBM hardware" below)
.\.venv\Scripts\python.exe -m hardware.qaoa_hardware preflight     # local only, ~4 min
```

### Running on IBM hardware

`hardware/qaoa_hardware.py` has four commands. Only `submit` uses QPU time.

```powershell
# Local only: transpile for a FakeFez snapshot, equivalence check, noisy prediction
.\.venv\Scripts\python.exe -m hardware.qaoa_hardware preflight

# Read the live backend (status, queue, calibration) and re-check the circuit; submits nothing
.\.venv\Scripts\python.exe -m hardware.qaoa_hardware check-live --backend ibm_fez --credential <NAME>

# Send ONE 4,000-shot job (refuses to run without the approval flag)
.\.venv\Scripts\python.exe -m hardware.qaoa_hardware submit --backend ibm_fez --credential <NAME> --i-approve-qpu-usage

# Re-attach to a finished job and analyze it
.\.venv\Scripts\python.exe -m hardware.qaoa_hardware fetch --job-id <JOB_ID> --credential <NAME>
```

**Credentials.** The script never takes an API key on the command line and
never stores one. `--credential <NAME>` reads the IBM Quantum API key from a
*Generic* credential with that name in Windows Credential Manager, in memory
only. Leave out `--credential` to use an account saved with
`QiskitRuntimeService.save_account(...)` in `~/.qiskit` instead. Never commit
keys: `.gitignore` excludes `.env`, `*.key` and `qiskit-ibm.json`.

Hardware results are written to **new** files in `results/hardware/`. The
script refuses to overwrite existing files.

Step 9 prints a report ending in `Verdict: FULLY VERIFIED`. To check a
different instance and solution, pass both paths:
`python -m robinx.validator <instance.xml[.gz]> <solution.xml[.gz]>`.
Instances that contain constraint types we have not implemented (CA1–CA3,
FA2, SE1) are reported as **not fully verified**, never as passing.

Outputs are written to `results/` as JSON plus `benchmark_charts.png` and
`solver_comparison_charts.png`.

**Overwrite behaviour.** Steps 1–6 and `wrestling.mat_qaoa` **overwrite**
their file in `results/` (only `wrestling.rosters` writes nothing). The
W5B, W5C and W5D scripts **refuse to run** if their output file already
exists, so they cannot overwrite recorded evidence. To reproduce
everything, run in a copy of the folder (see the demo script in
[PRESENTATION.md](./PRESENTATION.md)).

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
4. **Hardware:** the simulator-optimized wrestling circuit is compiled for
   IBM `ibm_fez`, checked to give the same ideal probabilities, and sampled
   once on the real chip. Its valid-schedule rate is then compared with the
   simulator, a noise-model prediction and random guessing.

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

**Official benchmark data.** The files in `data/robinx/` are unmodified
copies of the instance and published solution from QOBLIB 05-sports
(commit `ee10460`), distributed under the
[Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/)
license. Instances are from D. Van Bulck and D. Goossens, "The International
Timetabling Competition on Sports Timetabling (ITC2021)," *European Journal
of Operational Research*, 2023. The solution was contributed to QOBLIB by
Team MODAL. Full provenance: [data/robinx/SOURCE.md](./data/robinx/SOURCE.md). The wrestling
tournament uses fictional data and simplified rules. It is not based on
official competition rules.
