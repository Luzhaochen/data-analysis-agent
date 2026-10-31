"""list_memories.py —— 记忆浏览工具（透明性）：查看知识库里存了什么、因何而存。

输出分四节：
  1. 表知识：memory/tables/ 各文档 + overview.md 中的使用频次
  2. SQL 片段：memory/sql_snippets/ 各片段的一行摘要（文件头「场景」行）
  3. 待审阅草稿：runs/drafts/ 中尚未落库的新表文档
  4. 语法规则：memory/sql_syntax.md 是否存在

只读、确定性：不调模型、不连数据库；目录缺失时对应节显示为空。
用途：Step 6 提案前核对现状、会话中回答「库里存了什么」、报告知识库状态。
"""

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]  # scripts/ → database-query/ → skills/ → 仓库根
MEMORY = _REPO / "memory"


def _section(title: str) -> None:
    print(f"\n[{title}]")


def _table_knowledge() -> None:
    tables_dir = MEMORY / "tables"
    overview = tables_dir / "overview.md"
    counts = {}
    if overview.exists():
        try:
            for line in overview.read_text(encoding="utf-8").splitlines():
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if not cells or not cells[0].isalpha():
                    continue
                name = cells[0].lower()
                count = ""
                for cell in reversed(cells[1:]):
                    if cell.isdigit():
                        count = cell
                        break
                counts[name] = count
        except OSError:
            pass
    if not tables_dir.exists():
        return
    for p in sorted(tables_dir.glob("*.md")):
        name = p.stem.lower()
        if name == "overview" or name.startswith("模板"):
            continue
        doc = "doc: yes" if p.exists() else "doc: no"
        count = counts.get(name, "—")
        print(f"  {p.stem}　{doc}　usage: {count}")


def _snippets() -> None:
    snip_dir = MEMORY / "sql_snippets"
    if not snip_dir.exists():
        return
    for p in sorted(snip_dir.glob("*.sql")):
        scene = ""
        try:
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines()[:12]:
                if "场景：" in line:
                    scene = line.split("场景：", 1)[1].strip()
                    break
        except OSError:
            pass
        print(f"  {p.name}: {scene or '(no scene summary)'}")


def _drafts() -> None:
    drafts_dir = _REPO / "runs" / "drafts"
    if not drafts_dir.exists():
        return
    files = sorted(drafts_dir.glob("*.md"))
    if not files:
        print("  (no drafts awaiting review)")
        return
    for p in files:
        print(f"  {p.name}　status: draft, awaiting user review")


def _syntax() -> None:
    syntax = MEMORY / "sql_syntax.md"
    if syntax.exists():
        try:
            lines = syntax.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        print(f"  sql_syntax.md　present ({len(lines)} lines, general SQL rules)")
    else:
        print("  sql_syntax.md　missing")


def main() -> int:
    _section("Table knowledge (memory/tables/)")
    _table_knowledge()
    _section("SQL snippets (memory/sql_snippets/)")
    _snippets()
    _section("Drafts awaiting review (runs/drafts/)")
    _drafts()
    _section("Syntax rules")
    _syntax()
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
