"""
CPU Scheduling Simulator
Algorithms: FCFS, SJF (Preemptive / Non-Preemptive), Priority (Preemptive / Non-Preemptive), Round Robin
Run:  streamlit run app.py
"""
import base64   # Gantt chart image ko text (base64) mein convert karne ke liye, taake usse HTML <img> mein seedha embed kar sakein
import io       # memory mein temporary "file" (BytesIO) banane ke liye, taake chart disk pe save kiye bagair yahin pakar sakein
from collections import deque   # Round Robin ki ready queue ke liye (front se popleft(), end mein append() fast hota hai)

import matplotlib   # chart banane wali main library

matplotlib.use("Agg")   # bina window ke chart banane wala backend (server pe screen nahi hoti)
import matplotlib.pyplot as plt   # chart draw karne ke functions (subplots, barh, text, etc.)
import pandas as pd               # results ko DataFrame mein rakh ke HTML table (to_html) banane ke liye
import streamlit as st            # web GUI library: buttons, input boxes, sidebar, tabs, sab kuch

MAX_PROCESSES = 20
MAX_VALUE = 1000  # upper limit for AT / BT / Priority / Time Quantum

# ----------------------------------------------------------------------------
# Algorithm metadata
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
# Scheduling core
# ----------------------------------------------------------------------------
def _add_segment(gantt, name, start, end):
    """Append a Gantt segment, merging it with the previous one if it continues."""
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
        if not ready:  # CPU idle until next arrival
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
    """key(process, remaining_time) -> sortable tuple; the smallest tuple wins."""
    n = len(procs)
    rt = {p["name"]: p["bt"] for p in procs}
    ct, first_start, gantt = {}, {}, []
    t = 0
    while len(ct) < n:
        ready = [p for p in procs if rt[p["name"]] > 0 and p["at"] <= t]
        if not ready:  # CPU idle until next arrival
            nxt = min(p["at"] for p in procs if rt[p["name"]] > 0)
            _add_segment(gantt, "Idle", t, nxt)
            t = nxt
            continue
        p = min(ready, key=lambda x: key(x, rt[x["name"]]))
        name = p["name"]
        first_start.setdefault(name, t)
        # Run until it finishes or until the next arrival, whichever comes first
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
        if not queue:  # CPU idle until next arrival
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
        ptr = admit(ptr, t)  # arrivals during this slice are queued BEFORE p
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
# Validation
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
# Gantt chart (rendered as an inline SVG image, so no fullscreen/zoom toolbar)
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
        if fig_w * (e - s) / total >= 0.35:  # skip label if the bar is too narrow
            ax.text((s + e) / 2, 0, name, ha="center", va="center",
                    fontsize=10, fontweight="bold", color="#0f172a")

    ticks = sorted({0} | {g[1] for g in gantt} | {g[2] for g in gantt})
    ax.set_xticks(ticks)
    if len(ticks) > fig_w * 1.6:  # crowded axis: rotate labels
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
    min_w = min(max(total * 36, 600), 2400)
    return (
        '<div class="gantt-wrap"><img alt="Gantt chart" '
        f'style="min-width:{min_w}px;width:100%;" src="data:image/svg+xml;base64,{b64}"></div>'
    )


# ----------------------------------------------------------------------------
# Styling
# ----------------------------------------------------------------------------
CSS = """
<style>
#MainMenu, footer {visibility: hidden;}
.block-container {padding-top: 2rem; max-width: 1080px;}

.app-title {font-size: 1.9rem; font-weight: 700; margin: 0;}
.app-sub {opacity: .7; margin: .25rem 0 0 0;}
.app-head {border-bottom: 1px solid rgba(128,128,128,.35); padding-bottom: .9rem; margin-bottom: 1.2rem;}

.selected {
    border-left: 4px solid #1e3a5f; background: rgba(30,58,95,.06);
    padding: .8rem 1rem; border-radius: 4px; margin: .4rem 0 1rem 0;
}
.selected .name {font-weight: 700; font-size: 1.05rem;}
.selected .tag {
    font-size: .78rem; font-weight: 600; margin-left: .5rem; padding: .1rem .5rem;
    border: 1px solid rgba(128,128,128,.6); border-radius: 4px; opacity: .85;
}

div[data-testid="stMetric"] {
    border: 1px solid rgba(128,128,128,.3); border-radius: 6px; padding: .6rem .9rem;
}

div.stButton > button[kind="primary"],
button[data-testid^="stBaseButton-primary"] {
    background-color: #1e3a5f; border-color: #1e3a5f; color: #fff; border-radius: 6px;
}
div.stButton > button[kind="primary"]:hover,
button[data-testid^="stBaseButton-primary"]:hover {
    background-color: #274b7a; border-color: #274b7a; color: #fff;
}

.table-wrap {overflow-x: auto; background: #fff; border: 1px solid #cbd5e1; border-radius: 6px;}
table.result-table {width: 100%; border-collapse: collapse; font-size: .95rem;}
table.result-table th {
    background: #f1f5f9; color: #0f172a; padding: .55rem .7rem; text-align: center;
    border-bottom: 2px solid #cbd5e1;
}
table.result-table td {
    color: #0f172a; padding: .5rem .7rem; text-align: center; border-bottom: 1px solid #e2e8f0;
}
table.result-table tr:last-child td {border-bottom: none;}

.gantt-wrap {overflow-x: auto; background: #fff; border: 1px solid #cbd5e1; border-radius: 6px; padding: .5rem;}
.gantt-wrap img {display: block;}
.order {opacity: .7; font-size: .9rem; margin-top: .6rem;}
</style>
"""


