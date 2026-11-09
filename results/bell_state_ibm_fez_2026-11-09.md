# IBM Quantum Bell-State Hardware Experiment

## Project
Quantum Sports Scheduler
IBM Qiskit Fall Fest 2026

## Experiment Information
Date: November 9, 2026
Processor: ibm_fez
Physical qubits available: 156
Circuit qubits: 2
Circuit type: Bell state
IBM plan: Open
Job ID: dbovmec4148s739tmr50
Job status: DONE
Hardware shots: 100

## Circuit
1. Initialize two qubits to |00>.
2. Apply a Hadamard gate to qubit 0.
3. Apply a controlled-NOT gate from qubit 0 to qubit 1.
4. Measure both qubits.

Original circuit depth: 3
Transpiled hardware circuit depth: 8
ISA validation: PASS

## Simulator Results
Shots: 1000

00: 498
01: 0
10: 0
11: 502

## Real IBM Hardware Results
Shots: 100

00: 49
01: 5
10: 0
11: 46

## Analysis
The ideal Bell-state circuit produces 00 and 11
with equal theoretical probabilities.

The simulator produced 100% correlated outcomes.

The IBM quantum processor produced 95 correlated
outcomes out of 100 measurements.

Observed correlation rate: 95%
Observed unexpected-outcome rate: 5%

The hardware results are consistent with the
presence of quantum hardware noise, gate errors,
or measurement errors.

These results do not identify the exact source
of the unexpected outcomes.

## Scientific Limitations
- The simulator and hardware used different shot counts.
- The hardware experiment used only 100 shots.
- The results do not prove quantum advantage.
- Measurement correlations alone do not prove entanglement.
- The experiment does not establish Bell-state fidelity.
- The Bell-state circuit is not the full QAOA scheduler.

## Conclusion
We successfully executed a two-qubit Bell-state
experiment on real IBM quantum hardware.

This validates our basic hardware submission and
result-retrieval workflow.

Next, we will investigate the feasibility of
running our sports scheduling QAOA experiments
on real quantum hardware.
