# Official RobinX benchmark data: source and license

These files are unmodified copies of official benchmark data from the
**Quantum Optimization Benchmarking Library (QOBLIB)**, problem class
05-sports (Sports Tournament Scheduling). The instances come from the ITC2021
sports timetabling competition (Van Bulck et al.).

| Local file | Upstream path (QOBLIB) |
|---|---|
| `Addition_000_Small.xml.gz` | `05-sports/instances/Small/Addition_000_Small.xml.gz` |
| `Addition_000_Small.solution.xml.gz` | `05-sports/solutions/Small/Addition_000_Small.xml.gz` (renamed locally to avoid a name clash with the instance) |
| `Addition_000_Small.opt.sol` | `05-sports/solutions/Small/Addition_000_Small.opt.sol` |

- Repository: https://git.zib.de/qopt/qoblib-quantum-optimization-benchmarking-library
- Pinned commit: `ee1046010d3369d160bf0042f51051fbe823c1d0` (2026-07-08)
- Downloaded: 2026-11-10. Git blob IDs were checked against that commit, and all three match byte for byte.

SHA-256 checksums (also checked by `tests/test_robinx.py`):

```
d118db22bb0bf98c308e9137004775d3de80c4ae5742677a0d759ffe93392870  Addition_000_Small.xml.gz
920b9b76015cb371da0bd2e2a57b5963f336cd8f0984f99093dfcc94fbd65f96  Addition_000_Small.solution.xml.gz
ea1fd7b954ffe94fb800cc92ea990be09597562462c85a316eead96d76532abf  Addition_000_Small.opt.sol
```

## License and attribution

QOBLIB distributes its data under the **Creative Commons Attribution 4.0
International (CC BY 4.0)** license (`LICENSE.data` in the QOBLIB repository).
Redistribution is permitted with attribution. These files have not been modified.

Attribution: QOBLIB, Quantum Optimization Benchmarking Library (Zuse Institute
Berlin and contributors), 05-sports. Instances from D. Van Bulck and
D. Goossens, "The International Timetabling Competition on Sports Timetabling
(ITC2021)", *European Journal of Operational Research*, 2023. Solution files
contributed to QOBLIB by Team MODAL (koch@zib.de).

## Notes

- The solution XML's `InstanceName` field reads `Add` because QOBLIB's
  `sol2itc.py` converter truncates names. The instance–solution pairing rests on
  the matching upstream file paths and the checksums above.
- Both solution files encode the same 56 games. In the `.opt.sol` file,
  variable `x#h#a#s = 1` means team `h` hosts team `a` in slot `s`.