# ----------------------------------------------------------------------------
# Session state helpers
# ----------------------------------------------------------------------------
def init_state():
    """
    Streamlit deletes the state of any widget that is not drawn in a run
    (switching algorithm, hiding the Priority column, reducing process count).
    Re-assigning each key at the top of every run stops that clean-up, so the
    values the user typed are never lost.
    """
    defaults = {"n_proc": 4, "tq": 2}
    for i in range(MAX_PROCESSES):
        defaults[f"at_{i}"] = 0
        defaults[f"bt_{i}"] = 1
        defaults[f"pr_{i}"] = i + 1
    for key, default in defaults.items():
        st.session_state[key] = st.session_state.get(key, default)


# ----------------------------------------------------------------------------
# UI sections
# ----------------------------------------------------------------------------
def render_header():
    st.markdown(
        """
        <div class="app-head">
            <p class="app-title">CPU Scheduling Simulator</p>
            <p class="app-sub">Welcome. Select an algorithm from the sidebar, enter the process
            details, and run the simulation to see the results table, averages and Gantt chart.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("Algorithms Guide"):
        tabs = st.tabs(list(ALGO_INFO.keys()))
        for tab, (name, info) in zip(tabs, ALGO_INFO.items()):
            with tab:
                st.markdown(f"**{name}** ({info['type']})")
                st.write(info["summary"])
                st.markdown(f"**How it works:** {info['how']}")
                st.markdown(f"**Advantages:** {info['pros']}")
                st.markdown(f"**Disadvantages:** {info['cons']}")
        st.divider()
        st.markdown(GLOSSARY, unsafe_allow_html=True)


def render_sidebar():
    with st.sidebar:
        st.header("Select Algorithm")
        algo = st.radio("Algorithm", list(ALGO_INFO.keys()), label_visibility="collapsed")
        st.divider()
        st.caption("For Priority scheduling, a lower number means a higher priority.")
        st.caption("Ties are broken by earlier arrival time, then by process number.")
    return algo


def render_setup(algo):
    """Algorithm card + number of processes + time quantum (these change the form layout)."""
    info = ALGO_INFO[algo]

    st.markdown(
        f"""
        <div class="selected">
            <span class="name">{algo}</span><span class="tag">{info['type']}</span><br>
            <span>{info['summary']}</span>
        </div>
        """,
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
    All process inputs live inside a form: typing does NOT rerun the app.
    Values are applied only when 'Run Simulation' is pressed (or Enter is hit).
    """
    info = ALGO_INFO[algo]
    st.subheader("2. Process Details")

    with st.form("process_form", border=False):
        spec = [1, 2, 2, 2] if info["needs_priority"] else [1, 2, 2]
        headers = ["Process", "Arrival Time", "Burst Time"] + (["Priority"] if info["needs_priority"] else [])
        for col, h in zip(st.columns(spec), headers):
            col.markdown(f"**{h}**")

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
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Avg Waiting Time", f"{sum(r['WT'] for r in rows) / n:.2f}")
    m2.metric("Avg Turnaround Time", f"{sum(r['TAT'] for r in rows) / n:.2f}")
    m3.metric("Avg Response Time", f"{sum(r['RT'] for r in rows) / n:.2f}")
    m4.metric("CPU Utilization", f"{busy / makespan * 100:.1f}%")

    cols = ["Process", "AT", "BT"] + (["Priority"] if info["needs_priority"] else []) \
        + ["CT", "TAT", "WT", "RT"]
    table = pd.DataFrame(rows)[cols].to_html(index=False, border=0, classes="result-table")
    st.markdown(f'<div class="table-wrap">{table}</div>', unsafe_allow_html=True)

    st.subheader("Gantt Chart")
    st.markdown(gantt_html(gantt), unsafe_allow_html=True)
    order = " | ".join(f"{name} [{s}-{e}]" for name, s, e in gantt)
    st.markdown(f'<div class="order">Execution order: {order}</div>', unsafe_allow_html=True)


def signature(algo, procs, tq):
    """Fingerprint of the inputs; used to know if the saved result still matches them."""
    return (algo, tq, tuple((p["at"], p["bt"], p["pr"]) for p in procs))


def main():
    st.set_page_config(page_title="CPU Scheduling Simulator", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    init_state()

    render_header()
    algo = render_sidebar()
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
        except Exception as exc:  # last-resort safety net
            st.session_state.pop("result", None)
            st.error(f"Something went wrong while running the simulation: {exc}")
            return

    # The result stays on screen until the inputs or the algorithm actually change
    res = st.session_state.get("result")
    if res and res["sig"] == signature(algo, procs, tq):
        render_results(res["algo"], res["rows"], res["gantt"])


if __name__ == "__main__":
    main()
