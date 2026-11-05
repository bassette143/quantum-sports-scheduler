# Use Case: Sports Tournament Scheduling

## Why scheduling is a meaningful optimization problem

Tournament scheduling looks simple but is a classic **combinatorial
optimization problem**: the number of possible schedules explodes as leagues
grow, while the rules (constraints) eliminate almost all of them. Our tiny
4-team instance already has 262,144 ways to fill the schedule grid, of which
only 6 are valid single round-robins — about 0.002%. Professional instances
(18–20 teams, venue restrictions, TV windows, fairness rules) are so hard
that leagues hire specialist firms and research groups to solve them;
variants of round-robin scheduling are NP-hard in general, which is exactly
why the problem class appears in the QOBLIB quantum optimization benchmark.

A bad schedule has real costs: wasted stadium capacity, unfair sequences of
away games, broadcast conflicts, and extra travel.

## Real-world stakeholders

| Stakeholder | What they need from a schedule |
|---|---|
| **League operators** | All matchups played, rules satisfied, produced on time |
| **Teams** | Fairness: balanced home/away sequences, no brutal travel runs |
| **Players** | Adequate rest between games (break constraints) |
| **Broadcasters** | Marquee games spread across TV windows |
| **Venues & cities** | No clashes with concerts, other tenants, or public events |
| **Fans** | Predictable home games, meaningful season arcs |
| **Betting/integrity bodies** | Schedules that do not advantage particular teams |

## The real problem vs. our experiment

The full professional problem (as in QOBLIB) includes capacity (CA), break
(BR), game (GA), fairness (FA) and separation (SE) constraints. Our
experiment keeps only the structural core — every matchup played exactly
once per half, every team playing exactly once per round — on 4 teams, which
is the smallest meaningful instance that still has the "almost every
possibility is wrong" character of the real problem.

## Why try quantum computing on it?

Scheduling constraints translate naturally into QUBO energy penalties, the
input format for quantum optimizers such as QAOA. Studying a small instance
end-to-end — formulation, verification, measurement, honest comparison with
classical methods — is exactly how the field evaluates whether future, larger
quantum devices could one day help with the professional-scale problem.
Today, as our measurements show, classical algorithms remain vastly superior
on instances of this size ([RESULTS.md](./RESULTS.md)).
