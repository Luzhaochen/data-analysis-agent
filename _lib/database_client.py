"""共享数据库客户端（Phase 1 · 确定性执行层）

职责（只做输入→输出，不含任何业务判断）：
1. 读取 config/connection.ini（连接信息）与 config/analysis.json（行数上限/超时等约定）
2. 统一建连：pymysql + utf8mb4 + 读写超时 + 可选只读事务兜底
3. 统一结果输出：JSON / CSV / 表格，三种格式由调用方参数控制
4. 统一异常包装：任何错误都输出结构化 JSON，绝不让 traceback 裸奔给模型看

错误分类（框架 Step 4）——四类可重试 + 三类基础设施错误：
- PARTITION_ERROR  日期/分区字段不存在或格式错 → 检查时间过滤写法、确认字段类型
- FIELD_ERROR      字段名/类型/表名错         → 调 get_metadata.py 拿真实 schema
- SYNTAX_ERROR     语法错                     → 对照 memory/sql_syntax.md
- PERMISSION_ERROR 权限/只读策略拒绝          → 不重试，明确告知
- CONFIG_ERROR     配置缺失/损坏              → 修复配置（不重试）
- CONNECTION_ERROR 连不上/连接中断            → 检查服务与网络（不重试）
- TIMEOUT_ERROR    查询超时                    → 缩小范围/先聚合（可重试）

设计说明：
- 金额 Decimal → float（<1e12 时精度足够展示；精确计算请在 SQL 内完成）
- date/datetime → ISO 字符串；bytes → utf-8
- 只读兜底两层：data_agent 账号只有 SELECT 权限 + SET SESSION TRANSACTION READ ONLY
  （即使误配高权限账号，写操作也会被数据库拒绝，报错 1792）
"""

import configparser
import csv
import io
import json
import os
import sys
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import pymysql

# ---------------------------------------------------------------- 路径与配置

# 本文件位于 <repo>/_lib/；默认仓库根 = 上一级目录。
# Phase 6 安装到 ~/.claude/skills/ 后目录结构会变，届时用环境变量 DATA_AGENT_HOME 指定仓库根。
_REPO_ROOT = Path(os.environ.get("DATA_AGENT_HOME", str(Path(__file__).resolve().parents[1])))
CONFIG_DIR = _REPO_ROOT / "config"
RUNS_DIR = _REPO_ROOT / "runs"

# config/analysis.json 缺失时的默认约定（与 Phase 1 计划一致）
DEFAULT_ANALYSIS = {
    "default_row_limit": 1000,     # 未显式 LIMIT 时自动追加
    "hard_row_limit": 10000,       # 任何查询的行数硬上限（显式 LIMIT 超过也会被压回）
    "timeout_s": 30,               # 读写超时；同时作为 max_execution_time（服务端杀查询）
    "display_threshold_rows": 50,  # 结果 ≤ 此值表格展示，否则出 CSV（Phase 3 SKILL.md 使用）
    "enforce_readonly": True,      # 会话级只读事务兜底
    "retry_max": 3,                # Step 4 重试上限（计数逻辑在 SKILL.md 工作流）
}


class ConfigError(Exception):
    """配置错误：无法建连的根因，重试无意义。"""


class ConnectionFailure(Exception):
    """建连/认证失败：携带 MySQL 错误码。"""

    def __init__(self, code: Optional[int], message: str):
        super().__init__(message)
        self.code = code


def load_analysis_config() -> dict:
    """读取 config/analysis.json；文件缺失时用默认值（保证任何环境可运行）。"""
    cfg = dict(DEFAULT_ANALYSIS)
    path = CONFIG_DIR / "analysis.json"
    if path.exists():
        try:
            cfg.update(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError) as exc:
            raise ConfigError(f"config/analysis.json 解析失败：{exc}") from exc
    return cfg


