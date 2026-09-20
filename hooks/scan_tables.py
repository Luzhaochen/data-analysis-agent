"""scan_tables.py —— 扫描团队空间发现新表（自进化途径②：团队空间扫描，可接调度器定时触发）

用法：
  python hooks/scan_tables.py [--team-dir mock_data/team_space]

职责（确定性，不调 LLM）：
1. 扫描团队空间 *.sql 文件，提取 CREATE TABLE 的表名
2. 过滤已处理（runs/scan_state.json）与已建档（memory/tables/overview.md）
3. 每张新表查 information_schema：
   - 已上线 → 复用 doc_table 逻辑生成建档草稿到 runs/drafts/<表>.md，记入 state
   - 未上线 → 标记 pending_online（业务方先丢 DDL 后建表的时序，下次扫描继续等）
4. 输出 JSON 汇总 + next_steps

设计要点：
- 团队空间 DDL 只是「新表信号」；schema 事实源始终是数据库 information_schema
- 幂等：state 记录已处理表名，重复扫描零副作用（可接调度器反复运行）
- 落库 memory/tables/ 与更新 overview.md 是语义判断，由主 Agent 审阅草稿后完成
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]  # hooks/ → 仓库根
sys.path.insert(0, str(_REPO))
from _lib import database_client as db  # noqa: E402

_SCRIPTS = _REPO / "skills" / "database-query" / "scripts"
sys.path.insert(0, str(_SCRIPTS))
import doc_table  # noqa: E402

CREATE_TABLE_RE = re.compile(
    r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`]?([A-Za-z_][A-Za-z0-9_]*)[`]?",
    re.IGNORECASE,
)


def extract_table_names(sql_text: str) -> list:
    """从 DDL 文本提取 CREATE TABLE 的表名（可多个）。"""
    return CREATE_TABLE_RE.findall(sql_text)


def load_state(path: Path) -> dict:
    """读取幂等状态文件；缺失/损坏时从头开始（宁可重扫，不漏新表）。"""
    if not path.exists():
        return {"processed": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"processed": {}}
    if not isinstance(state.get("processed"), dict):
        state["processed"] = {}
    return state


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_documented_tables(overview: Path) -> set:
    """解析 overview.md 表格第一列（已建档表名集合）；文件缺失返回空集。"""
    names = set()
    if not overview.exists():
        return names
    try:
        for line in overview.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\|\s*([A-Za-z_][A-Za-z0-9_]*)\s*\|", line)
            if m:
                names.add(m.group(1).lower())
    except OSError:
        pass
    return names


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--team-dir", default=None, help="团队空间目录（默认 mock_data/team_space）")
    args = ap.parse_args()

    team_dir = Path(args.team_dir) if args.team_dir else _REPO / "mock_data" / "team_space"
    state_path = db.RUNS_DIR / "scan_state.json"
    overview = _REPO / "memory" / "tables" / "overview.md"

    # 1. 扫团队空间提取表名
    if not team_dir.exists():
        db.emit_error("CONFIG_ERROR", f"团队空间目录不存在：{team_dir}",
                      suggestion="检查 team_space 目录（说明见 mock_data/team_space/README.md）。")
        return 1
    found = {}
    for f in sorted(team_dir.glob("*.sql")):
        try:
            names = extract_table_names(f.read_text(encoding="utf-8"))
        except OSError:
            continue
        for n in names:
            found.setdefault(n, f.name)

    # 2. 过滤已处理（state）/ 已建档（overview）
    state = load_state(state_path)
    documented = load_documented_tables(overview)
    new_tables = [n for n in found if n not in state["processed"] and n.lower() not in documented]

    # 3. 建连（data_agent 只读账号，仅查 information_schema）
    try:
        dbcfg = db.load_db_config()
        conn = db.connect()
    except db.ConfigError as exc:
        db.emit_error("CONFIG_ERROR", str(exc), suggestion="检查 config/connection.ini。")
        return 1
    except db.ConnectionFailure as exc:
        db.emit_error("CONNECTION_ERROR", str(exc), suggestion="检查 MySQL 服务（MYSQL95）是否运行。")
        return 1

    # 4. 每张新表：查库 → 建档草稿 / 标记等待上线
    drafted, pending = [], []
    try:
        for name in new_tables:
            table = doc_table.fetch_table(conn, dbcfg["database"], name)
            if table is None:
                pending.append(name)
                continue
            draft_path = db.RUNS_DIR / "drafts" / f"{name}.md"
            draft_path.parent.mkdir(parents=True, exist_ok=True)
            draft_path.write_text(doc_table.render_draft(table), encoding="utf-8")
            state["processed"][name] = {
                "first_seen": datetime.now().isoformat(timespec="seconds"),
                "draft": str(draft_path),
                "source_file": found[name],
            }
            drafted.append(name)
    finally:
        conn.close()
    save_state(state_path, state)

    # 5. 汇总输出
    next_steps = []
    if drafted:
        next_steps.append(
            "审阅 runs/drafts/<表>.md 草稿并补充语义后，落库 memory/tables/ 并在 overview.md 增加条目。"
        )
    if pending:
        next_steps.append("pending_online 的表等业务方在数据库建表后，重新运行本脚本。")
    db.emit_json({
        "status": "ok",
        "scanned_tables": sorted(found),
        "new_tables": drafted,
        "pending_online": pending,
        "state_file": str(state_path),
        "next_steps": next_steps,
    })
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
