# Limitations

Honest documentation of what this project does **not** show. A slower
quantum solution is still a meaningful research result — but only if its
limitations are stated plainly.

## 1. Problem simplifications

- **Tiny instance.** Four teams is an educational example, not a hard
  problem. Classical backtracking solves it in ~10 microseconds. Nothing
  here predicts behavior on professional-scale instances.
- **Single round-robin core + classical mirroring.** The quantum model
  decides only the 3-round single round-robin (18 variables). The
  double round-robin and all home/away decisions are produced by a fixed,
  deterministic classical post-processing step (alphabetical home teams in
  rounds 1–3, mirrored in rounds 4–6). The qubits never choose venues.
- **Unbalanced home/away patterns.** Neither the classical nor the quantum
  pipeline enforces home/away streak fairness ("breaks"); the validator
  checks only the round-robin structure. Because of the alphabetical
  convention, team A plays HHHAAA and team D plays AAAHHH (H = home,
  A = away, rounds 1–6) in **all six** mirrored QAOA/QUBO schedules. The
  classical backtracking schedule saved in `results/classical_result.json`
  has the same pattern (A: HHHAAA, D: AAAHHH; B: AHHHAA; C: HAAAHH).
  Real leagues treat runs of three home or away games as undesirable;
  these schedules are structurally valid but not fair in that sense.
- **QOBLIB constraints excluded.** Capacity (CA), break (BR), game (GA),
  fairness (FA), and separation (SE) constraints from the original research
  are entirely absent. This project does not reproduce the QOBLIB benchmark.
- **The full 4-team double round-robin was out of reach.** It needs 72
  binary variables = 72 qubits, requiring ~76 zettabytes for exact
  simulation. The 18-qubit model is a transparent downsizing, not a choice
  made to flatter either method.

## 2. QAOA limitations

- **Heuristic, no guarantees.** QAOA may return invalid schedules in most
  shots, and did: the best configuration (p=3) still produced valid
  schedules in under 1% of measurements.
- **Can fail completely.** One p=3 seed (55) and four of five p=1 seeds
  found no valid schedule at all in 4,000 final shots.
- **Fixed optimizer budget.** COBYLA was capped at 40 iterations for every
  depth for comparability. Every p=3 trial hit this cap, so deeper circuits
  may be under-optimized; p=3 might perform better (or differently) with a
  larger budget. Untested.
- **Depth is not guaranteed to help.** Our run showed improvement with
  depth *on average over 5 seeds*. Deeper circuits have more parameters and
  harder optimization landscapes, and can perform worse.
- **Penalty weights untuned.** A=B=1 was mathematically sufficient
  (verified exhaustively) but alternative weightings were not explored.

## 3. Simulator limitations

- **No hardware noise.** The Aer simulator is noiseless. The p=3 circuit
  has 324 two-qubit gates at depth 113 (basis: cx/rz/rx/h); on a real
  device, gate errors and decoherence would degrade results substantially.
  No hardware runs were performed; no noise model was applied.
- **Simulator timings are not hardware timings.** Measured runtimes include
  Python and Aer overheads and exclude real-device queue time, latency, and
  per-shot sampling costs. They cannot be extrapolated to QPU performance.

## 4. Experimental comparison limitations

- **Simulated annealing comparison budgets differ (Phase 2F).** 30 SA runs
  vs 5 stored QAOA trials per depth: the QAOA side of that comparison is
  preliminary. An SA "run" (~900 energy evaluations typically) and a QAOA
  "trial" (tens of thousands of shots plus an optimization loop) are not
  equal computational budgets. SA's TTS99 is a 99th-percentile single-run
  time (all 30 runs succeeded); QAOA's TTS99 values assume independent
  repeats with a success probability estimated from only 5 trials.
- **SA hyperparameters were not tuned.** One reasonable setting
  (T₀=3.0, cooling 0.9995, 50k max iterations) was chosen and measured;
  better or worse settings exist. Likewise QAOA's optimizer budget was
  fixed. Neither method was tuned to its best possible configuration.

- **Small sample sizes.** Five seeds per depth. The p=1 mean valid rate
  (0.075%) rests entirely on one lucky seed; standard deviations are of the
  same magnitude as the means (e.g., p=3: 0.295% ± 0.387%). Success counts
  like 4/5 carry wide binomial uncertainty. The depth trend (1/5 → 3/5 →
  4/5 successful trials) is suggestive, not statistically conclusive.
- **Random baseline is weakly informative on its own.** Zero valid samples
  in 20,000 random draws is unsurprising — the expected count was 0.458 and
  the probability of seeing zero was 63%. The meaningful comparison is
  QAOA's measured valid rates (up to 0.95%) against the exactly known
  random probability (0.0023%), a factor of 30–400 depending on seed/depth.
- **Different-kind comparison.** Backtracking is an exact algorithm with a
  100% success rate; QAOA is a stochastic sampler. "Time-to-valid-solution"
  (total time across trials divided by successful trials) is a fair summary
  but still compares fundamentally different processes.
- **No quantum speedup can be claimed, and none is.** Classical
  backtracking was ~6 orders of magnitude faster on this instance. We also
  did not measure IBM QPU time, so no hardware-time comparison of any kind
  is possible from this work.

## 5. Wrestling simulation limitations (Phases W1–W4)

- **Championship brackets only.** The projected totals (60 byes, 118
  contested matches for the seed-42 rosters) cover single-elimination
  championship brackets exclusively. Real tournaments typically add
  consolation/wrestle-back brackets, placement matches, and other
  competition-specific requirements, which can roughly double the match
  count. These are intentionally excluded from the prototype.
- **Synthetic placement.** Bracket positions are assigned deterministically
  in roster order for reproducibility — not official NFHS seeding or bye
  distribution.
- **No actual results.** No match winners, team scoring, or forfeits are
  simulated; byes are the only non-contested advancements, and later-round
  participants stay unknown placeholders.
- **Mat assignments and time slots exist, but are simulated (W3).** Every
  one of the 118 contested matches is assigned to one of 6 identical mats
  and a discrete, equal-length time slot. Real match durations (pins,
  overtime, injury time) are not modeled. The 1-slot minimum rest between
  a wrestler's consecutive matches is a modeling choice, **not** a
  verified competition-specific rest requirement. The greedy schedule
  reaches the 20-slot lower bound under this simplified model only.
- **Still excluded overall:** official seeding, consolation/wrestle-back
  brackets, real match durations, actual results, and verified
  competition-specific rest rules.
- **W4 is a classical feasibility study, not a quantum result.** The
  14-variable mat-selection QUBO was verified exhaustively and solved by
  classical brute force and greedy; no QAOA was run on it. In the chosen
  snapshot (slot 17) the greedy heuristic already finds the optimum, so
  the instance is easy and demonstrates the model rather than any need
  for a stronger solver. The "one match per weight class per slot" rule
  is used only in W4; the W3 validator does not enforce it.
- **Fictional data.** Sample weight-class labels and fictional schools;
  no real student or competition data.
