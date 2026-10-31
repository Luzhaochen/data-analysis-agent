# -*- coding: utf-8 -*-
"""oversight_console.py — Human Oversight Console / 人工监督控制台 (prototype)

The interaction layer of the project's three ideas: verify · approve · inspect.
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

T = {
    "en": {
        "page_title": "Data Agent · Oversight Console",
        "title": "Data Analysis Agent — Human Oversight Console",
        "caption": ("Interaction-layer prototype (verify · approve · correct). Content is "
                    "from the real 2026-10-31 session; the prototype does not modify the "
                    "real knowledge base and does not connect to the database."),
        "tab_v": "① Verify before execution",
        "tab_a": "② Approve memory updates",
        "tab_i": "③ Inspect the knowledge base",
        "v_head": "Verify before execution: the SQL and the source of every caliber",
        "v_question": "**User question**: What is the Q1 2026 refund rate?",
        "v_calibers": "**Caliber declarations (each with its source)**",
        "c_gmv": "**GMV** = SUM(pay_amt)\n\ncancelled orders excluded\n\n📎 orders.md · Calibers",
        "c_time": ("**Time attribution** = refund date\n\nrefund_dt, left-closed right-open\n\n"
                   "📎 refunds.md · Time fields"),
        "c_rate": ("**Refund rate** = refunds ÷ same-period GMV\n\namount-based, confirmed "
                   "2026-10-31\n\n📎 refunds.md · Calibers"),
        "v_ok": "✓ Confirm and run",
        "v_no": "✗ Reject",
        "v_ok_msg": "Executed (read-only). All five sanity checks passed:",
        "chk": ["Empty result", "Magnitude", "Ratio", "All-NULL columns", "Reconciliation"],
        "chk_res": ["No — data present in range",
                    "GMV 252.06M / refunds 5.88M — consistent with documented scales",
                    "0.023335 within the valid range", "None",
                    "Category shares sum losslessly to 5,881,693.30 — equal to the total"],
        "v_answer": ("**Answer: Q1 refund rate 2.33%** (5,881,693.30 ÷ 252,056,695.62, "
                     "refund-day attribution)"),
        "v_rej_msg": "Not executed. Back to clarification, waiting for the user's edit.",
        "a_head": "End of session: decide each memory proposal",
        "a_caption": ("Real knowledge-base updates require per-item user permission; this "
                      "prototype writes decisions to gui_decisions.json and never touches "
                      "the real knowledge base."),
        "p_what": "What to remember",
        "p_prev": "Content preview",
        "p_why": "Why",
        "p_src": "Source",
        "d_ok": "Approve (write as-is)",
        "d_edit": "Edit (write my version)",
        "d_rej": "Reject (do not write)",
        "d_edited": "Edited content",
        "submit": "Submit all decisions",
        "a_ok_msg": "Decisions recorded to gui_decisions.json (prototype does not modify "
                    "the knowledge base). Approved {n1}, edited {n2}, rejected {n3}.",
        "i_head": "Memory browser: what the knowledge base contains",
        "i_caption": "Calls list_memories.py live (read-only, deterministic; tool output is in English).",
        "i_btn": "Refresh knowledge-base status",
        "i_hint": ("Click 'Refresh knowledge-base status' to see the current state of "
                   "memory/ (table docs / SQL snippets / drafts / syntax rules)."),
        "i_timeout": "(timed out)",
    },
    "zh": {
        "page_title": "数据分析智能体 · 人工监督控制台",
        "title": "数据分析智能体 — 人工监督控制台",
        "caption": ("交互层原型（验证 · 批准 · 纠正）。内容取自 2026-10-31 真实会话；"
                    "原型不修改真实知识库、不连接数据库。"),
        "tab_v": "① 执行前验证",
        "tab_a": "② 批准记忆更新",
        "tab_i": "③ 检查知识库",
        "v_head": "执行前验证：SQL 与每条口径的来源",
        "v_question": "**用户问题**：2026 年 Q1 的退款率是多少？",
        "v_calibers": "**口径声明（每条带来源）**",
        "c_gmv": "**GMV** = SUM(pay_amt)\n\n排除 cancelled\n\n📎 orders.md · 指标口径",
        "c_time": "**时间归属** = 退款发生日\n\nrefund_dt 左闭右开\n\n📎 refunds.md · 时间字段",
        "c_rate": ("**退款率** = 退款金额 ÷ 同期 GMV\n\n金额口径，已确认 2026-10-31\n\n"
                   "📎 refunds.md · 指标口径"),
        "v_ok": "✓ 确认，执行",
        "v_no": "✗ 拒绝执行",
        "v_ok_msg": "已执行（只读）。五项结果校验全部通过：",
        "chk": ["空结果", "量级", "比率", "全空字段", "对账"],
        "chk_res": ["无（区间内有数据）",
                    "GMV 2.52 亿 / 退款 588 万，与表文档量级一致",
                    "0.023335 ∈ 合理区间", "无",
                    "三品类分摊合计 5,881,693.30 = 整体退款，无损"],
        "v_answer": ("**答案：Q1 退款率 2.33%**（5,881,693.30 ÷ 252,056,695.62，按退款日归属）"),
        "v_rej_msg": "未执行。已回到澄清环节，等待用户修改口径。",
        "a_head": "会话结束：记忆提案逐条裁决",
        "a_caption": ("真实知识库更新需要逐条获得用户许可；此原型将裁决写入 "
                      "gui_decisions.json，不修改真实知识库。"),
        "p_what": "要记什么",
        "p_prev": "内容预览",
        "p_why": "为什么记",
        "p_src": "来源",
        "d_ok": "确认（照写）",
        "d_edit": "修改（编辑后写）",
        "d_rej": "拒绝（不写）",
        "d_edited": "修改后的内容",
        "submit": "提交全部裁决",
        "a_ok_msg": ("裁决已记录到 gui_decisions.json（原型不修改真实知识库）。"
                     "批准 {n1} 条，修改 {n2} 条，拒绝 {n3} 条。"),
        "i_head": "记忆浏览：知识库里存了什么",
        "i_caption": "实时调用 list_memories.py（只读、确定性；工具输出为英文）。",
        "i_btn": "刷新知识库状态",
        "i_hint": ("点击「刷新知识库状态」查看 memory/ 的现状（表知识 / SQL 片段 / "
                   "草稿 / 语法规则）。"),
        "i_timeout": "（超时）",
    },
}

PROPOSALS = [
    {"en": {"title": "Caliber confirmed · Refund rate",
            "what": "Add one line to refunds.md, Calibers section",
            "preview": ("Refund rate (confirmed 2026-10-31): amount-based = refunds ÷ "
                        "same-period GMV (orders caliber, order_status <> 'cancelled'), "
                        "default refund-day attribution"),
            "why": "This caliber was marked 'needs confirmation'; today's Q1 rate "
                   "analysis relied on it",
            "source": "This session, clarification round 1"},
     "zh": {"title": "口径确认 · 退款率",
            "what": "refunds.md「指标口径」节新增一行",
            "preview": ("退款率（已确认 2026-10-31）：金额口径 = 退款金额 ÷ 同期 GMV"
                        "（orders 口径，order_status <> 'cancelled'），默认按退款发生日归属"),
            "why": "该口径此前标记「待确认」，本次会话的 Q1 退款率分析依赖它",
            "source": "本次会话第 1 轮澄清"}},
    {"en": {"title": "Reusable snippet · refund_rate_analysis.sql",
            "what": ("New file in memory/sql_snippets/ (six variants: overall / monthly / "
                     "reason / promo level / category + reconciliation probes)"),
            "preview": ("-- Scenario: refund rate (amount-based), overall / by month / "
                        "by dimension\n-- Params: replace all date ranges (refunds by "
                        "refund_dt, orders by order_dt, left-closed right-open)"),
            "why": "Ran and reconciled in this session (category shares sum losslessly "
                   "to 5,881,693.30)",
            "source": "This session, query 2"},
     "zh": {"title": "片段入库 · refund_rate_analysis.sql",
            "what": ("memory/sql_snippets/ 新增文件（六写法：整体/按月/原因/等级/品类 "
                     "+ 对账探针）"),
            "preview": ("-- 场景：退款率（金额口径）整体 / 按月 / 分维度\n"
                        "-- 参数：替换所有日期范围（refunds 按 refund_dt、orders 按 "
                        "order_dt，左闭右开）"),
            "why": "本次会话跑通并完成五查对账（合计 5,881,693.30 无损）",
            "source": "本次会话第 2 个查询"}},
    {"en": {"title": "Business rule · Category attribution",
            "what": "Add one item to refunds.md, Pitfalls section",
            "preview": ("Order-level refunds attributed to categories by each SKU's GMV "
                        "share (order_items.gmv), rolled up via products.category_id → "
                        "parent_id; LEFT-JOIN probe for orphan refunds first"),
            "why": "The rule did not exist; defined with the user during this session",
            "source": "This session, clarification round 2"},
     "zh": {"title": "业务规则 · 品类分摊",
            "what": "refunds.md「坑」节新增一条",
            "preview": ("订单级退款金额归属品类：按订单内各 SKU 成交额（order_items.gmv）"
                        "占比分摊，经 products.category_id（二级）→ parent_id 上卷一级品类；"
                        "分摊前先 LEFT JOIN 探孤儿"),
            "why": "分维度下钻时该业务规则不存在，本次会话与用户确认后确定",
            "source": "本次会话第 2 轮澄清"}},
]

st.set_page_config(page_title="Data Agent · Oversight Console", layout="wide",
                   page_icon="🧭")

if "lang" not in st.session_state:
    st.session_state.lang = "en"
col_title, col_lang = st.columns([6, 1])
with col_lang:
    st.session_state.lang = ("zh" if st.toggle("中文", value=st.session_state.lang == "zh")
                             else "en")
t = T[st.session_state.lang]

with col_title:
    st.title(t["title"])
st.caption(t["caption"])

tab_verify, tab_approve, tab_inspect = st.tabs([t["tab_v"], t["tab_a"], t["tab_i"]])

# ---------------------------------------------------------------- ① Verify
with tab_verify:
    st.subheader(t["v_head"])
    st.markdown(t["v_question"])
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
    st.markdown(t["v_calibers"])
    c1, c2, c3 = st.columns(3)
    with c1:
        st.info(t["c_gmv"])
    with c2:
        st.info(t["c_time"])
    with c3:
        st.info(t["c_rate"])

    if "verify_state" not in st.session_state:
        st.session_state.verify_state = None
    col_ok, col_no = st.columns(2)
    if col_ok.button(t["v_ok"], type="primary"):
        st.session_state.verify_state = "approved"
    if col_no.button(t["v_no"]):
        st.session_state.verify_state = "rejected"

    if st.session_state.verify_state == "approved":
        st.success(t["v_ok_msg"])
        st.table({"Check": t["chk"], "Result": t["chk_res"]}
                 if st.session_state.lang == "en"
                 else {"检查项": t["chk"], "结果": t["chk_res"]})
        st.markdown(t["v_answer"])
    elif st.session_state.verify_state == "rejected":
        st.warning(t["v_rej_msg"])

# ---------------------------------------------------------------- ② Approve
with tab_approve:
    st.subheader(t["a_head"])
    st.caption(t["a_caption"])
    decisions = {}
    for p in PROPOSALS:
        c = p[st.session_state.lang]
        with st.container(border=True):
            st.markdown(f"**Proposal {p['en']['title'].split(' ·')[0]} · {c['title']}**"
                        if st.session_state.lang == "en"
                        else f"**提案 {p['zh']['title'].split(' ·')[0]} · {c['title']}**")
            st.markdown(f"- **{t['p_what']}**: {c['what']}\n- **{t['p_prev']}**: "
                        f"{c['preview']}\n- **{t['p_why']}**: {c['why']}\n"
                        f"- **{t['p_src']}**: {c['source']}")
            decision = st.radio("Decision", [t["d_ok"], t["d_edit"], t["d_rej"]],
                                key=f"d{p['en']['title']}", horizontal=True,
                                label_visibility="collapsed")
            if decision == t["d_edit"]:
                decisions[p["en"]["title"]] = {
                    "decision": "edit",
                    "edited": st.text_area(t["d_edited"], key=f"e{p['en']['title']}",
                                          height=68)}
            else:
                decisions[p["en"]["title"]] = {
                    "decision": "approve" if decision == t["d_ok"] else "reject"}
    if st.button(t["submit"], type="primary"):
        record = {"submitted_at": datetime.now().isoformat(timespec="seconds"),
                  "language": st.session_state.lang, "decisions": decisions}
        DECISIONS.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        st.success(t["a_ok_msg"].format(
            n1=sum(1 for d in decisions.values() if d["decision"] == "approve"),
            n2=sum(1 for d in decisions.values() if d["decision"] == "edit"),
            n3=sum(1 for d in decisions.values() if d["decision"] == "reject")))

# ---------------------------------------------------------------- ③ Inspect
with tab_inspect:
    st.subheader(t["i_head"])
    st.caption(t["i_caption"])
    if st.button(t["i_btn"]):
        try:
            out = subprocess.run(
                [sys.executable, str(REPO / "skills" / "database-query" / "scripts"
                                     / "list_memories.py")],
                capture_output=True, text=True, encoding="utf-8", timeout=60,
                env={**os.environ, "PYTHONUTF8": "1"},
            )
            st.session_state.memory_out = out.stdout if out.returncode == 0 else out.stderr
        except subprocess.TimeoutExpired:
            st.session_state.memory_out = t["i_timeout"]
    if st.session_state.get("memory_out"):
        st.code(st.session_state.memory_out, language=None)
    else:
        st.info(t["i_hint"])
