# Wrestling QAOA: Hardware Optimization and Validation

**Project:** Quantum Sports Scheduler
**Researcher:** Griselda Bassette
**Event:** IBM Qiskit Fall Fest 2026
**Experiment date:** November 9, 2026
**Target processor:** IBM ibm_fez

## 1. Research Objective

Investigate whether our existing 14-qubit wrestling
QAOA circuit can be prepared efficiently for real
IBM quantum hardware without changing its intended
measurement probabilities.

All tests in this report were local.
No additional IBM hardware jobs were submitted.

## 2. Existing QAOA Simulator Results

| Metric | QAOA p=1 | QAOA p=2 |
|---|---:|---:|
| Logical qubits | 14 | 14 |
| Circuit depth | 79 | 123 |
| CX gates | 182 | 364 |
| Feasible samples | 7.775% | 20.8% |
| Optimal samples | 0% | 0.075% |

The noiseless p=2 experiment produced more feasible
schedules but required more circuit operations.

These results do not establish quantum advantage.

## 3. IBM Hardware Transpilation

QAOA p=1:

| Metric | Level 1 | Level 2 | Level 3 |
|---|---:|---:|---:|
| Circuit depth | 495 | 442 | 440 |
| CZ gates | 440 | 320 | 330 |
| SX gates | 814 | 663 | 670 |
| RZ gates | 884 | 531 | 569 |
| Measurements | 14 | 14 | 14 |

Level 2 reduced CZ gates by approximately 27.3%
and circuit depth by approximately 10.7%
relative to Level 1.

Level 3 achieved slightly lower depth, but Level 2
required fewer CZ, SX, and RZ gates.

Level 2 is our provisional optimization choice.
Actual hardware error rates have not been compared.

## 4. QAOA p=2 Hardware Preparation

Optimization Level 1:

Hardware depth: 907
CZ gates: 895
SX gates: 1653
RZ gates: 1733
Measurements: 14

The p=2 hardware circuit was substantially more
complex than p=1.

## 5. Physical Qubit Investigation

Local FakeFez transpilation at Level 2:

Logical qubits: 14
Hardware circuit wires: 156
Active physical qubits: 14
Idle qubits: 142
Local FakeFez circuit depth: 445

After removing idle wires from an in-memory copy:

Compact circuit qubits: 14
Compact circuit depth: 445
Measurements: 14
Adjustable parameters: 2

Removing idle wires reduced simulation memory
requirements but did not reduce circuit depth.

FakeFez is a local hardware snapshot. Its results
may differ from live IBM hardware.

## 6. Circuit Equivalence Tests

The original QAOA p=1 circuit was compared with
the compact, Level 2 hardware-transpiled circuit.

Ideal measurement probabilities were mapped to
the corresponding classical bit order.

| Parameters | Total Variation Distance | Result |
|---|---:|---|
| 0.17, 0.31 | 2.05318e-14 | PASS |
| 0.10, 0.20 | 1.92040e-14 | PASS |
| 0.35, 0.45 | 2.11066e-14 | PASS |
| 0.70, 0.90 | 2.01796e-14 | PASS |

Tolerance: absolute probability difference <= 1e-7
for each measurement outcome.

All four tests passed.

The tiny differences are consistent with
floating-point numerical rounding.

## 7. Scientific Limitations

- Four parameter settings do not prove equivalence
  for every possible QAOA parameter value.
- Ideal statevector simulation excludes hardware noise.
- The compact circuit was created for local testing,
  not submitted to IBM hardware.
- Gate count alone cannot establish circuit fidelity.
- No full wrestling QAOA hardware job was submitted.
- No quantum speedup or quantum advantage was shown.
- Real hardware accuracy and runtime remain unknown.

## 8. Conclusions

Qiskit optimization substantially reduced our
wrestling QAOA p=1 hardware gate count.

The optimized circuit produced nearly identical
ideal measurement probabilities across four
tested parameter settings.

However, hundreds of two-qubit hardware operations
remain, making noise a significant concern.

## 9. Recommended Next Experiment

1. Preserve existing experiments and source files.
2. Investigate a memory-safe local noisy simulation.
3. Compare predicted feasible and optimal sample rates.
4. Review hardware calibration and resource usage.
5. Decide whether a smaller QAOA hardware demonstration
   is more appropriate than the full wrestling circuit.

No existing project results were replaced.
