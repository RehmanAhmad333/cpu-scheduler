"""
CPU Scheduling Simulator
FCFS, SJF (preemptive / non-preemptive), Priority (preemptive / non-preemptive), Round Robin.
Run with:  streamlit run app.py
"""
import base64
import io
from collections import deque

import matplotlib

matplotlib.use("Agg")  # no display on a server, so draw to memory only
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

MAX_PROCESSES = 20
MAX_VALUE = 1000  # upper limit for arrival, burst, priority and time quantum

# ----------------------------------------------------------------------------
# Algorithm info (also decides which input boxes are shown)
# ----------------------------------------------------------------------------
ALGO_INFO = {
    "FCFS": {
        "type": "Non-Preemptive",
        "needs_priority": False,
        "needs_tq": False,
        "summary": "First Come, First Served. Processes run strictly in the order they arrive.",
        "how": "The process with the earliest arrival time gets the CPU and runs to completion. "
               "The next process in arrival order then starts.",
        "pros": "Simple to implement; no starvation.",
        "cons": "Convoy effect: one long process makes all later processes wait. Average waiting time can be high.",
    },
    "SJF Preemptive (SRTF)": {
        "type": "Preemptive",
        "needs_priority": False,
        "needs_tq": False,
        "summary": "Shortest Remaining Time First. The process with the least remaining burst time runs.",
        "how": "At every moment, the CPU is given to the arrived process with the smallest remaining time. "
               "If a new process arrives with a shorter remaining time than the running one, the running process is preempted.",
        "pros": "Gives the minimum average waiting time among these algorithms.",
        "cons": "Needs burst times in advance; long processes may starve; more context switches.",
    },
    "SJF Non-Preemptive": {
        "type": "Non-Preemptive",
        "needs_priority": False,
        "needs_tq": False,
        "summary": "Shortest Job First. Among the processes that have arrived, the shortest burst time is chosen.",
        "how": "When the CPU becomes free, the arrived process with the smallest burst time is selected "
               "and runs to completion without interruption.",
        "pros": "Low average waiting time; no context switching during a burst.",
        "cons": "Needs burst times in advance; long processes may starve.",
    },
    "Priority Preemptive": {
        "type": "Preemptive",
        "needs_priority": True,
        "needs_tq": False,
        "summary": "The process with the highest priority runs. A lower number means a higher priority.",
        "how": "At every moment, the arrived process with the best (lowest) priority number runs. "
               "If a higher-priority process arrives, the running process is preempted.",
        "pros": "Important processes get the CPU quickly.",
        "cons": "Low-priority processes may starve.",
    },
    "Priority Non-Preemptive": {
        "type": "Non-Preemptive",
        "needs_priority": True,
        "needs_tq": False,
        "summary": "The arrived process with the highest priority is chosen when the CPU becomes free.",
        "how": "When the CPU is free, the arrived process with the lowest priority number is selected "
               "and runs to completion. A higher-priority arrival must wait.",
        "pros": "Simple; no preemption overhead.",
        "cons": "A high-priority process may wait behind a long low-priority one; starvation is possible.",
    },
    "Round Robin": {
        "type": "Preemptive (time quantum)",
        "needs_priority": False,
        "needs_tq": True,
        "summary": "Each process gets the CPU for a fixed time quantum, then goes to the back of the queue.",
        "how": "Processes wait in a FIFO ready queue. The first process runs for at most one time quantum. "
               "If it is not finished, it moves to the end of the queue. Processes arriving during a slice are queued before the preempted process.",
        "pros": "Fair sharing; good response time; no starvation.",
        "cons": "Performance depends on the quantum size; many context switches if it is too small.",
    },
}

GLOSSARY = (
    "**AT** Arrival Time &nbsp;|&nbsp; **BT** Burst Time &nbsp;|&nbsp; **CT** Completion Time &nbsp;|&nbsp; "
    "**TAT** Turnaround Time = CT - AT &nbsp;|&nbsp; **WT** Waiting Time = TAT - BT &nbsp;|&nbsp; "
    "**RT** Response Time = first CPU start - AT"
)


