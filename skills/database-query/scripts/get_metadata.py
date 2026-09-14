"""get_metadata.py —— 元数据查询：表清单 / 字段 / 索引 / 近似行数

用法：
  python get_metadata.py                 # 全部表
  python get_metadata.py --table orders  # 单表
  python get_metadata.py --brief         # 表索引（表名/注释/近似行数），overview.md 种子材料

数据来源：information_schema.TABLES / COLUMNS / STATISTICS。
注意：TABLES.TABLE_ROWS 是 InnoDB 估算值（真实行数用 SELECT COUNT(*)），输出字段名因此叫 approx_rows。
"""

import argparse
import sys
import time
from pathlib import Path

import pymysql

_REPO = Path(__file__).resolve().parents[3]  # scripts/ → database-query/ → skills/ → 仓库根
sys.path.insert(0, str(_REPO))
from _lib import database_client as db  # noqa: E402

TABLES_SQL = (
    "SELECT TABLE_NAME, TABLE_COMMENT, ENGINE, TABLE_ROWS "
    "FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME"
)
COLUMNS_SQL = (
    "SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_KEY, COLUMN_DEFAULT, COLUMN_COMMENT "
    "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
    "ORDER BY ORDINAL_POSITION"
)
INDEXES_SQL = (
    "SELECT INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME "
    "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
    "ORDER BY INDEX_NAME, SEQ_IN_INDEX"
)


def fetch_all(conn, sql: str, params):
    """执行参数化查询并抓取全部行（元数据量小，无截断问题）。"""
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def build_indexes(rows) -> list:
    """把 STATISTICS 的行（索引名/序号/列名）合并成结构化索引。"""
    grouped: dict = {}
    for r in rows:
        entry = grouped.setdefault(
            r["INDEX_NAME"],
            {"name": r["INDEX_NAME"], "unique": not bool(r["NON_UNIQUE"]), "columns": []},
        )
        entry["columns"].append(r["COLUMN_NAME"])
    return list(grouped.values())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--table", help="只看单张表")
    ap.add_argument("--brief", action="store_true", help="只输出表索引（表名/注释/近似行数）")
    args = ap.parse_args()

    try:
        dbcfg = db.load_db_config()
        conn = db.connect()
    except db.ConfigError as exc:
        db.emit_error("CONFIG_ERROR", str(exc), suggestion="检查 config/connection.ini（模板见 connection.ini.example）。")
        return 1
    except db.ConnectionFailure as exc:
        db.emit_error("CONNECTION_ERROR", str(exc), suggestion="检查 MySQL 服务（MYSQL95）是否运行。")
        return 1

    t0 = time.time()
    try:
        tables = fetch_all(conn, TABLES_SQL, (dbcfg["database"],))
        if args.table:
            tables = [t for t in tables if t["TABLE_NAME"] == args.table]
            if not tables:
                db.emit_error("FIELD_ERROR", f"表 {args.table} 不存在。",
                              suggestion="不带 --table 跑一次 get_metadata.py 查看全部表名。")
                return 1
        out_tables = []
        for t in tables:
            name = t["TABLE_NAME"]
            cols = fetch_all(conn, COLUMNS_SQL, (dbcfg["database"], name))
            idxs = build_indexes(fetch_all(conn, INDEXES_SQL, (dbcfg["database"], name)))
            out_tables.append({
                "table_name": name,
                "comment": t["TABLE_COMMENT"] or "",
                "engine": t["ENGINE"],
                "approx_rows": int(t["TABLE_ROWS"] or 0),
                "columns": [{
                    "name": c["COLUMN_NAME"],
                    "type": c["COLUMN_TYPE"],
                    "nullable": (c["IS_NULLABLE"] or "NO").upper() == "YES",
                    "key": c["COLUMN_KEY"] or "",
                    "default": db.to_jsonable(c["COLUMN_DEFAULT"]),
                    "comment": c["COLUMN_COMMENT"] or "",
                } for c in cols],
                "indexes": idxs,
            })
        if args.brief:
            db.emit_json({
                "status": "ok", "database": dbcfg["database"],
                "tables": [{
                    "table_name": x["table_name"],
                    "comment": x["comment"],
                    "approx_rows": x["approx_rows"],
                    "column_count": len(x["columns"]),
                } for x in out_tables],
            })
        else:
            db.emit_json({
                "status": "ok", "database": dbcfg["database"], "tables": out_tables,
                "elapsed_ms": round((time.time() - t0) * 1000, 1),
            })
        return 0
    except pymysql.MySQLError as exc:
        code = exc.args[0] if exc.args else None
        info = db.classify_error(code, str(exc))
        db.emit_error(info["error_type"], f"[{code}] {exc}", suggestion=info["suggestion"])
        return 1
    except Exception as exc:
        db.emit_error("UNKNOWN_ERROR", f"内部错误：{exc}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
