"""execute_query.py —— 框架 Step 4：SQL 执行入口（确定性，不含语义判断）

用法：
  python execute_query.py --sql "SELECT ..." [--format json|csv|table]
                          [--limit N] [--dry-run] [--session-id SID] [--file query.sql]
  SQL 也可从 stdin 传入（UTF-8）。

职责：
1. 基础检查：单语句 / 只读白名单（SELECT WITH EXPLAIN SHOW DESCRIBE DESC）/ 自动补 LIMIT
2. 执行（--dry-run 时用 EXPLAIN 验证语法与执行计划，不抓数据）
3. 结果输出 JSON/CSV/表格；错误一律结构化 JSON + 四分类 + 修复建议
4. 每次尝试（成功/失败）追加进 runs/<session_id>/retry_log.json

边界说明：
- 重试循环不在这里——「错误→修正」是语义判断，由 SKILL.md 工作流完成（上限 retry_max）
- 本脚本每次只做一次确定性执行 + 分类，retry_log 记录每次尝试供工作流计数与复盘
- PERMISSION_ERROR / CONFIG_ERROR / CONNECTION_ERROR 不重试（分类建议里已写明）
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import pymysql

_REPO = Path(__file__).resolve().parents[3]  # scripts/ → database-query/ → skills/ → 仓库根
sys.path.insert(0, str(_REPO))
from _lib import database_client as db  # noqa: E402

# 只读白名单（大小写不敏感；允许前置括号如 (SELECT ...) UNION ...）
READONLY_KEYWORDS = ("select", "with", "explain", "show", "describe", "desc")

# 已知写操作/会话控制关键字：策略层明确拒绝
DENY_KEYWORDS = (
    "insert", "update", "delete", "replace", "create", "alter", "drop",
    "truncate", "rename", "grant", "revoke", "set", "use", "call", "do",
    "begin", "start", "commit", "rollback", "lock", "unlock", "flush",
    "kill", "load", "import", "optimize", "analyze", "cache", "prepare",
    "execute", "deallocate", "xa", "purge", "reset", "shutdown",
)

# LIMIT 正则：LIMIT n / LIMIT n, m / LIMIT n OFFSET m
LIMIT_RE = re.compile(r"\blimit\s+(\d+)(?:\s*,\s*(\d+))?(?:\s+offset\s+(\d+))?", re.IGNORECASE)


def read_sql(args) -> str:
    """SQL 来源优先级：--file > --sql > stdin。"""
    if args.file:
        return Path(args.file).read_text(encoding="utf-8")
    if args.sql:
        return args.sql
    if not sys.stdin.isatty():
        return sys.stdin.read()
    db.emit_error("CONFIG_ERROR", "未提供 SQL：用 --sql / --file，或从 stdin 管道传入。")
    sys.exit(1)


def strip_sql(sql: str) -> str:
    return sql.strip().rstrip(";").strip()  # 去掉结尾分号（保持单语句语义）


def first_keyword(sql: str) -> str:
    """取首关键字（跳过前导空白/注释/括号，用于只读白名单检查）。"""
    s = sql.lstrip()
    while True:
        if s.startswith("--") or s.startswith("#"):
            nl = s.find("\n")
            s = s[nl + 1:] if nl >= 0 else ""
        elif s.startswith("/*"):
            end = s.find("*/", 2)
            s = s[end + 2:] if end >= 0 else ""
        else:
            break
        s = s.lstrip()
    while s.startswith("("):
        s = s[1:].lstrip()
    m = re.match(r"[A-Za-z]+", s)
    return (m.group(0) if m else "").lower()


def has_trailing_content_after_semicolon(sql: str) -> bool:
    """在引号/注释之外发现 ';' 且其后还有实质内容 → 多语句。"""
    i, n = 0, len(sql)
    state = None  # None | 'sq'（单引号） | 'dq'（双引号） | 'bt'（反引号）
    while i < n:
        ch = sql[i]
        if state == "sq":
            if ch == "\\":
                i += 2
                continue
            if ch == "'":
                state = None
        elif state == "dq":
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                state = None
        elif state == "bt":
            if ch == "`":
                state = None
        else:
            if ch == "'":
                state = "sq"
            elif ch == '"':
                state = "dq"
            elif ch == "`":
                state = "bt"
            elif ch == "#":
                while i < n and sql[i] != "\n":
                    i += 1
                continue
            elif ch == "-" and i + 1 < n and sql[i + 1] == "-" and (i + 2 >= n or sql[i + 2] in " \t\n"):
                while i < n and sql[i] != "\n":
                    i += 1
                continue
            elif ch == "/" and i + 1 < n and sql[i + 1] == "*":
                end = sql.find("*/", i + 2)
                i = n if end < 0 else end + 2
                continue
            elif ch == ";":
                if sql[i + 1:].strip():
                    return True
        i += 1
    return False


def find_limit(sql: str):
    return LIMIT_RE.search(sql)


def clamp_explicit_limit(sql: str, m, hard: int):
    """显式 LIMIT 超过硬上限时改写为 hard+1（多 1 行用于探测截断）；返回 (sql, clamped)。"""
    if m.group(2):  # LIMIT offset, count 形式：行数在第二组
        if int(m.group(2)) > hard:
            return sql[: m.start(2)] + str(hard + 1) + sql[m.end(2):], True
    elif int(m.group(1)) > hard:
        return sql[: m.start(1)] + str(hard + 1) + sql[m.end(1):], True
    return sql, False


def append_limit(sql: str, limit: int) -> str:
    """追加 LIMIT；若 SQL 以行注释结尾，插到注释之前（否则会被注释吞掉）。"""
    m = re.search(r"(--[^\n]*|#[^\n]*)$", sql)
    if m:
        return sql[: m.start()] + f" LIMIT {limit} " + sql[m.start():]
    return f"{sql} LIMIT {limit}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sql", help="SQL 文本")
    ap.add_argument("--file", help="从 UTF-8 文件读取 SQL")
    ap.add_argument("--format", choices=["json", "csv", "table"], default="json",
                    help="输出格式（默认 json；csv 时元信息走 stderr）")
    ap.add_argument("--limit", type=int, help="覆盖默认行数上限（仍受 hard_row_limit 约束）")
    ap.add_argument("--dry-run", action="store_true",
                    help="用 EXPLAIN 验证语法与执行计划，不执行查询")
    ap.add_argument("--session-id", help="会话 ID（用于 runs/<sid>/retry_log.json 留痕）")
    args = ap.parse_args()

    analysis = db.load_analysis_config()
    timeout_s = int(analysis.get("timeout_s", 30))
    hard = int(analysis.get("hard_row_limit", 10000))
    max_rows = min(args.limit or int(analysis.get("default_row_limit", 1000)), hard)
    session_id = args.session_id or f"manual-{datetime.now():%Y%m%d-%H%M%S}"

    sql = read_sql(args)
    sql = strip_sql(sql)
    if not sql:
        db.emit_error("SYNTAX_ERROR", "SQL 为空。")
        return 1

    # ---- 检查 1：单语句 ----
    if has_trailing_content_after_semicolon(sql):
        db.emit_error("SYNTAX_ERROR", "仅支持单条语句（发现分号后仍有内容）。",
                      suggestion="拆成多次调用，或去掉多余语句。")
        return 1

    # ---- 检查 2：只读策略 ----
    # 已知写关键字 → 策略层拒绝；未知关键字（如 SELEC 拼写错误）不拦截，交给数据库判语法：
    # 拼写错误得到准确的 1064 → SYNTAX_ERROR；真写操作由 data_agent 只读权限 +
    # READ ONLY 事务两层兜底拒绝（1142/1792）→ PERMISSION_ERROR。
    kw = first_keyword(sql)
    if kw in DENY_KEYWORDS:
        db.emit_error("PERMISSION_ERROR",
                      f"语句以 '{kw}' 开头，属写操作/会话控制，被策略拦截。",
                      suggestion="本环境只读；写操作（INSERT/UPDATE/DDL）请用 root 在 Workbench 手工执行。")
        return 1

    # ---- 检查 3：自动 LIMIT（仅 SELECT/WITH；EXPLAIN/SHOW/DESCRIBE 不需要）----
    # 探测截断的 +1 技巧：自动追加或钳制时，让 SQL 带 max_rows+1 的 LIMIT 配额，
    # fetchmany 多抓 1 行即可判断「还有更多行」。LIMIT 在 SQL 内时服务端先行截断，
    # 只有 SQL 侧多给 1 行配额，客户端才探得到。
    limit_clamped = False
    if kw in ("select", "with"):
        m = find_limit(sql)
        if m:
            sql, limit_clamped = clamp_explicit_limit(sql, m, hard)
        else:
            sql = append_limit(sql, max_rows + 1)

    # ---- 执行（含 EXPLAIN dry-run）----
    dry_run_note = None
    exec_sql = sql
    if args.dry_run and kw in ("select", "with"):
        exec_sql = f"EXPLAIN FORMAT=TRADITIONAL {sql}"
        dry_run_note = "EXPLAIN 验证通过：rows 为执行计划，非查询结果。"
    elif args.dry_run:
        dry_run_note = "SHOW/DESCRIBE/EXPLAIN 为元数据语句，dry-run 下按原样执行。"

    t0 = time.time()
    try:
        conn = db.connect(timeout_s)
    except db.ConfigError as exc:
        db.emit_error("CONFIG_ERROR", str(exc),
                      suggestion="检查 config/connection.ini（模板见 connection.ini.example）与 config/analysis.json。")
        return 1
    except db.ConnectionFailure as exc:
        db.emit_error("CONNECTION_ERROR", str(exc),
                      suggestion="检查 MySQL 服务（MYSQL95）是否运行、连接配置是否正确。")
        return 1

    try:
        columns, rows, truncated = db.fetch_rows(conn, exec_sql, max_rows)
        elapsed_ms = round((time.time() - t0) * 1000, 1)
        meta = {
            "truncated": truncated,
            "limit": max_rows,
            "limit_clamped": limit_clamped,
            "elapsed_ms": elapsed_ms,
            "dry_run": args.dry_run,
        }
        if dry_run_note:
            meta["note"] = dry_run_note
        if args.format == "json":
            db.emit_success(columns, rows, **meta)
        elif args.format == "csv":
            print(db.render_csv(columns, rows))
            print(json.dumps({"status": "ok", **meta}, ensure_ascii=False), file=sys.stderr)
        else:  # table
            print(db.render_table(columns, rows))
            print(f"row_count={len(rows)} truncated={truncated} limit={max_rows} elapsed_ms={elapsed_ms}")
        db.append_retry_log(session_id, {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "status": "ok",
            "dry_run": args.dry_run,
            "sql": sql,
            "row_count": len(rows),
            "truncated": truncated,
            "elapsed_ms": elapsed_ms,
        })
        return 0
    except pymysql.MySQLError as exc:
        code = exc.args[0] if exc.args else None
        message = exc.args[1] if len(exc.args) > 1 else str(exc)
        elapsed_ms = round((time.time() - t0) * 1000, 1)
        info = db.classify_error(code, str(message), timeout_s)
        db.emit_error(info["error_type"], f"[{code}] {message}",
                      suggestion=info["suggestion"], sql=sql, elapsed_ms=elapsed_ms)
        db.append_retry_log(session_id, {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "status": "error",
            "dry_run": args.dry_run,
            "sql": sql,
            "error_type": info["error_type"],
            "error_code": code,
            "message": message,
            "suggestion": info["suggestion"],
            "elapsed_ms": elapsed_ms,
        })
        return 1
    except Exception as exc:  # 兜底：任何意外错误也必须结构化，绝不让 traceback 裸奔
        db.emit_error("UNKNOWN_ERROR", f"执行器内部错误：{exc}",
                      suggestion="把错误信息记入 Phase 3 的失败日志，人工排查。")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
