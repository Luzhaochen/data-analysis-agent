# -*- coding: utf-8 -*-
"""oversight_console.py — Human Oversight Console (prototype)

The interaction layer of the CS619 project's three ideas: verify · approve · inspect.
Prototype only: no live agent, no database access. Content comes from the real
2026-10-31 working session and the real knowledge base.

Run: streamlit run oversight_console.py
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

REPO = Path(__file__).parent
DECISIONS = REPO / "gui_decisions.json"

st.set_page_config(page_title="Data Agent · Oversight Console", layout="wide",
                   page_icon="🧭")

st.title("Data Analysis Agent — Human Oversight Console")
st.caption("Interaction-layer prototype (verify · approve · correct). Content is from the "
           "real 2026-10-31 session; the prototype does not modify the real knowledge base "
           "and does not connect to the database.")

tab_verify, tab_approve, tab_inspect = st.tabs(
    ["① Verify before execution", "② Approve memory updates", "③ Inspect the knowledge base"])

# ---------------------------------------------------------------- ① Verify
with tab_verify:
    st.subheader("Verify before execution: the SQL and the source of every caliber")
    st.markdown("**User question**: What is the Q1 2026 refund rate?")
    st.code(
        "SELECT ROUND(SUM(r.refund_amt), 2) AS refund_amt,\n"
        "       ROUND((SELECT SUM(pay_amt) FROM orders\n"
        "              WHERE order_dt >= '2026-01-01' AND order_dt < '2026-04-01'\n"
        "                AND order_status <> 'cancelled'), 2) AS gmv,\n"
        "       ROUND(SUM(r.refund_amt) / (SELECT SUM(pay_amt) FROM orders\n"
        "              WHERE order_dt >= '2026-01-01' AND order_dt < '2026-04-01'\n"
        "                AND order_status <> 'cancelled') * 100, 4) AS refund_rate_pct\n"
        "FROM refunds r\n"
        "WHERE r.refund_dt >= '2026-01-01' AND r.refund_dt < '2026-04-01';",
        language="sql",
    )
    st.markdown("**Caliber declarations (each with its source)**")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.info("**GMV** = SUM(pay_amt)\n\ncancelled orders excluded\n\n📎 orders.md · Calibers")
    with c2:
        st.info("**Time attribution** = refund date\n\nrefund_dt, left-closed right-open\n\n"
                "📎 refunds.md · Time fields")
    with c3:
        st.info("**Refund rate** = refunds ÷ same-period GMV\n\namount-based, "
                "confirmed 2026-10-31\n\n📎 refunds.md · Calibers")

    if "verify_state" not in st.session_state:
        st.session_state.verify_state = None
    col_ok, col_no = st.columns(2)
    if col_ok.button("✓ Confirm and run", type="primary"):
        st.session_state.verify_state = "approved"
    if col_no.button("✗ Reject"):
        st.session_state.verify_state = "rejected"

    if st.session_state.verify_state == "approved":
        st.success("Executed (read-only). All five sanity checks passed:")
        st.table({
            "Check": ["Empty result", "Magnitude", "Ratio", "All-NULL columns",
                      "Reconciliation"],
            "Result": ["No — data present in range",
                       "GMV 252.06M / refunds 5.88M — consistent with documented scales",
                       "0.023335 within the valid range", "None",
                       "Category shares sum losslessly to 5,881,693.30 — equal to the total"],
        })
        st.markdown("**Answer: Q1 refund rate 2.33%** "
                    "(5,881,693.30 ÷ 252,056,695.62, refund-day attribution)")
    elif st.session_state.verify_state == "rejected":
        st.warning("Not executed. Back to clarification, waiting for the user's edit.")

# ---------------------------------------------------------------- ② Approve
PROPOSALS = [
    {
        "id": 1,
        "title": "Caliber confirmed · Refund rate",
        "what": "Add one line to refunds.md, Calibers section",
        "preview": "Refund rate (confirmed 2026-10-31): amount-based = refunds ÷ same-period "
                   "GMV (orders caliber, order_status <> 'cancelled'), default refund-day "
                   "attribution",
        "why": "This caliber was marked 'needs confirmation'; today's Q1 rate analysis "
               "relied on it",
        "source": "This session, clarification round 1",
    },
    {
        "id": 2,
        "title": "Reusable snippet · refund_rate_analysis.sql",
        "what": "New file in memory/sql_snippets/ (six variants: overall / monthly / reason / "
                "promo level / category + reconciliation probes)",
        "preview": "-- Scenario: refund rate (amount-based), overall / by month / by dimension\n"
                   "-- Params: replace all date ranges (refunds by refund_dt, orders by "
                   "order_dt, left-closed right-open)",
        "why": "Ran and reconciled in this session (category shares sum losslessly to "
               "5,881,693.30)",
        "source": "This session, query 2",
    },
    {
        "id": 3,
        "title": "Business rule · Category attribution",
        "what": "Add one item to refunds.md, Pitfalls section",
        "preview": "Order-level refunds attributed to categories by each SKU's GMV share "
                   "(order_items.gmv), rolled up via products.category_id → parent_id; "
                   "LEFT-JOIN probe for orphan refunds first",
        "why": "The rule did not exist; defined with the user during this session",
        "source": "This session, clarification round 2",
    },
]

with tab_approve:
    st.subheader("End of session: decide each memory proposal")
    st.caption("Real knowledge-base updates require per-item user permission; this prototype "
               "writes decisions to gui_decisions.json and never touches the real knowledge "
               "base.")
    decisions = {}
    for p in PROPOSALS:
        with st.container(border=True):
            st.markdown(f"**Proposal {p['id']} · {p['title']}**")
            st.markdown(f"- **What to remember**: {p['what']}\n- **Content preview**: "
                        f"{p['preview']}\n- **Why**: {p['why']}\n- **Source**: {p['source']}")
            decision = st.radio("Decision", ["Approve (write as-is)", "Edit (write my version)",
                                             "Reject (do not write)"],
                                key=f"d{p['id']}", horizontal=True,
                                label_visibility="collapsed")
            if decision.startswith("Edit"):
                decisions[p["id"]] = {"decision": "edit",
                                      "edited": st.text_area("Edited content", key=f"e{p['id']}",
                                                             height=68)}
            else:
                decisions[p["id"]] = {"decision":
                                      "approve" if decision.startswith("Approve") else "reject"}
    if st.button("Submit all decisions", type="primary"):
        record = {"submitted_at": datetime.now().isoformat(timespec="seconds"),
                  "decisions": decisions}
        DECISIONS.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        st.success(f"Decisions recorded to {DECISIONS.name} (prototype does not modify the "
                   f"knowledge base). Approved "
                   f"{sum(1 for d in decisions.values() if d['decision'] == 'approve')}, edited "
                   f"{sum(1 for d in decisions.values() if d['decision'] == 'edit')}, rejected "
                   f"{sum(1 for d in decisions.values() if d['decision'] == 'reject')}.")

# ---------------------------------------------------------------- ③ Inspect
with tab_inspect:
    st.subheader("Memory browser: what the knowledge base contains")
    st.caption("Calls list_memories.py live (read-only, deterministic).")
    if st.button("Refresh knowledge-base status"):
        try:
            out = subprocess.run(
                [sys.executable, str(REPO / "skills" / "database-query" / "scripts"
                                     / "list_memories.py")],
                capture_output=True, text=True, encoding="utf-8", timeout=60,
                env={**os.environ, "PYTHONUTF8": "1"},
            )
            st.session_state.memory_out = out.stdout if out.returncode == 0 else out.stderr
        except subprocess.TimeoutExpired:
            st.session_state.memory_out = "(timed out)"
    if st.session_state.get("memory_out"):
        st.code(st.session_state.memory_out, language=None)
    else:
        st.info("Click 'Refresh knowledge-base status' to see the current state of memory/ "
                "(table docs / SQL snippets / drafts / syntax rules).")
