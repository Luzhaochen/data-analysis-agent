"""session_evolution.py —— 自进化钩子（专业人士指导的途径①：会话结束触发知识库更新）

子命令：
  --enqueue  SessionEnd 钩子用：把 session_id / transcript_path 追加进待处理队列。
             毫秒级完成，适配 SessionEnd 的 1.5 秒共享预算；重活留给 --process。
  --process  SessionStart 钩子用：处理队列（使用计数 / 草稿建档 / 幂等），
             并把进化摘要写到 stdout——纯文本会作为上下文注入新会话。

设计（Phase 4 队列化方案）：
- 散场（SessionEnd）只入队，开场（SessionStart）做重活——绕开 SessionEnd 的 1.5s 预算
- 幂等两层：入队去重（同 session_id 只入队一次）+ 处理去重（state 记录已处理）
- 只做确定性操作，不调 LLM、不调 claude CLI（防递归）
- transcript JSONL 是内部格式，解析必须容错（格式变化时宁可少计数，不可崩钩子）
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]  # hooks/ → 仓库根
RUNS_DIR = _REPO / "runs"
QUEUE_PATH = RUNS_DIR / "evolution_queue.jsonl"
STATE_PATH = RUNS_DIR / "evolution_state.json"
OVERVIEW_PATH = _REPO / "memory" / "tables" / "overview.md"


def read_stdin() -> dict:
    """读 Claude Code 递来的 JSON 信；坏信返回空 dict（钩子绝不因协议问题崩溃）。"""
    try:
        return json.loads(sys.stdin.read().strip())
    except (json.JSONDecodeError, OSError):
        return {}


# ---------------------------------------------------------------- enqueue（SessionEnd）

def cmd_enqueue() -> int:
    info = read_stdin()
    session_id = info.get("session_id")
    transcript_path = info.get("transcript_path")
    if not session_id or not transcript_path:
        return 1

    entry = {
        "session_id": session_id,
        "transcript_path": transcript_path,
        "enqueued_at": datetime.now().isoformat(timespec="seconds"),
    }
    # 幂等：同一会话重复入队只保留一条（先读旧队列查重）
    if QUEUE_PATH.exists():
        try:
            for line in QUEUE_PATH.read_text(encoding="utf-8").splitlines():
                try:
                    if json.loads(line).get("session_id") == session_id:
                        return 0
                except json.JSONDecodeError:
                    continue
        except OSError:
            pass

    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with QUEUE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return 0


# ---------------------------------------------------------------- process（SessionStart）

LOG = RUNS_DIR / "hook.log"


def log(msg: str) -> None:
    """钩子的 stdout 没人看，出错信息写日志文件。"""
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}\n")
    except OSError:
        pass


def load_table_names() -> set:
    """从 overview.md 提取全部表名（含留白表——它们也参与使用计数）。"""
    names = set()
    if not OVERVIEW_PATH.exists():
        return names
    try:
        for line in OVERVIEW_PATH.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\|\s*([A-Za-z_][A-Za-z0-9_]*)\s*\|", line)
            if m:
                names.add(m.group(1).lower())
    except OSError:
        pass
    return names


FROM_JOIN_RE = re.compile(
    r"\b(?:from|join)\s+[`]?([a-z_][a-z0-9_]*)[`]?", re.IGNORECASE
)


def count_tables_in_transcript(transcript_path: str, table_names: set) -> set:
    """扫逐字稿（JSONL）中 SQL 的 FROM/JOIN 子句，命中表名才算「本次会话用到」。

    为什么只看 FROM/JOIN：逐字稿里包含模型读知识库时的文件全文——overview.md 的
    表格索引里列着所有表名，若按「出现即使用」计数，读一次 overview 就把 9 张表
    全算上（实测踩过）。FROM/JOIN 只出现在真实 SQL 与片段里，语义才是「被查询」。

    transcript 是内部格式，官方不承诺稳定——解析必须容错：文件缺失/坏行一律跳过，
    宁可少计数，不可崩钩子。
    """
    used = set()
    try:
        text = Path(transcript_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return used
    for m in FROM_JOIN_RE.finditer(text):
        t = m.group(1).lower()
        if t in table_names:
            used.add(t)
    return used


def increment_overview_counts(used: set) -> list:
    """overview.md 表格「使用频次」列对用到过的表 +1（每会话每表）。返回被加的表。"""
    bumped = []
    if not OVERVIEW_PATH.exists():
        return bumped
    try:
        lines = OVERVIEW_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return bumped
    out = []
    for line in lines:
        m = re.match(r"^\|\s*([A-Za-z_][A-Za-z0-9_]*)\s*\|", line)
        if m and m.group(1).lower() in used:
            count_m = re.search(r"\|\s*(\d+)\s*\|$", line)
            if count_m:
                line = re.sub(r"\|\s*\d+\s*\|$", f"| {int(count_m.group(1)) + 1} |", line)
            out.append(line)
            bumped.append(m.group(1).lower())
        else:
            out.append(line)
    try:
        OVERVIEW_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
    except OSError:
        pass
    return bumped


def build_drafts(used: set) -> list:
    """出现过的表在 memory/tables/ 无详情文档 → 子进程调 doc_table.py 生成草稿。

    草稿只进 runs/drafts/，语义补充与落库是主 Agent 的活（人工闸门）。
    """
    drafted = []
    tables_dir = _REPO / "memory" / "tables"
    for t in sorted(used):
        if (tables_dir / f"{t}.md").exists():
            continue
        try:
            subprocess.run(
                [str(_REPO / ".venv" / "Scripts" / "python.exe"),
                 str(_REPO / "skills" / "database-query" / "scripts" / "doc_table.py"),
                 "--table", t],
                capture_output=True, timeout=120, check=False,
            )
            drafted.append(t)
        except (OSError, subprocess.TimeoutExpired):
            log(f"doc_table 建档失败：{t}")
    return drafted


def load_state() -> dict:
    """幂等状态：processed = 已处理过的 session_id 列表。缺失/损坏时从空开始。"""
    if not STATE_PATH.exists():
        return {"processed": []}
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"processed": []}
    if not isinstance(state.get("processed"), list):
        state["processed"] = []
    return state


def cmd_process() -> int:
    """消费队列：计数 → 建档 → 幂等记录 → stdout 输出进化摘要（注入新会话上下文）。"""
    if not QUEUE_PATH.exists():
        return 0
    try:
        entries = []
        for line in QUEUE_PATH.read_text(encoding="utf-8").splitlines():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return 0

    state = load_state()
    processed = set(state["processed"])
    pending = [e for e in entries if e.get("session_id") not in processed]

    table_names = load_table_names()
    bumped_all, drafted_all = set(), []
    for entry in pending:
        used = count_tables_in_transcript(entry.get("transcript_path", ""), table_names)
        if not used:
            continue
        bumped_all.update(increment_overview_counts(used))
        drafted_all += build_drafts(used)
        processed.add(entry["session_id"])

    # 幂等落账：state 记录 + 队列清空（已处理的移除，未处理的原样保留）
    state["processed"] = sorted(processed)
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        QUEUE_PATH.unlink()
    except OSError:
        log("state/queue 写入失败")

    # 进化摘要：stdout 纯文本在 SessionStart 时作为上下文注入新会话
    if bumped_all or drafted_all:
        parts = []
        if bumped_all:
            parts.append(f"使用计数 +1：{', '.join(sorted(bumped_all))}")
        if drafted_all:
            parts.append(f"新表草稿待审阅：{', '.join(drafted_all)}（runs/drafts/）")
        print(f"[自进化] 上次会话知识库更新：{'；'.join(parts)}。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--enqueue", action="store_true", help="SessionEnd 用：入队")
    ap.add_argument("--process", action="store_true", help="SessionStart 用：处理队列")
    args = ap.parse_args()
    if args.enqueue:
        return cmd_enqueue()
    if args.process:
        return cmd_process()
    return 1


if __name__ == "__main__":
    sys.exit(main())
