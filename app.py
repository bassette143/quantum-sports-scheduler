"""Read-only Streamlit dashboard for the Quantum Sports Scheduler.

Displays saved results from ``results/`` only. It never runs QAOA, generates
schedules, or contacts IBM Quantum. Run with:

    streamlit run app.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st

RESULTS = Path(__file__).resolve().parent / "results"
ROOT = Path(__file__).resolve().parent

st.set_page_config(page_title="Quantum Sports Scheduler", page_icon="🤼", layout="wide")


# ---------------------------------------------------------------------------
# Loading helpers (read-only, with warnings instead of crashes)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _read_json(path: str):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


@st.cache_data(show_spinner=False)
def _read_text(path: str):
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


def load_json(name: str):
    path = RESULTS / name
    if not path.exists():
        st.warning(f"Missing results file: `results/{name}`. This part cannot be shown.")
        return None
    try:
        return _read_json(str(path))
    except (OSError, json.JSONDecodeError) as exc:
        st.warning(f"Could not read `results/{name}`: {exc}")
        return None


def load_text(path: Path):
    if not path.exists():
        st.warning(f"Missing file: `{path.relative_to(ROOT)}`.")
        return None
    try:
        return _read_text(str(path))
    except OSError as exc:
        st.warning(f"Could not read `{path.relative_to(ROOT)}`: {exc}")
        return None


_MISSING = object()


def get(data, *keys, label: str | None = None, warn: bool = True):
    """Safely walk nested dicts/lists. Returns None and warns if absent."""
    cur = data
    for key in keys:
        try:
            cur = cur[key]
        except (KeyError, IndexError, TypeError):
            cur = _MISSING
            break
    if cur is _MISSING:
        if warn:
            st.warning(f"Field unavailable in saved results: `{label or '.'.join(map(str, keys))}`")
        return None
    return cur


def fmt_time(seconds) -> str:
    if seconds is None:
        return "n/a"
    s = float(seconds)
    if s < 1e-3:
        return f"{s * 1e6:.1f} µs"
    if s < 1:
        return f"{s * 1e3:.1f} ms"
    return f"{s:.2f} s"


def fmt_pct(value, digits: int = 3) -> str:
    return "n/a" if value is None else f"{float(value):.{digits}g}%"


def show_table(rows: list[dict]):
    if rows:
        df = pd.DataFrame(rows)
        # Columns mixing numbers and text (e.g. "—") are shown as text for Arrow.
        for col in df.columns:
            if df[col].dtype == object:
                df[col] = df[col].map(lambda v: "n/a" if v is None else str(v))
        st.dataframe(df, hide_index=True, width="stretch")


NO_ADVANTAGE = (
    "**Research finding:** Our classical solvers outperformed QAOA on the tested problems. "
    "The quantum experiments demonstrate a working QUBO/QAOA implementation and reveal "
    "current limitations; no quantum advantage was established. QAOA results come from a "
    "noiseless local simulator, and simulator runtimes are not quantum-hardware runtimes."
)


# ---------------------------------------------------------------------------
# Header + navigation
# ---------------------------------------------------------------------------

st.title("Quantum Sports Scheduler")
st.caption(
    "IBM Qiskit Fall Fest 2026 · Read-only dashboard of saved experimental results. "
    "Nothing on this page reruns QAOA, generates schedules, or submits IBM Quantum jobs. "
    "All schools and wrestlers are fictional."
)
st.info(NO_ADVANTAGE, icon="🔬")

section = st.sidebar.radio(
    "Section",
    [
        "1 · Wrestling Schedule",
        "2 · Classical vs. Quantum",
        "3 · Charts",
        "4 · IBM Quantum Hardware",
    ],
)
st.sidebar.markdown("---")
st.sidebar.caption(f"Data folder: `{RESULTS.relative_to(ROOT)}/`")
st.sidebar.caption("See `LIMITATIONS.md` for the full list of caveats.")


# ---------------------------------------------------------------------------
# Section 1: Wrestling schedule
# ---------------------------------------------------------------------------

MATCH_ID = re.compile(r"^W(\d+)-R(\d+)-S(\d+)$")


def bracket_lookup(brackets_json) -> dict:
    """Map match id -> (participant A, participant B) from saved brackets."""
    lookup = {}
    brackets = get(brackets_json, "brackets", warn=False) or {}
    for bracket in brackets.values():
        for rnd in bracket.get("rounds", []):
            for slot in rnd.get("slots", []):
                people = slot.get("wrestlers") or slot.get("participants") or [None, None]
                lookup[slot.get("id")] = tuple(people) + (None,) * (2 - len(people))
    return lookup


def render_schedule():
    st.header("1 · Wrestling Schedule")
    st.write(
        "Simulated single-elimination **championship brackets** for 12 fictional schools "
        "across 14 weight classes, assigned to 6 mats and equal-length time slots by a "
        "**classical** deterministic greedy scheduler. No quantum solver produced this schedule."
    )

    sched = load_json("wrestling_mat_schedule.json")
    if sched is None:
        return
    brackets = load_json("wrestling_brackets.json")
    people = bracket_lookup(brackets) if brackets else {}
    if brackets is None:
        st.info("Wrestler names unavailable; showing match IDs only.")

    stats = get(sched, "statistics") or {}
    settings = get(sched, "settings") or {}
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Matches scheduled", stats.get("n_matches_scheduled", "n/a"))
    c2.metric("Mats", stats.get("n_mats", settings.get("n_mats", "n/a")))
    c3.metric(
        "Time slots used",
        stats.get("makespan_slots", "n/a"),
        help=f"Theoretical lower bound: {stats.get('theoretical_lower_bound_slots', 'n/a')}",
    )
    util = stats.get("mat_utilization_percent")
    c4.metric("Mat utilization", f"{util}%" if util is not None else "n/a")

    valid = sched.get("is_valid")
    if valid is True:
        st.success(
            f"Saved validator result: valid, {len(sched.get('violations', []))} violations. "
            f"Algorithm: {settings.get('algorithm', 'n/a')}; "
            f"rest between a wrestler's matches: {settings.get('rest_slots', 'n/a')} slot(s)."
        )
    elif valid is False:
        st.error(f"Saved validator reported violations: {sched.get('violations')}")
    else:
        st.warning("Validator result `is_valid` not found in saved schedule.")

    assignments = get(sched, "assignments")
    if not assignments:
        return

    rows = []
    for mid, a in assignments.items():
        m = MATCH_ID.match(mid)
        weight, rnd = (int(m.group(1)), int(m.group(2))) if m else (None, None)
        pa, pb = people.get(mid, (None, None))
        bout = f"{pa or 'TBD'} vs {pb or 'TBD'}" if mid in people else "—"
        rows.append(
            {
                "Slot": a.get("slot"),
                "Mat": a.get("mat"),
                "Match ID": mid,
                "Weight (lb)": weight,
                "Round": rnd,
                "Bout": bout,
            }
        )
    df = pd.DataFrame(rows).sort_values(["Slot", "Mat"])

    st.caption(
        "\"TBD\" = later-round participant decided by an earlier bout. No match winners are "
        "simulated, so later rounds stay placeholders."
    )

    view = st.radio("View", ["Grid (slot × mat)", "List with filters"], horizontal=True)
    if view.startswith("Grid"):
        grid = df.assign(Cell=df["Match ID"] + "  " + df["Bout"]).pivot_table(
            index="Slot", columns="Mat", values="Cell", aggfunc="first"
        )
        grid.columns = [f"Mat {c}" for c in grid.columns]
        st.dataframe(grid.fillna("(empty)"), width="stretch", height=740)
    else:
        f1, f2 = st.columns(2)
        slots = sorted(df["Slot"].dropna().unique())
        weights = sorted(df["Weight (lb)"].dropna().unique())
        pick_slots = f1.multiselect("Time slots", slots)
        pick_weights = f2.multiselect("Weight classes", weights)
        out = df
        if pick_slots:
            out = out[out["Slot"].isin(pick_slots)]
        if pick_weights:
            out = out[out["Weight (lb)"].isin(pick_weights)]
        st.dataframe(out, hide_index=True, width="stretch")

    with st.expander("What this schedule does not model"):
        st.markdown(
            "- Championship brackets only: no consolation/wrestle-back or placement matches.\n"
            "- Synthetic, unseeded bracket placement: not official NFHS seeding.\n"
            "- Equal-length slots: real match durations are not modeled.\n"
            "- The 1-slot rest rule is a modeling choice, not a verified competition rule."
        )


# ---------------------------------------------------------------------------
# Section 2: Classical vs quantum
# ---------------------------------------------------------------------------

def render_round_robin():
    st.subheader("Experiment A: 4-team round-robin (18 binary variables / 18 qubits)")
    st.caption(
        "A small educational sports league problem. Every solver below was run on the "
        "**same verified 18-variable QUBO**. This is the only problem where simulated "
        "annealing was benchmarked."
    )
    sa = load_json("sa_benchmark_results.json")
    bench = load_json("benchmark_results.json")
    if sa is None:
        return

    rows = []
    cb = get(sa, "classical_baseline")
    if cb:
        rows.append(
            {
                "Solver": "Classical backtracking",
                "Runs on": "Classical CPU",
                "Runs": cb.get("repeats"),
                "Successful runs": "100%" if cb.get("all_runs_found_valid_zero_energy_solution") else "n/a",
                "Median time / run": fmt_time(cb.get("median_time_s")),
                "Expected time to a valid schedule": fmt_time(cb.get("median_time_s")),
            }
        )
    ss = get(sa, "sa_summary")
    if ss:
        rows.append(
            {
                "Solver": "Simulated annealing",
                "Runs on": "Classical CPU",
                "Runs": ss.get("n_runs"),
                "Successful runs": fmt_pct(ss.get("success_percent")),
                "Median time / run": fmt_time(ss.get("median_time_s")),
                "Expected time to a valid schedule": fmt_time(ss.get("expected_tts_including_failures_s")),
            }
        )
    for q in get(sa, "qaoa_summaries_from_phase2c_not_rerun") or []:
        depth = q.get("method", "").replace("qaoa_p", "")
        rows.append(
            {
                "Solver": f"QAOA p={depth}",
                "Runs on": "Noiseless Aer simulator",
                "Runs": q.get("n_runs"),
                "Successful runs": fmt_pct(q.get("success_percent")),
                "Median time / run": fmt_time(q.get("median_time_s")),
                "Expected time to a valid schedule": fmt_time(q.get("expected_tts_including_failures_s")),
            }
        )
    show_table(rows)
    st.caption(
        "\"Successful run\" = at least one valid schedule found. QAOA rows use only 5 trials "
        "each and are preliminary. An SA run and a QAOA trial are not equal computational effort."
    )

    if bench:
        summaries = get(bench, "summaries") or []
        qrows = [
            {
                "QAOA depth": f"p={s.get('depth')}",
                "Mean valid samples per shot": fmt_pct(s.get("mean_valid_percent")),
                "Std. dev.": fmt_pct(s.get("stdev_valid_percent")),
                "Circuit depth": s.get("circuit_depth"),
                "Two-qubit gates": s.get("two_qubit_gates"),
            }
            for s in summaries
        ]
        if qrows:
            st.markdown("**QAOA shot-level quality (4,000 final shots per trial, 5 seeds)**")
            show_table(qrows)

    with st.expander("Saved fairness notes for this comparison"):
        for note in get(sa, "fairness_notes", warn=False) or []:
            st.markdown(f"- {note}")
        if bench:
            for note in get(bench, "limitations", warn=False) or []:
                st.markdown(f"- {note}")


def render_wrestling_snapshot():
    st.subheader("Experiment B: wrestling 14-qubit QAOA snapshot")
    st.info(
        "**This is not the full tournament.** The QAOA experiment solves one small decision "
        "taken from the wrestling schedule: at a single time slot, choose 6 of 14 candidate "
        "matches to maximize bracket progression (with at most one match per weight class). "
        "That is 14 binary variables → 14 qubits. The full 118-match tournament would need far "
        "more qubits and was scheduled only classically.",
        icon="🔎",
    )

    w5 = load_json("wrestling_qaoa_result.json")
    if w5 is None:
        return
    p2 = load_json("wrestling_qaoa_p2_result.json")
    sweep = load_json("wrestling_qaoa_sweep_results.json")

    inst = get(w5, "instance") or {}
    c1, c2, c3 = st.columns(3)
    c1.metric("Snapshot time slot", inst.get("snapshot_slot", "n/a"))
    c2.metric("Candidate matches (qubits)", len(inst.get("pool", [])) or "n/a")
    c3.metric("Matches to select (k)", inst.get("k", "n/a"))

    cr = get(w5, "classical_reference") or {}
    ur = get(w5, "uniform_random_exact") or {}
    rows = [
        {
            "Method": "Classical greedy",
            "Runs on": "Classical CPU",
            "Best score (optimum = 12)": cr.get("greedy_score"),
            "Feasible samples": "always",
            "Optimal samples": "always",
            "Time": fmt_time(cr.get("greedy_median_time_s")) + " (median)",
        },
        {
            "Method": "Classical brute force (exact)",
            "Runs on": "Classical CPU",
            "Best score (optimum = 12)": cr.get("brute_force_score"),
            "Feasible samples": "always",
            "Optimal samples": "always",
            "Time": fmt_time(cr.get("brute_force_median_time_s")) + " (median)",
        },
        {
            "Method": "Uniform random guessing (exact probability)",
            "Runs on": "Calculated",
            "Best score (optimum = 12)": "—",
            "Feasible samples": fmt_pct(ur.get("feasible_percent")),
            "Optimal samples": fmt_pct(ur.get("optimal_percent")),
            "Time": "—",
        },
    ]
    for label, data in (("QAOA p=1, seed 42", w5), ("QAOA p=2, seed 42", p2)):
        main = get(data, "main", warn=False) if data else None
        if not main:
            continue
        an = main.get("analysis", {})
        rows.append(
            {
                "Method": label,
                "Runs on": "Noiseless Aer simulator",
                "Best score (optimum = 12)": an.get("best_feasible_score"),
                "Feasible samples": fmt_pct(an.get("feasible_percent")),
                "Optimal samples": fmt_pct(an.get("optimal_percent")),
                "Time": fmt_time(main.get("timings_seconds", {}).get("quantum_pipeline_total")),
            }
        )
    show_table(rows)
    st.caption(
        "Simulated annealing was **not** run on this wrestling instance, so it is not listed here. "
        "Single-seed QAOA rows are exploratory."
    )

    if sweep:
        srows = []
        for s in get(sweep, "summaries") or []:
            fp, op, rt = (s.get(k, {}) for k in ("feasible_percent", "optimal_percent", "runtime_s"))
            srows.append(
                {
                    "QAOA depth": f"p={s.get('depth')}",
                    "Seeds": s.get("n"),
                    "Mean feasible samples": fmt_pct(fp.get("mean")),
                    "Feasible range": f"{fmt_pct(fp.get('min'))} – {fmt_pct(fp.get('max'))}",
                    "Mean optimal samples": fmt_pct(op.get("mean")),
                    "Runs finding optimum": f"{s.get('runs_finding_optimum')}/{s.get('n')}",
                    "Mean runtime": fmt_time(rt.get("mean")),
                    "Circuit depth": s.get("circuit_depth"),
                    "Two-qubit gates": s.get("two_qubit_gates"),
                }
            )
        if srows:
            st.markdown("**Reproducibility sweep (5 seeds per depth)**")
            show_table(srows)
            mw = get(sweep, "analysis", "mann_whitney_feasible_p2_vs_p1", warn=False) or {}
            if mw.get("p_value_two_sided_exact") is not None:
                st.caption(
                    f"p=2 vs p=1 feasible rate: Mann-Whitney p = {mw['p_value_two_sided_exact']:.2f} "
                    "(not statistically significant). A uniform random sampler has about a 21.7% "
                    "chance of hitting the single optimum at least once in 4,000 shots, so "
                    "\"found the optimum\" is weak evidence."
                )

    with st.expander("The 14 candidate matches in the snapshot"):
        pool, weights, scores = inst.get("pool", []), inst.get("weights", []), inst.get("scores", [])
        if pool and len(pool) == len(weights) == len(scores):
            show_table(
                [
                    {"Qubit": i, "Match ID": m, "Weight (lb)": w, "Progression score": s}
                    for i, (m, w, s) in enumerate(zip(pool, weights, scores))
                ]
            )
        else:
            st.warning("Snapshot pool details are unavailable or inconsistent.")


def render_full_tournament():
    st.subheader("Full wrestling tournament (118 contested matches)")
    sched = load_json("wrestling_mat_schedule.json")
    if sched is None:
        return
    stats = get(sched, "statistics") or {}
    show_table(
        [
            {
                "Method": "Classical greedy list scheduling",
                "Runs on": "Classical CPU",
                "Matches": stats.get("n_matches_scheduled"),
                "Slots used": stats.get("makespan_slots"),
                "Lower bound": stats.get("theoretical_lower_bound_slots"),
                "Valid": sched.get("is_valid"),
                "Time": fmt_time(sched.get("scheduling_time_seconds")),
            }
        ]
    )
    st.warning(
        "No quantum or simulated-annealing solver was run on the full tournament. The greedy "
        "schedule already reaches the lower bound under this simplified model."
    )


def render_comparison():
    st.header("2 · Classical vs. Quantum")
    st.write(
        "Results come from **three different problems of different sizes**. They are shown "
        "separately and should not be compared across tabs as if they were the same experiment."
    )
    t1, t2, t3 = st.tabs(
        [
            "A · 4-team round-robin (18 qubits)",
            "B · Wrestling snapshot (14 qubits)",
            "C · Full tournament (classical only)",
        ]
    )
    with t1:
        render_round_robin()
    with t2:
        render_wrestling_snapshot()
    with t3:
        render_full_tournament()


# ---------------------------------------------------------------------------
# Section 3: Charts
# ---------------------------------------------------------------------------

def render_charts():
    st.header("3 · Charts")
    st.info(
        "Both saved charts come from **Experiment A (4-team round-robin, 18 qubits)**, "
        "not from the wrestling problem. QAOA was run on a noiseless simulator, not quantum hardware.",
        icon="📊",
    )
    charts = [
        (
            "solver_comparison_charts.png",
            "Backtracking, simulated annealing and QAOA p=1–3 on the same 18-variable QUBO. "
            "QAOA used only 5 trials per depth, so these results are preliminary. Note the log time axis.",
        ),
        (
            "benchmark_charts.png",
            "QAOA depth sweep: valid-sample rate, runtime vs. classical backtracking, circuit "
            "size, and trials with at least one valid schedule (5 seeds per depth).",
        ),
    ]
    for name, caption in charts:
        path = RESULTS / name
        if path.exists():
            st.image(str(path), caption=caption, width="stretch")
        else:
            st.warning(f"Chart not found: `results/{name}`.")


# ---------------------------------------------------------------------------
# Section 4: IBM Quantum hardware
# ---------------------------------------------------------------------------

def md_section(text: str, heading: str) -> str | None:
    m = re.search(rf"^##\s+{re.escape(heading)}\s*$(.*?)(?=^##\s|\Z)", text, re.M | re.S)
    return m.group(1) if m else None


def parse_counts(block: str | None) -> dict:
    if not block:
        return {}
    return {k: int(v) for k, v in re.findall(r"^\s*([01]{2}):\s*(\d+)\s*$", block, re.M)}


def parse_fields(block: str | None) -> dict:
    if not block:
        return {}
    return dict(re.findall(r"^\s*([A-Za-z][A-Za-z ]+?):\s*(.+?)\s*$", block, re.M))


def render_hardware():
    st.header("4 · IBM Quantum Hardware")
    st.write(
        "Our only real-hardware job so far is a **2-qubit Bell-state test** on IBM `ibm_fez`. "
        "It checks that we can submit jobs and retrieve results. **It is not the scheduling QAOA.**"
    )

    text = load_text(RESULTS / "bell_state_ibm_fez_2026-11-09.md")
    if text:
        info = parse_fields(md_section(text, "Experiment Information"))
        if info:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Processor", info.get("Processor", "n/a"))
            c2.metric("Circuit qubits", info.get("Circuit qubits", "n/a"))
            c3.metric("Hardware shots", info.get("Hardware shots", "n/a"))
            c4.metric("Job status", info.get("Job status", "n/a"))
            st.caption(
                f"Date: {info.get('Date', 'n/a')} · Job ID: `{info.get('Job ID', 'n/a')}` · "
                f"IBM plan: {info.get('IBM plan', 'n/a')}"
            )
        else:
            st.warning("Could not read the experiment information block from the Bell-state report.")

        sim = parse_counts(md_section(text, "Simulator Results"))
        hw = parse_counts(md_section(text, "Real IBM Hardware Results"))
        if sim and hw:
            outcomes = sorted(set(sim) | set(hw))
            sim_total, hw_total = sum(sim.values()), sum(hw.values())
            df = pd.DataFrame(
                {
                    "Outcome": outcomes,
                    "Simulator count": [sim.get(o, 0) for o in outcomes],
                    "Simulator %": [round(100 * sim.get(o, 0) / sim_total, 1) for o in outcomes],
                    "ibm_fez count": [hw.get(o, 0) for o in outcomes],
                    "ibm_fez %": [round(100 * hw.get(o, 0) / hw_total, 1) for o in outcomes],
                }
            )
            left, right = st.columns([1, 1])
            with left:
                st.markdown(f"**Measurement counts** (simulator: {sim_total} shots, hardware: {hw_total} shots)")
                st.dataframe(df, hide_index=True, width="stretch")
                corr = hw.get("00", 0) + hw.get("11", 0)
                st.metric(
                    "Hardware correlated outcomes (00 or 11)",
                    f"{100 * corr / hw_total:.0f}%",
                    help="Ideal Bell state: 50% 00 and 50% 11, never 01 or 10.",
                )
            with right:
                st.markdown("**Outcome distribution (% of shots)**")
                st.bar_chart(
                    df.set_index("Outcome")[["Simulator %", "ibm_fez %"]],
                    stack=False,
                    y_label="% of shots",
                )
            st.caption(
                "The 5% unexpected outcomes on hardware are consistent with noise, gate errors "
                "or measurement errors; the experiment does not identify which."
            )
        else:
            st.warning("Could not read the simulator/hardware count tables from the Bell-state report.")

        limits = md_section(text, "Scientific Limitations")
        st.markdown("**Limitations of this hardware test**")
        if limits:
            st.markdown(limits.strip())
        else:
            st.warning("Limitations section not found in the Bell-state report.")

        with st.expander("Full Bell-state report (as saved)"):
            st.markdown(text)

    st.divider()
    st.subheader("Preparing the wrestling QAOA for hardware (local tests only)")
    st.warning(
        "No wrestling QAOA job has been submitted to IBM hardware. The work below used "
        "local transpilation and a FakeFez snapshot only; real hardware accuracy and "
        "runtime are unknown.",
        icon="🧪",
    )
    prep = load_text(RESULTS / "qaoa_hardware_optimization_validation_2026-11-09.md")
    if prep:
        st.markdown(
            "- The 14-qubit p=1 circuit grows from depth 79 (logical) to roughly 440–495 when "
            "transpiled for ibm_fez, with 320–440 two-qubit (CZ) gates.\n"
            "- Optimization level 2 reduced CZ gates by about 27% relative to level 1.\n"
            "- The optimized circuit matched the original's ideal probabilities at 4 tested "
            "parameter settings (noise-free statevector check).\n"
            "- Hundreds of two-qubit gates remain, so hardware noise is a significant concern."
        )
        with st.expander("Full hardware-preparation report (as saved)"):
            st.markdown(prep)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

if section.startswith("1"):
    render_schedule()
elif section.startswith("2"):
    render_comparison()
elif section.startswith("3"):
    render_charts()
else:
    render_hardware()