# ----------------------------------------------------------------------------
# Scheduling logic
# ----------------------------------------------------------------------------
def _add_segment(gantt, name, start, end):
    """Add a block to the Gantt list. If it continues the last block, just extend that one."""
    if end <= start:
        return
    if gantt and gantt[-1][0] == name and gantt[-1][2] == start:
        gantt[-1] = (name, gantt[-1][1], end)
    else:
        gantt.append((name, start, end))


def _build_rows(procs, ct, first_start):
    rows = []
    for p in procs:
        tat = ct[p["name"]] - p["at"]
        rows.append(
            {
                "Process": p["name"],
                "AT": p["at"],
                "BT": p["bt"],
                "Priority": p["pr"],
                "CT": ct[p["name"]],
                "TAT": tat,
                "WT": tat - p["bt"],
                "RT": first_start[p["name"]] - p["at"],
            }
        )
    return rows


def run_non_preemptive(procs, key):
    n = len(procs)
    done, ct, first_start, gantt = set(), {}, {}, []
    t = 0
    while len(done) < n:
        ready = [p for p in procs if p["name"] not in done and p["at"] <= t]
        if not ready:  # nobody has arrived yet, so the CPU waits
            nxt = min(p["at"] for p in procs if p["name"] not in done)
            _add_segment(gantt, "Idle", t, nxt)
            t = nxt
            continue
        p = min(ready, key=key)
        first_start[p["name"]] = t
        _add_segment(gantt, p["name"], t, t + p["bt"])
        t += p["bt"]
        ct[p["name"]] = t
        done.add(p["name"])
    return _build_rows(procs, ct, first_start), gantt


def run_preemptive(procs, key):
    """key(process, remaining_time) gives a tuple, and the smallest tuple gets the CPU."""
    n = len(procs)
    rt = {p["name"]: p["bt"] for p in procs}
    ct, first_start, gantt = {}, {}, []
    t = 0
    while len(ct) < n:
        ready = [p for p in procs if rt[p["name"]] > 0 and p["at"] <= t]
        if not ready:  # nobody has arrived yet, so the CPU waits
            nxt = min(p["at"] for p in procs if rt[p["name"]] > 0)
            _add_segment(gantt, "Idle", t, nxt)
            t = nxt
            continue
        p = min(ready, key=lambda x: key(x, rt[x["name"]]))
        name = p["name"]
        first_start.setdefault(name, t)
        # run until it finishes or the next process arrives, whichever is first
        future = [q["at"] for q in procs if q["at"] > t and rt[q["name"]] > 0]
        run = rt[name] if not future else min(rt[name], min(future) - t)
        _add_segment(gantt, name, t, t + run)
        t += run
        rt[name] -= run
        if rt[name] == 0:
            ct[name] = t
    return _build_rows(procs, ct, first_start), gantt


def run_round_robin(procs, tq):
    n = len(procs)
    order = sorted(procs, key=lambda p: (p["at"], p["i"]))
    rt = {p["name"]: p["bt"] for p in procs}
    ct, first_start, gantt = {}, {}, []
    queue, ptr, t = deque(), 0, 0

    def admit(ptr, t):
        while ptr < n and order[ptr]["at"] <= t:
            queue.append(order[ptr])
            ptr += 1
        return ptr

    while len(ct) < n:
        ptr = admit(ptr, t)
        if not queue:  # nobody is waiting, so jump to the next arrival
            nxt = order[ptr]["at"]
            _add_segment(gantt, "Idle", t, nxt)
            t = nxt
            continue
        p = queue.popleft()
        name = p["name"]
        first_start.setdefault(name, t)
        run = min(tq, rt[name])
        _add_segment(gantt, name, t, t + run)
        t += run
        rt[name] -= run
        ptr = admit(ptr, t)  # new arrivals join the queue before the process that just ran
        if rt[name] > 0:
            queue.append(p)
        else:
            ct[name] = t
    return _build_rows(procs, ct, first_start), gantt