def load_db_config() -> dict:
    """读取 config/connection.ini 的 [database] 段；缺失/缺项时给出可操作的报错。"""
    path = CONFIG_DIR / "connection.ini"
    if not path.exists():
        raise ConfigError(
            f"缺少 {path}：请复制 config/connection.ini.example 为 connection.ini，"
            "填入 data_agent 账号信息（见 mock_data/setup.sql.example）。"
        )
    parser = configparser.ConfigParser()
    try:
        parser.read(path, encoding="utf-8")
    except configparser.Error as exc:
        raise ConfigError(f"{path} 解析失败：{exc}") from exc
    if not parser.has_section("database"):
        raise ConfigError(f"{path} 缺少 [database] 段")
    sec = {k: (v or "").strip() for k, v in parser["database"].items()}
    missing = [k for k in ("host", "user", "password", "database") if not sec.get(k)]
    if missing:
        raise ConfigError(f"{path} 缺少配置项：{', '.join(missing)}")
    return {
        "host": sec["host"],
        "port": int(sec.get("port", 3306)),
        "user": sec["user"],
        "password": sec["password"],
        "database": sec["database"],
        "charset": sec.get("charset", "utf8mb4"),
    }


# ---------------------------------------------------------------- 建连

def connect(timeout_s: Optional[int] = None):
    """统一建连。

    - 读写超时：read_timeout = timeout_s + 5（留 5 秒让服务端先报超时错误码）
    - SET SESSION max_execution_time = timeout_s：服务端在超时处直接中断 SELECT，报错 3024
    - enforce_readonly 时 SET SESSION TRANSACTION READ ONLY：写操作报错 1792
    """
    analysis = load_analysis_config()
    timeout_s = timeout_s or int(analysis.get("timeout_s", 30))
    try:
        dbcfg = load_db_config()
    except ConfigError:
        raise
    try:
        conn = pymysql.connect(
            host=dbcfg["host"],
            port=dbcfg["port"],
            user=dbcfg["user"],
            password=dbcfg["password"],
            database=dbcfg["database"],
            charset=dbcfg["charset"],
            autocommit=True,
            connect_timeout=10,
            read_timeout=timeout_s + 5,
            write_timeout=timeout_s + 5,
            cursorclass=pymysql.cursors.DictCursor,
        )
    except pymysql.MySQLError as exc:
        code = exc.args[0] if exc.args else None
        if code == 1045:
            raise ConnectionFailure(code, "账号或密码错误（Access denied）：检查 connection.ini 与 data_agent 账号") from exc
        raise ConnectionFailure(code, f"无法连接数据库：{exc}") from exc
    try:
        with conn.cursor() as cur:
            cur.execute(f"SET SESSION max_execution_time = {int(timeout_s) * 1000}")
            if analysis.get("enforce_readonly", True):
                cur.execute("SET SESSION TRANSACTION READ ONLY")
    except pymysql.MySQLError as exc:
        conn.close()
        raise ConnectionFailure(exc.args[0] if exc.args else None, f"会话初始化失败：{exc}") from exc
    return conn


def fetch_rows(conn, sql: str, max_rows: int):
    """执行并抓取最多 max_rows 行（多抓 1 行用于探测截断）。返回 (columns, rows, truncated)。"""
    with conn.cursor() as cur:
        cur.execute(sql)
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(max_rows + 1)
    truncated = len(rows) > max_rows
    if truncated:
        rows = rows[:max_rows]
    return columns, rows, truncated


# ---------------------------------------------------------------- 序列化与输出

def to_jsonable(value: Any) -> Any:
    """转成 JSON 安全值（递归）。"""
    if isinstance(value, Decimal):
        return float(value)  # 金额展示足够；精确计算请放在 SQL 内
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


def to_display(value: Any) -> Any:
    """CSV/表格展示值：Decimal 保持字符串原样（不丢精度），日期 ISO。"""
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def emit_json(obj: dict) -> None:
    """输出 JSON；下游提前关闭管道（如 head）时静默降级，绝不让 traceback 裸奔。"""
    try:
        print(json.dumps(obj, ensure_ascii=False, default=str), flush=True)
    except OSError:
        try:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        except OSError:
            pass


