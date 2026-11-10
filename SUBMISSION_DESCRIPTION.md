# DeepStation Submission Description

**Project name:** Quantum Sports Scheduler: Classical Python vs. Quantum QAOA for Wrestling Tournaments

---

## Description (paste into DeepStation)

**The problem.** Large wrestling tournaments run many weight classes at once on a few
mats. Organizers have to run every match exactly once, keep bracket order, give
wrestlers rest between bouts, avoid double-booking mats, and finish as early as
possible. The number of possible schedules grows extremely fast, which makes this a
classic optimization problem. The idea came from our team's experience in sports
medicine at large wrestling tournaments.

**Why quantum?** Optimization problems like this can be written as a QUBO, a set of
yes/no decisions with a score. QUBO is the input format for quantum optimization
algorithms such as QAOA. We wanted to test honestly whether QAOA could help with a
real sports scheduling decision, and compare it fairly against classical methods.

**What we built.** We simulated a fictional tournament: 12 schools, 14 weight classes,
132 wrestlers, 118 matches and 6 mats. A classical greedy scheduler placed all 118
matches in **20 time slots, which equals the mathematical lower bound** (98.3% mat
use). An independent validator confirmed that every rule was followed. We then gave
QAOA a smaller real decision from that schedule: at time slot 17, choose 6 of 14
ready matches to maximize bracket progress. That is 14 variables, or 14 qubits. We
checked the QUBO against all 16,384 possible answers before running any quantum code
(1,289 feasible, exactly 1 optimal).

**Simulator results (Qiskit Aer, noiseless, 5 seeds per depth, 4,000 final shots).**
QAOA produced valid schedules more often than random guessing on average: **14.9%
feasible samples at p=1 and 18.7% at p=2, vs. 7.9% for random guessing.** It found
the optimal answer in 3 of 5 runs (p=1) and 2 of 5 runs (p=2). Results varied
widely by seed (about 6–28%), and p=2 was not significantly better than p=1. Every
feasible QAOA answer passed our independent validator. Classical greedy found the
optimum every time in about 10 microseconds. QAOA took 1–3 seconds per run on the
simulator. In an earlier 4-team league test (18 qubits), classical backtracking and
simulated annealing also solved every run, while QAOA succeeded in 1–4 of 5 runs.

**Real IBM quantum hardware.** We ran **our 14-qubit wrestling QAOA circuit on IBM's
ibm_fez processor**: one job of 4,000 shots (job dbppooc4148s739v0lsg, Open Plan). We
reused the saved simulator angles (p=1, seed 22), so nothing was optimized on the
hardware. Compiled for the chip, the circuit had 280 two-qubit gates and depth 356. We
checked that the compiled circuit gives the same ideal probabilities as our simulator
circuit. **Measured result: 13.2% of hardware samples were valid schedules (95% CI
12.2–14.3%), vs. 7.9% for random guessing** (p ≈ 7×10⁻³¹). All 423 distinct valid
hardware answers passed our independent validator. Noise had a big effect: the same
angles give 23.6% on a perfect quantum computer and 23.5% in our simulator run, and a
pre-run noise-model prediction (FakeFez, not a measurement) was 17.4%. The single best
answer did not appear on hardware; the best hardware answer scored 11 of 12. Before
that, a 2-qubit Bell-state test on ibm_fez (job dbovmec4148s739tmr50, 95/100
correlated outcomes) confirmed our hardware workflow.

**Conclusion and limitations.** Classical Python was faster and more reliable on
every problem we tested. **We do not claim a quantum advantage.** The hardware run
shows that our scheduling algorithm works on a real quantum computer and beats random
guessing, but noise cut its success rate by about 44% compared with the simulator. It
was one job with one set of angles. The tournament is fictional and simplified, the
instance is easy for greedy, and we ran only five simulator seeds per depth. Next
steps: harder instances where greedy is not optimal, more seeds and better QAOA
objectives, repeated hardware runs, and error mitigation. Our main lesson:
**check the answer, not the algorithm.** 228 automated tests, an exhaustive QUBO check
and an independent validator kept our results honest.

**Code:** https://github.com/bassette143/quantum-sports-scheduler
(see `submission_notebook.ipynb` for a step-by-step walkthrough with saved outputs)

---

## Evidence files for the judges

- Hardware result: `results/hardware/hardware_result_ibm_fez_dbppooc4148s739v0lsg.json`
  (job ID, raw counts, validator check, comparison numbers)
- Pre-run noise prediction: `results/hardware/preflight_fakefez_2026-11-10_172347.json`
- Script used: `hardware/qaoa_hardware.py`
- Walkthrough: `submission_notebook.ipynb`, section 9c
