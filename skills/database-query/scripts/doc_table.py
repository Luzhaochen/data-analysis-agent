"""doc_table.py —— 表文档建档（框架「完整文档建档 / 骨架兜底」）

用法：
  python doc_table.py --table orders [--out-dir runs/drafts]

流程：get_metadata 拿真实 schema → 按 memory/tables/ 单表模板生成草稿：
- 字段表自动填「名称/类型/含义（来自 schema COMMENT）」——确定性事实
- 业务含义与口径（粒度/指标口径/坑/关联键）留「待补充」——语义判断留给主 Agent
草稿写到 out-dir（默认 runs/drafts/），不直接进 memory——审阅后落库，
守住「语义判断由 Agent 做」的分工。

TODO(Phase 2)：模板落地 memory/tables/模板.md 后，本脚本改为读取模板文件渲染。
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pymysql

sys.path.insert(0, str(Path(__file__).parent))  # 与 get_metadata.py 同目录，复用其查询函数
import get_metadata  # noqa: E402

_REPO = Path(__file__).resolve().parents[3]  # scripts/ → database-query/ → skills/ → 仓库根
sys.path.insert(0, str(_REPO))
from _lib import database_client as db  # noqa: E402

DRAFT_TEMPLATE = """# {table}{comment}

> 草稿（doc_table.py 自动生成，{date}）——业务含义与口径需人工补充并审阅后，才能进入 memory/tables/。

- 用途：待补充
- 粒度：待补充（一行 = 一个待补充）
- 唯一键：{pk}
- 时间字段候选：{time_cols}（待确认哪个是时间过滤字段——见 memory/sql_syntax.md 分区过滤约定）
- 字段表：

| 字段 | 类型 | 含义 | 口径/取值 | 备注 |
|---|---|---|---|---|
{field_rows}
- 指标口径：待补充（GMV / 订单量 / 客单价等定义写在这里）
- 注意事项/坑：待补充（至少 3 条：这张表回答什么、怎么算、有什么坑）
- 常用过滤：待补充
- 关联键：待补充
"""


def render_draft(table: dict) -> str:
    """把 metadata 结果渲染成草稿 Markdown。只填确定性事实，语义留待补充。"""
    name = table["table_name"]
    pk_idx = next((i for i in table["indexes"] if i["name"] == "PRIMARY"), None)
    pk = "、".join(pk_idx["columns"]) if pk_idx else "待补充"
    time_cols = "、".join(
        f"{c['name']} ({c['type']})" for c in table["columns"]
        if c["type"].lower().startswith(("date", "datetime", "timestamp"))
    ) or "无（人工补充）"
    field_rows = "\n".join(
        "| {name} | {type} | {meaning} | 待补充 | {note} |".format(
            name=c["name"],
            type=c["type"],
            meaning=c["comment"] or "待补充",
            note={"PRI": "主键", "UNI": "唯一键", "MUL": "索引"}.get(c["key"], ""),
        )
        for c in table["columns"]
    )
    return DRAFT_TEMPLATE.format(
        table=name,
        comment=f"（{table['comment']}）" if table["comment"] else "（表注释待补充）",
        date=datetime.now().strftime("%Y-%m-%d"),
        pk=pk,
        time_cols=time_cols,
        field_rows=field_rows,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--table", required=True, help="要建档的表名")
    ap.add_argument("--out-dir", default=None, help="草稿输出目录（默认 runs/drafts）")
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

    try:
        tables = get_metadata.fetch_all(conn, get_metadata.TABLES_SQL, (dbcfg["database"],))
        tables = [t for t in tables if t["TABLE_NAME"] == args.table]
        if not tables:
            db.emit_error("FIELD_ERROR", f"表 {args.table} 不存在。",
                          suggestion="不带参数跑一次 get_metadata.py 查看全部表名。")
            return 1
        table = {
            "table_name": tables[0]["TABLE_NAME"],
            "comment": tables[0]["TABLE_COMMENT"] or "",
            "columns": [{
                "name": c["COLUMN_NAME"],
                "type": c["COLUMN_TYPE"],
                "key": c["COLUMN_KEY"] or "",
                "comment": c["COLUMN_COMMENT"] or "",
            } for c in get_metadata.fetch_all(
                conn, get_metadata.COLUMNS_SQL, (dbcfg["database"], args.table)
            )],
            "indexes": get_metadata.build_indexes(
                get_metadata.fetch_all(conn, get_metadata.INDEXES_SQL, (dbcfg["database"], args.table))
            ),
        }
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

    out_dir = Path(args.out_dir) if args.out_dir else db.RUNS_DIR / "drafts"
    out_dir.mkdir(parents=True, exist_ok=True)
    draft_path = out_dir / f"{args.table}.md"
    draft_path.write_text(render_draft(table), encoding="utf-8")

    auto_filled = sum(1 for c in table["columns"] if c["comment"])
    db.emit_json({
        "status": "ok",
        "table": args.table,
        "draft_path": str(draft_path),
        "auto_filled": {"fields": len(table["columns"]), "with_comment": auto_filled},
        "next_steps": [
            "补充用途/粒度/指标口径/坑/关联键（语义，人审）",
            "审阅通过后移入 memory/tables/（由主 Agent 落库，Phase 2）",
        ],
    })
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