def run_algorithm(algo, procs, tq=None):
    if algo == "FCFS":
        return run_non_preemptive(procs, lambda p: (p["at"], p["i"]))
    if algo == "SJF Non-Preemptive":
        return run_non_preemptive(procs, lambda p: (p["bt"], p["at"], p["i"]))
    if algo == "Priority Non-Preemptive":
        return run_non_preemptive(procs, lambda p: (p["pr"], p["at"], p["i"]))
    if algo == "SJF Preemptive (SRTF)":
        return run_preemptive(procs, lambda p, r: (r, p["at"], p["i"]))
    if algo == "Priority Preemptive":
        return run_preemptive(procs, lambda p, r: (p["pr"], p["at"], p["i"]))
    if algo == "Round Robin":
        return run_round_robin(procs, tq)
    raise ValueError(f"Unknown algorithm: {algo}")


# ----------------------------------------------------------------------------
# Input checks
# ----------------------------------------------------------------------------
def validate(algo, procs, tq):
    errors = []
    info = ALGO_INFO.get(algo)
    if info is None:
        return ["Please select a valid algorithm."]
    if not 1 <= len(procs) <= MAX_PROCESSES:
        errors.append(f"Number of processes must be between 1 and {MAX_PROCESSES}.")
    for p in procs:
        if p["at"] is None or not 0 <= p["at"] <= MAX_VALUE:
            errors.append(f"{p['name']}: Arrival Time must be between 0 and {MAX_VALUE}.")
        if p["bt"] is None or not 1 <= p["bt"] <= MAX_VALUE:
            errors.append(f"{p['name']}: Burst Time must be between 1 and {MAX_VALUE}.")
        if info["needs_priority"] and (p["pr"] is None or not 0 <= p["pr"] <= MAX_VALUE):
            errors.append(f"{p['name']}: Priority must be between 0 and {MAX_VALUE}.")
    if info["needs_tq"] and (tq is None or not 1 <= tq <= MAX_VALUE):
        errors.append(f"Time Quantum must be between 1 and {MAX_VALUE}.")
    return errors


# ----------------------------------------------------------------------------
# Gantt chart (drawn as an inline SVG image, so it has no zoom/fullscreen toolbar)
# ----------------------------------------------------------------------------
PALETTE = ["#9ec5e8", "#f2c18d", "#a8d5ba", "#e3a8b5", "#c4b5e0", "#f0e08a",
           "#8fd0cf", "#d9b99b", "#b7c9a0", "#e8b4d6"]


def gantt_html(gantt):
    total = gantt[-1][2]
    fig_w = max(8, min(total * 0.5, 24))
    fig, ax = plt.subplots(figsize=(fig_w, 1.9))
    fig.patch.set_facecolor("white")
    names = []
    for name, _, _ in gantt:
        if name != "Idle" and name not in names:
            names.append(name)

    for name, s, e in gantt:
        if name == "Idle":
            ax.barh(0, e - s, left=s, height=0.62, color="#f1f5f9",
                    edgecolor="#94a3b8", hatch="//", linewidth=1)
        else:
            ax.barh(0, e - s, left=s, height=0.62,
                    color=PALETTE[names.index(name) % len(PALETTE)],
                    edgecolor="#334155", linewidth=1)
        if fig_w * (e - s) / total >= 0.35:  # bar is too thin for a label otherwise
            ax.text((s + e) / 2, 0, name, ha="center", va="center",
                    fontsize=10, fontweight="bold", color="#0f172a")

    ticks = sorted({0} | {g[1] for g in gantt} | {g[2] for g in gantt})
    ax.set_xticks(ticks)
    if len(ticks) > fig_w * 1.6:  # too many numbers, turn them sideways
        plt.setp(ax.get_xticklabels(), rotation=90)
    ax.set_xlim(0, total)
    ax.set_ylim(-0.5, 0.5)
    ax.set_yticks([])
    ax.tick_params(axis="x", colors="#334155", labelsize=9)
    ax.set_xlabel("Time", color="#334155")
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#94a3b8")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="svg", facecolor="white")
    plt.close(fig)
    b64 = base64.b64encode(buf.getvalue()).decode()
    min_w = min(max(total * 36, 600), 2400)  # on a phone the chart scrolls sideways
    return (
        '<div class="scroll-box"><img alt="Gantt chart" '
        f'style="min-width:{min_w}px;width:100%;display:block;" '
        f'src="data:image/svg+xml;base64,{b64}"></div>'
    )


