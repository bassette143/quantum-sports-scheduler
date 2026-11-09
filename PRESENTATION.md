# Presentation Outline: Quantum vs. Classical Wrestling Scheduling

Florida Qiskit Fallfest, about 10–12 minutes, three presenters.
Every number below comes from the recorded JSON in `results/` (see
RESULTS.md). Do not quote numbers that are not in RESULTS.md.

| Speaker | Sections | Time |
|---|---|---|
| Presenter 1 | 1. Real-world problem · 2. Classical scheduling and validation | ~4 min |
| Presenter 2 | 3. QUBO and QAOA implementation · live demo | ~4 min |
| Presenter 3 | 4. Results and comparison · 5. Lessons and future work | ~4 min |

---

## 1. The real-world problem (Presenter 1)

- Wrestling tournaments run many weight classes at once on a few mats.
  Organizers must run every match in bracket order, give wrestlers rest
  between bouts, and keep mats busy.
- Our simulation: **12 schools, 14 weight classes, 132 wrestlers, 14
  single-elimination brackets, 60 byes, 118 matches, 6 mats.**
- Fictional data and simplified rules. There are no consolation brackets,
  real match durations or official seeding (LIMITATIONS.md §5).
- Background: we first tested the same method on a 4-team round-robin
  (18 qubits). Classical won there too.

## 2. Classical scheduling and validation (Presenter 1)

- A greedy scheduler puts each match on a mat in the earliest slot that
  respects bracket order and a 1-slot rest.
- Result: **20 time slots, equal to the proven lower bound** (118 matches
  ÷ 6 mats, rounded up). Mat utilization is 98.3%.
  Under this model no solver, classical or quantum, can do better.
- An **independent validator** checks every schedule: every match once,
  no double-booked mats, bracket order and rest respected. It checks all
  classical and quantum outputs.
- Key point: validate the answer, not the algorithm.

## 3. QUBO and QAOA implementation (Presenter 2)

- Since the full schedule is already optimal, we gave quantum a smaller
  real decision: **at time slot 17, choose 6 of the 14 ready matches** (one
  per mat, at most one per weight class) to maximize bracket progression.
- **QUBO:** 14 binary variables, so 14 qubits.
  H = 13·(Σx − 6)² + 13·(same-weight pairs) − Σ(progression score).
  Lower energy means a better selection. The energy reaches its minimum
  only at feasible selections.
- **Verified first:** all 16,384 selections were checked exhaustively.
  1,289 are feasible, 1 is optimal (score 12), and the quantum (Ising) form
  matches on every selection.
- **QAOA:** Qiskit, Aer **noiseless simulator** (no hardware), COBYLA
  optimizer, 1,000 shots per step and 4,000 final shots.
  Circuit: p=1 has 182 two-qubit gates; p=2 has 364.
- → **Live demo** (see the script below).

## 4. Results and comparison (Presenter 3)

Slide table, five seeds per depth (W5C):

| | QAOA p=1 | QAOA p=2 | Random guessing | Classical greedy |
|---|---|---|---|---|
| Feasible samples | 14.9 ± 8.5% | 18.7 ± 9.0% | 7.9% | always feasible |
| Runs finding the optimum | 3/5 | 2/5 | 21.7% per run | 5/5 |
| Runtime | ~1.4 s | ~2.8 s | – | ~10 µs |

Talking points:
- QAOA does better than random guessing on feasibility on average, but
  results vary greatly from seed to seed (about 6% to 28%).
- **p=2 was not consistently better than p=1** (not statistically
  significant, p = 0.42).
- Our first single run (seed 42) looked impressive at p=2 (the optimum was
  found, 20.8% feasible), but **it did not reproduce** across seeds. This
  is why we ran the sweep.
- Optimizer check (W5D): the optimizer's own score was too optimistic in
  19 of 20 runs. Giving every step fresh random seeds did **not** fix it.
  The cause is selection bias from noisy estimates.
- **Classical greedy finds the optimum in about 10 µs, every time.
  No quantum advantage.**

## 5. Lessons learned and future possibilities (Presenter 3)

Lessons:
1. Verify the model exhaustively before running any quantum code.
2. One lucky run is not a result. Use multiple seeds and confidence
   intervals.
3. Judge with independent measurements, not the optimizer's own number.
4. Strong classical baselines matter: greedy solved our instance
   instantly.

Future possibilities (untested, so present these as ideas only):
- Tune the penalty weights, or use objectives that focus on the best
  samples (for example CVaR).
- Larger optimizer budgets, more seeds, and p=3 or deeper.
- Noise-model simulation, then real IBM hardware.
- Harder instances where greedy is not already optimal.

**Do not say:** "quantum was faster," "quantum beat classical," "deeper
circuits improve results," or anything about hardware performance. None of
these were measured.

---

## Demo script (safe: does not modify recorded results)

Run in **PowerShell** from the project folder. Total time is about 30 s
(the test suite takes about 14 s of that). Tested end to end on
2026-11-04.

### Part A: safe in the project folder

```powershell
# 1. Full test suite (writes only Python caches)
.\.venv\Scripts\python.exe -m pytest -q

# 2. Roster and bracket statistics (prints only, writes no files)
.\.venv\Scripts\python.exe -m wrestling.rosters

# 3. Evidence protection: these scripts refuse to overwrite recorded results
.\.venv\Scripts\python.exe -m wrestling.mat_qaoa_depth
.\.venv\Scripts\python.exe -m wrestling.mat_qaoa_sweep
```

Step 3 prints "... already exists; refusing to overwrite." PowerShell may
show it in red as an error. That is expected: it is the protection working.

Do **not** run these in the project folder during a demo. They overwrite
recorded files: `classical_scheduler.py`, `verify_qubo.py`,
`quantum_scheduler.py`, `benchmark.py`, `benchmark_sa.py`,
`wrestling.brackets`, `wrestling.mat_schedule`, `wrestling.mat_qubo`,
`wrestling.mat_qaoa`.

### Part B: live wrestling pipeline in a throwaway copy

```powershell
$proj = (Get-Location).Path
$py   = Join-Path $proj ".venv\Scripts\python.exe"
$demo = Join-Path $env:TEMP ("qss-demo-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Path (Join-Path $demo "results") | Out-Null
Copy-Item -Path (Join-Path $proj "wrestling") -Destination $demo -Recurse
Push-Location $demo
& $py -m wrestling.brackets       # 14 brackets, 118 matches
& $py -m wrestling.mat_schedule   # 20 slots = lower bound, VALID
& $py -m wrestling.mat_qubo       # 14-variable QUBO, exhaustive check
& $py -m wrestling.mat_qaoa       # QAOA p=1 on the simulator (~2 s)
Pop-Location
Write-Host "Demo outputs are in $demo"
```

The copy writes only inside `$demo` (a new, timestamped temp folder). The
recorded `results/` folder is never touched. The `mat_qaoa` output in the
copy reproduces the recorded seed-42 run (7.78% feasible, best score 11),
except for the timing fields.