def emit_success(columns, rows, **meta) -> None:
    """成功结果统一输出为 JSON：{status, columns, rows, row_count, ...meta}。"""
    emit_json({
        "status": "ok",
        "columns": columns,
        "rows": [to_jsonable(r) for r in rows],
        "row_count": len(rows),
        **meta,
    })


def emit_error(error_type: str, message: str, *, suggestion: Optional[str] = None, **extra) -> None:
    """错误统一输出为结构化 JSON：{status:"error", error_type, message, suggestion?}。"""
    obj = {"status": "error", "error_type": error_type, "message": message}
    if suggestion:
        obj["suggestion"] = suggestion
    obj.update(extra)
    emit_json(obj)


def render_csv(columns, rows) -> str:
    """rows: list[dict]。纯 CSV 文本（表头 + 数据行）。"""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([to_display(row.get(c)) for c in columns])
    return buf.getvalue()


def _disp_width(text: str) -> int:
    """终端显示宽度：中文/全角算 2 列，保证表格对齐。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def render_table(columns, rows, max_cell: int = 40) -> str:
    """人读表格：中文按双宽对齐，单元格过长截断。"""

    def cut(s: str) -> str:
        out, w = [], 0
        for ch in s:
            cw = 2 if unicodedata.east_asian_width(ch) in "WF" else 1
            if w + cw > max_cell - 1:
                out.append("…")
                break
            out.append(ch)
            w += cw
        return "".join(out)

    def cell(value) -> str:
        s = str(to_display(value))
        return s if _disp_width(s) <= max_cell else cut(s)

    header = [cell(c) for c in columns]
    body = [[cell(r.get(c)) for c in columns] for r in rows]
    widths = [
        max(_disp_width(header[i]), *(_disp_width(row[i]) for row in body))
        for i in range(len(columns))
    ]

    def pad(s: str, w: int) -> str:
        return s + " " * (w - _disp_width(s))

    lines = [
        " | ".join(pad(h, w) for h, w in zip(header, widths)),
        "-+-".join("-" * w for w in widths),
    ]
    for row in body:
        lines.append(" | ".join(pad(v, w) for v, w in zip(row, widths)))
    return "\n".join(lines)


# ---------------------------------------------------------------- 错误分类

# MySQL 错误码 → 分类映射（dev.mysql.com 8.0 error reference）
#   1054 Unknown column             → FIELD_ERROR
#   1052 Column ambiguous           → FIELD_ERROR（加表前缀）
#   1146 Table doesn't exist        → FIELD_ERROR
#   1109 Unknown table              → FIELD_ERROR
#   1064 syntax error               → SYNTAX_ERROR
#   1055 ONLY_FULL_GROUP_BY         → SYNTAX_ERROR（聚合/非聚合列混用）
#   1111 invalid group function     → SYNTAX_ERROR
#   1242 标量子查询多行              → SYNTAX_ERROR
#   1065 empty query                → SYNTAX_ERROR
#   1292 值/类型转换错               → 按 message 细分（含 date/time → PARTITION_ERROR）
#   1526 分区值越界                  → PARTITION_ERROR
#   1142/1144/1145/1227 权限拒绝     → PERMISSION_ERROR（不重试）
#   1792 只读事务拒绝写              → PERMISSION_ERROR
#   2013 连接中断（during query）    → TIMEOUT_ERROR / 其他 → CONNECTION_ERROR
#   3024 max_execution_time 超时     → TIMEOUT_ERROR
#   注意：max_execution_time 只在行处理检查点计时，SLEEP() 不受限制（MySQL 文档）；
#   客户端 read_timeout 是第二道兜底（超时 +5s，报 2013）。
#   2003/2006 无法连接              → CONNECTION_ERROR


def classify_error(code: Optional[int], message: str, timeout_s: int = 30) -> dict:
    """MySQL 错误码 → {error_type, suggestion}（框架 Step 4 分类表）。

    调用方据此决定：FIELD/SYNTAX/PARTITION/TIMEOUT 可修正后重试；
    PERMISSION/CONFIG/CONNECTION 不重试。
    """
    msg = (message or "").lower()
    if code in (1054, 1052, 1146, 1109):
        return {"error_type": "FIELD_ERROR",
                "suggestion": "字段/表不存在或歧义：先调 get_metadata.py 拿真实 schema，再修正字段名与表前缀。"}
    if code in (1064, 1055, 1111, 1242, 1065):
        if code == 1055:
            sug = ("聚合查询混用非聚合列（ONLY_FULL_GROUP_BY）：SELECT/ORDER BY 中的列必须出现在 "
                   "GROUP BY 或聚合函数内，见 memory/sql_syntax.md 聚合规则。")
        elif code == 1242:
            sug = "标量子查询返回多行：子查询应返回 0/1 行（如取 MAX/MIN/聚合后使用），或改为 JOIN。"
        else:
            sug = "语法错误：对照 memory/sql_syntax.md 检查关键字、括号、别名与引号。"
        return {"error_type": "SYNTAX_ERROR", "suggestion": sug}
    if code in (1292, 1525):  # 1525：MySQL 9 中「Incorrect DATE value」的报错码（8.x 用 1292）
        if "date" in msg or "time" in msg:
            return {"error_type": "PARTITION_ERROR",
                    "suggestion": "时间字段的值格式错或类型不匹配：日期比较统一用 'YYYY-MM-DD' 字符串，"
                                  "先 get_metadata.py 确认字段类型，见 memory/sql_syntax.md 日期规则。"}
        return {"error_type": "FIELD_ERROR",
                "suggestion": "值/类型不匹配（非法值或截断）：确认字段类型与比较值一致。"}
    if code == 1526:
        return {"error_type": "PARTITION_ERROR",
                "suggestion": "分区值越界（Table has no partition for value）：检查分区字段与过滤条件。"}
    if code in (1142, 1144, 1145, 1227, 1792):
        return {"error_type": "PERMISSION_ERROR",
                "suggestion": "权限/只读策略拒绝，不重试：本环境账号为 SELECT-only；写操作请用 root 在 Workbench 手工执行。"}
    if code in (2013, 3024):
        if code == 3024 or "during query" in msg:
            return {"error_type": "TIMEOUT_ERROR",
                    "suggestion": f"查询超过 {timeout_s}s 被中断：缩小时间范围、先聚合再取明细；"
                                  "确需更长可调 config/analysis.json 的 timeout_s。"}
        return {"error_type": "CONNECTION_ERROR",
                "suggestion": "数据库连接中断：检查 MySQL 服务（MYSQL95）是否运行。"}
    if code in (2003, 2006):
        return {"error_type": "CONNECTION_ERROR",
                "suggestion": "无法连接数据库：检查服务 MYSQL95 与 config/connection.ini。"}
    return {"error_type": "UNKNOWN_ERROR",
            "suggestion": "未收录的错误码：把 message 与 memory/sql_syntax.md 对照检查，"
                          "并把该错误码补进 _lib/database_client.py 顶部的映射表。"}


# ---------------------------------------------------------------- 运行留痕

def append_retry_log(session_id: str, entry: dict) -> Path:
    """追加一次执行尝试到 runs/<session_id>/retry_log.json（Step 4 证据留痕）。

    每次尝试都记录（成功或失败）；「修正」体现在下一条记录的 sql 变化上。
    attempt 序号按已有记录数自动递增；日志损坏时重来，不阻塞查询。
    """
    path = RUNS_DIR / session_id / "retry_log.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    log = []
    if path.exists():
        try:
            log = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log = []
    if not isinstance(log, list):
        log = []
    entry["attempt"] = sum(1 for e in log if isinstance(e, dict)) + 1
    log.append(entry)
    path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