def metrics_html(items):
    """Summary cards. A CSS grid gives 4 across on desktop and 2 x 2 on a phone."""
    cards = "".join(
        f'<div class="metric"><div class="m-label">{label}</div><div class="m-value">{value}</div></div>'
        for label, value in items
    )
    return f'<div class="metrics">{cards}</div>'


# ----------------------------------------------------------------------------
# Styling
# ----------------------------------------------------------------------------
CSS = """
<style>
#MainMenu, footer {visibility: hidden;}
.block-container, [data-testid="stMainBlockContainer"] {
    padding-top: 4.5rem !important;  /* clears Streamlit's fixed 3.75rem header */
    max-width: 1080px;
}

/* header */
.app-title {font-size: clamp(1.45rem, 5.5vw, 1.9rem); font-weight: 700; margin: 0; line-height: 1.2;}
.app-sub {opacity: .7; margin: .3rem 0 0 0;}
.app-head {border-bottom: 1px solid rgba(128,128,128,.35); padding-bottom: .9rem; margin-bottom: 1.2rem;}

/* selected algorithm card */
.selected {
    border-left: 4px solid #1e3a5f; background: rgba(30,58,95,.06);
    padding: .8rem 1rem; border-radius: 4px; margin: .4rem 0 1rem 0;
}
.selected .name {font-weight: 700; font-size: 1.05rem;}
.selected .tag {
    display: inline-block; font-size: .78rem; font-weight: 600; margin-left: .5rem; padding: .1rem .5rem;
    border: 1px solid rgba(128,128,128,.6); border-radius: 4px; opacity: .85;
}

/* buttons */
div.stButton > button[kind="primary"],
button[data-testid^="stBaseButton-primary"] {
    background-color: #1e3a5f; border-color: #1e3a5f; color: #fff; border-radius: 6px; min-height: 2.8rem;
}
div.stButton > button[kind="primary"]:hover,
button[data-testid^="stBaseButton-primary"]:hover {
    background-color: #274b7a; border-color: #274b7a; color: #fff;
}

/* process form: keep every row on one line, even on a phone */
[data-testid="stForm"] [data-testid="stHorizontalBlock"] {flex-wrap: nowrap !important;}
[data-testid="stForm"] [data-testid="stColumn"],
[data-testid="stForm"] [data-testid="column"] {min-width: 0 !important;}
.col-head {font-weight: 700;}
.col-head .sm {display: none;}
.mobile-only {display: none;}

/* summary cards */
.metrics {display: grid; grid-template-columns: repeat(4, 1fr); gap: .6rem; margin-bottom: 1rem;}
.metric {border: 1px solid rgba(128,128,128,.3); border-radius: 6px; padding: .6rem .9rem;}
.m-label {font-size: .85rem; opacity: .7;}
.m-value {font-size: 1.6rem; font-weight: 600; line-height: 1.3;}

/* results table and chart */
.scroll-box {
    overflow-x: auto; -webkit-overflow-scrolling: touch;
    background: #fff; border: 1px solid #cbd5e1; border-radius: 6px;
}
table.result-table {width: 100%; border-collapse: collapse; font-size: .95rem;}
table.result-table th {
    background: #f1f5f9; color: #0f172a; padding: .55rem .7rem; text-align: center;
    border-bottom: 2px solid #cbd5e1; white-space: nowrap;
}
table.result-table td {
    color: #0f172a; padding: .5rem .7rem; text-align: center;
    border-bottom: 1px solid #e2e8f0; white-space: nowrap;
}
table.result-table tr:last-child td {border-bottom: none;}
/* the Process column stays visible while the table scrolls sideways */
table.result-table th:first-child, table.result-table td:first-child {position: sticky; left: 0; z-index: 1;}
table.result-table td:first-child {background: #fff; font-weight: 600;}
.swipe-hint {display: none; opacity: .65; font-size: .8rem; margin: .3rem 0 .6rem 0;}
.order {opacity: .7; font-size: .9rem; margin-top: .6rem; word-break: break-word;}

/* phones */
@media (max-width: 640px) {
    .block-container, [data-testid="stMainBlockContainer"] {padding: 4.2rem .8rem 3rem !important;}
    .app-head {margin-bottom: .8rem;}

    [data-testid="stForm"] [data-testid="stHorizontalBlock"] {gap: .4rem !important;}
    [data-testid="stForm"] [data-testid="stNumberInputStepUp"],
    [data-testid="stForm"] [data-testid="stNumberInputStepDown"] {display: none;}
    [data-testid="stForm"] [data-testid="stNumberInput"] input {
        padding: .45rem .5rem; font-size: 16px; /* 16px stops iOS from zooming on focus */
    }
    .col-head {font-size: .9rem;}
    .col-head .lg {display: none;}
    .col-head .sm {display: inline;}
    .mobile-only {display: block; opacity: .7; font-size: .85rem; margin-bottom: .5rem;}

    .metrics {grid-template-columns: repeat(2, 1fr);}
    .m-value {font-size: 1.35rem;}

    table.result-table {font-size: .85rem;}
    table.result-table th, table.result-table td {padding: .45rem .55rem;}
    .swipe-hint {display: block;}
}
</style>
"""


