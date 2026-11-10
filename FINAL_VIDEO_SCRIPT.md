# Final Video Script (5 minutes max)

Three speakers, about 700 spoken words in total (about 670 without the *(optional)*
lines). At a relaxed pace of about 145 words per minute, that is roughly 4 minutes 40
to 50 seconds. **Do a timed practice run.** If you go over, cut the lines marked
*(optional)*.

Record with your own voices. *[Square brackets]* tell you what to show on screen.
Don't read them out. Slide numbers refer to
`presentation/Quantum_Sports_Scheduler_Hackathon_2026_v3.pptx`.

Every number here comes from `RESULTS.md` or `results/` (hardware numbers come from
`results/hardware/hardware_result_ibm_fez_dbppooc4148s739v0lsg.json`). If you change a
number, check it there first.

---

## Speaker 1: Problem and Purpose (about 1 minute, ~150 words)

*[Slide 1: title]*

Hi, we're the Quantum Sports Scheduler team, and this is our project for the IBM
Qiskit Fall Fest.

*[Slide 2: why this project matters]*

This idea started with real experience. One of our team members worked in sports
medicine at large wrestling tournaments. They saw how hard it is to organize
hundreds of athletes across several mats at the same time.

*[Slide 3: what we built]*

Here's the problem. Every match has to happen exactly once, and in bracket order.
Wrestlers need rest between matches. You can't put two matches on the same mat at
the same time. And you want to finish as early as possible.

The number of possible schedules explodes very quickly. That makes this an
optimization problem, the kind of problem quantum computers are being studied for.

So our question was simple: can a quantum algorithm help schedule a tournament, and
how does it compare with regular Python?

---

## Speaker 2: Classical and Quantum Methods (about 2 minutes, ~290 words)

*[Slide 5: wrestling schedule, 20 rounds = minimum]*

We started with classical Python. We built a fictional tournament: 12 schools, 14
weight classes and 118 matches on 6 mats. Our greedy algorithm fills each time slot
with matches that are ready to go.

It scheduled all 118 matches in 20 time slots. With 118 matches and 6 mats, you need
at least 20 slots, so this schedule is already optimal. A separate validator program
checked every rule and found no mistakes.

*[Slide 6: how the quantum part works]*

Since the full schedule was already optimal, we gave the quantum computer a smaller
real decision. At time slot 17, there are 14 matches ready to start. Pick the best 6,
one per mat, with only one match per weight class.

To give this to a quantum computer, we wrote it as a QUBO. That's just a list of
yes-or-no choices with a score. Each match is one yes-or-no choice, so 14 matches
means 14 qubits. Breaking a rule adds a big penalty, and making bracket progress
earns points.

Before running any quantum code, we checked our formula against all 16,384 possible
answers. Exactly one answer was the best.

*[Stay on slide 6: point to the five steps]*

Then we used QAOA, the Quantum Approximate Optimization Algorithm. Think of it as a
team. The quantum circuit makes good answers more likely. A regular computer tunes
the circuit's settings and tries again. At the end, we measure the qubits thousands
of times and check every answer.

*[Optional: show notebook section 5 or the dashboard]*

We ran this with Qiskit on IBM's Aer simulator, which is a regular computer imitating
a perfect quantum computer. We tested one and two QAOA layers, with five different
random seeds each, and 4,000 measurements per run.

---

## Speaker 3: Results and Conclusions (about 2 minutes, ~280 words)

*[Slide 7 "valid answers vs. guessing" row, or the notebook chart in section 6b]*

So, what happened?

If you guess randomly, about 8% of answers follow all the rules. QAOA did better on
average: about 15% with one layer and about 19% with two layers. But results changed
a lot from run to run, from about 6% up to 28%. *(optional: QAOA found the single best
answer in 3 of 5 runs with one layer and 2 of 5 runs with two layers.)* Every valid
answer it found passed our validator.

*[Slide 7: regular Python vs. quantum]*

Now the honest part. Classical greedy found the best answer every single time, in
about 10 microseconds. QAOA on the simulator took one to three seconds. So in our
tests, regular Python was faster and more reliable. **We did not find a quantum
advantage, and we're not claiming one.**

*[Slide 8: real IBM computer]*

Then we took the next step. We ran our actual scheduling circuit on IBM's ibm_fez
quantum computer: one job, 4,000 measurements, using the settings we had already
found on the simulator.

On the real chip, 13.2% of the answers were valid schedules. That's well above random
guessing at 7.9%, and every valid answer passed our checker.

But noise made a big difference. The same circuit gave 23.5% on the simulator. On the
chip it needed 280 two-qubit gates, and every gate adds a little error. The single
best answer didn't show up on hardware. That's why testing on real hardware matters:
simulators are perfect, and real chips are not.

*[Slide 11: what we learned]*

What did we learn? Check the answer, not the algorithm. Always compare against a
strong classical method, and never trust one lucky run. *(optional: We used five
seeds, an exhaustive check, and 228 automated tests.)*

Next, we want to try harder tournaments where simple methods struggle, repeat our
hardware runs, and try techniques that reduce the effect of noise.

Thanks for watching!

---

## Recording checklist

- [ ] Timed practice run is under 5:00 (aim for 4:40 to leave margin)
- [ ] Real voices. If anyone uses an AI voice, it must be a realistic one such as ElevenLabs (organizer rule)
- [ ] Simulator results are always called "simulator". Only the 13.2% ibm_fez result (and the Bell test) are "hardware"
- [ ] Export as MP4 (DeepStation upload limit is 2 GB)