# ----------------------------------------------------------------------------
# Session state
# ----------------------------------------------------------------------------
def init_state():
    """
    Streamlit forgets a widget's value when the widget is not drawn in a run
    (for example when you switch algorithm or lower the process count).
    Writing every key back at the start of each run keeps those values alive.
    """
    defaults = {"n_proc": 4, "tq": 2}
    for i in range(MAX_PROCESSES):
        defaults[f"at_{i}"] = 0
        defaults[f"bt_{i}"] = 1
        defaults[f"pr_{i}"] = i + 1
    for key, default in defaults.items():
        st.session_state[key] = st.session_state.get(key, default)


# ----------------------------------------------------------------------------
# Page sections
# ----------------------------------------------------------------------------
def render_header():
    st.markdown(
        '<div class="app-head">'
        '<p class="app-title">CPU Scheduling Simulator</p>'
        '<p class="app-sub">Welcome. Pick an algorithm, enter the process details, and run the '
        'simulation to see the results table, averages and Gantt chart.</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    with st.expander("Algorithms Guide"):
        for i, (name, info) in enumerate(ALGO_INFO.items()):
            if i:
                st.divider()
            st.markdown(
                f"**{name}** ({info['type']})  \n{info['summary']}\n\n"
                f"- **How it works:** {info['how']}\n"
                f"- **Advantages:** {info['pros']}\n"
                f"- **Disadvantages:** {info['cons']}"
            )
        st.divider()
        st.markdown(GLOSSARY, unsafe_allow_html=True)


def render_algorithm_picker():
    # In the main area (not the sidebar) so it is easy to find on a phone
    algo = st.selectbox("Select Algorithm", list(ALGO_INFO.keys()), key="algo")
    st.caption("For Priority scheduling, a lower number means a higher priority. "
               "Ties go to the earlier arrival, then the lower process number.")
    return algo


def render_setup(algo):
    info = ALGO_INFO[algo]

    st.markdown(
        '<div class="selected">'
        f'<span class="name">{algo}</span><span class="tag">{info["type"]}</span><br>'
        f'<span>{info["summary"]}</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    st.subheader("1. Setup")
    c1, c2 = st.columns(2)
    n = c1.number_input(
        f"Number of processes (1 to {MAX_PROCESSES})",
        min_value=1, max_value=MAX_PROCESSES, step=1, key="n_proc",
    )
    tq = None
    if info["needs_tq"]:
        tq = c2.number_input(
            f"Time Quantum (1 to {MAX_VALUE})",
            min_value=1, max_value=MAX_VALUE, step=1, key="tq",
        )
    return int(n), (int(tq) if tq is not None else None)


def render_process_form(algo, n):
    """
    The inputs sit inside a form, so typing does not rerun the app.
    The values are applied when the user presses Run Simulation (or Enter).
    """
    info = ALGO_INFO[algo]
    st.subheader("2. Process Details")
    st.markdown(
        '<div class="mobile-only">AT = Arrival Time, BT = Burst Time'
        + (", PR = Priority" if info["needs_priority"] else "") + "</div>",
        unsafe_allow_html=True,
    )

    with st.form("process_form", border=False):
        spec = [1, 2, 2, 2] if info["needs_priority"] else [1, 2, 2]
        heads = [("Process", "P"), ("Arrival Time", "AT"), ("Burst Time", "BT")]
        if info["needs_priority"]:
            heads.append(("Priority", "PR"))
        for col, (long_name, short_name) in zip(st.columns(spec), heads):
            col.markdown(
                f'<div class="col-head"><span class="lg">{long_name}</span>'
                f'<span class="sm">{short_name}</span></div>',
                unsafe_allow_html=True,
            )

        procs = []
        for i in range(n):
            row = st.columns(spec)
            row[0].markdown(f"P{i + 1}")
            at = row[1].number_input("Arrival Time", min_value=0, max_value=MAX_VALUE,
                                     step=1, key=f"at_{i}", label_visibility="collapsed")
            bt = row[2].number_input("Burst Time", min_value=1, max_value=MAX_VALUE,
                                     step=1, key=f"bt_{i}", label_visibility="collapsed")
            pr = 0
            if info["needs_priority"]:
                pr = row[3].number_input("Priority", min_value=0, max_value=MAX_VALUE,
                                         step=1, key=f"pr_{i}", label_visibility="collapsed")
            procs.append({"name": f"P{i + 1}", "i": i, "at": int(at), "bt": int(bt), "pr": int(pr)})

        submitted = st.form_submit_button("Run Simulation", type="primary", use_container_width=True)
    return procs, submitted


def render_results(algo, rows, gantt):
    info = ALGO_INFO[algo]
    n = len(rows)
    makespan = max(r["CT"] for r in rows)
    busy = sum(r["BT"] for r in rows)

    st.success(f"Simulation completed using {algo} for {n} process(es).")

    st.subheader("Results")
    st.markdown(
        metrics_html([
            ("Avg Waiting Time", f"{sum(r['WT'] for r in rows) / n:.2f}"),
            ("Avg Turnaround Time", f"{sum(r['TAT'] for r in rows) / n:.2f}"),
            ("Avg Response Time", f"{sum(r['RT'] for r in rows) / n:.2f}"),
            ("CPU Utilization", f"{busy / makespan * 100:.1f}%"),
        ]),
        unsafe_allow_html=True,
    )

    cols = ["Process", "AT", "BT"] + (["Priority"] if info["needs_priority"] else []) \
        + ["CT", "TAT", "WT", "RT"]
    table = pd.DataFrame(rows)[cols].to_html(index=False, border=0, classes="result-table")
    st.markdown(f'<div class="scroll-box">{table}</div>'
                '<div class="swipe-hint">Swipe sideways to see the whole table</div>',
                unsafe_allow_html=True)

    st.subheader("Gantt Chart")
    st.markdown(gantt_html(gantt) +
                '<div class="swipe-hint">Swipe sideways to see the whole chart</div>',
                unsafe_allow_html=True)
    order = " | ".join(f"{name} [{s}-{e}]" for name, s, e in gantt)
    st.markdown(f'<div class="order">Execution order: {order}</div>', unsafe_allow_html=True)


def signature(algo, procs, tq):
    """A small fingerprint of the inputs, used to tell if the saved result is still valid."""
    return (algo, tq, tuple((p["at"], p["bt"], p["pr"]) for p in procs))


def main():
    st.set_page_config(page_title="CPU Scheduling Simulator", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    init_state()

    render_header()
    algo = render_algorithm_picker()
    n, tq = render_setup(algo)
    procs, submitted = render_process_form(algo, n)

    if submitted:
        errors = validate(algo, procs, tq)
        if errors:
            st.session_state.pop("result", None)
            for e in errors:
                st.error(e)
            return
        try:
            rows, gantt = run_algorithm(algo, procs, tq)
            st.session_state["result"] = {
                "sig": signature(algo, procs, tq), "algo": algo, "rows": rows, "gantt": gantt,
            }
        except Exception as exc:  # last safety net so the page never crashes
            st.session_state.pop("result", None)
            st.error(f"Something went wrong while running the simulation: {exc}")
            return

    # keep showing the result until the inputs or the algorithm change
    res = st.session_state.get("result")
    if res and res["sig"] == signature(algo, procs, tq):
        render_results(res["algo"], res["rows"], res["gantt"])


if __name__ == "__main__":
    main()
