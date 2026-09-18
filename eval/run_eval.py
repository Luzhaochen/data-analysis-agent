"""run_eval.py —— 回归评测：知识覆盖检查 + SQL 规则检查（确定性 grader，不调 LLM）

用法：
  python eval/run_eval.py                # 跑全部用例
  python eval/run_eval.py --case <id>    # 单用例调试

三类校验（对应用例三种形态）：
1. SQL 类用例：知识覆盖（表在 overview 有行 + 详情文档存在；指标在表文档有口径定义）
   + SQL 规则（must_have 全部命中 / must_not_have 零命中）
   + EXPLAIN dry-run 语法验证（复用 execute_query.py --dry-run，不抓数据抓语法错）
2. clarify 用例：无 SQL 检查，报告「预期澄清行为」。
3. reject 用例：reference_sql 交给 execute_query.py 执行，断言被策略层拒绝
   （PERMISSION_ERROR）——验证只读防线真实生效。

设计原则（CS621 eval 经验迁移）：确定性 grader 优先；标准答案 SQL 来自已跑通的
测试（11 题迭代 / 冷启动 / 知识库片段），不用「agent 跑出来的结果」当答案。
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]  # eval/ → 仓库根
CASES_PATH = _REPO / "eval" / "cases.json"
OVERVIEW = _REPO / "memory" / "tables" / "overview.md"
TABLES_DIR = _REPO / "memory" / "tables"
PY = str(_REPO / ".venv" / "Scripts" / "python.exe")
EXECUTE = str(_REPO / "skills" / "database-query" / "scripts" / "execute_query.py")


def load_cases() -> list:
    try:
        data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"cases.json 读取失败：{exc}")
        sys.exit(1)
    cases = data.get("cases", [])
    if not isinstance(cases, list) or not cases:
        print("cases.json 无有效用例")
        sys.exit(1)
    return cases


def load_overview_tables() -> set:
    names = set()
    if not OVERVIEW.exists():
        return names
    for line in OVERVIEW.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*([A-Za-z_][A-Za-z0-9_]*)\s*\|", line)
        if m:
            names.add(m.group(1).lower())
    return names


def check_knowledge(case: dict) -> list:
    """知识覆盖：表在 overview 有行 + 详情文档存在；指标在相关表文档有口径定义。"""
    failures = []
    overview_tables = load_overview_tables()
    for t in case.get("expected_tables", []):
        if t.lower() not in overview_tables:
            failures.append(f"知识覆盖：overview.md 缺表 {t}")
        elif not (TABLES_DIR / f"{t}.md").exists():
            failures.append(f"知识覆盖：缺详情文档 memory/tables/{t}.md")
    metrics = case.get("expected_metrics", [])
    if metrics:
        blob = ""
        for t in case.get("expected_tables", []):
            p = TABLES_DIR / f"{t}.md"
            if p.exists():
                blob += p.read_text(encoding="utf-8", errors="replace")
        for m in metrics:
            if m not in blob:
                failures.append(f"知识覆盖：指标「{m}」在相关表文档中无口径定义")
    return failures


def check_patterns(case: dict) -> list:
    sql = (case.get("reference_sql") or "").lower()
    failures = []
    for p in case.get("sql_patterns", {}).get("must_have", []):
        if p.lower() not in sql:
            failures.append(f"SQL 规则：缺少必需模式「{p}」")
    for p in case.get("sql_patterns", {}).get("must_not_have", []):
        if p.lower() in sql:
            failures.append(f"SQL 规则：出现违禁模式「{p}」")
    return failures


def run_execute(sql: str, dry_run: bool) -> dict:
    cmd = [PY, EXECUTE, "--session", "eval-check", "--sql", sql]
    if dry_run:
        cmd.append("--dry-run")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "internal", "message": str(exc)}
    try:
        return json.loads(r.stdout.strip())
    except json.JSONDecodeError:
        return {"status": "internal", "message": f"execute_query 无合法 JSON 输出：{r.stdout[:200]}"}


def check_explain(case: dict) -> list:
    out = run_execute(case["reference_sql"], dry_run=True)
    if out.get("status") != "ok":
        return [f"EXPLAIN：{out.get('error_type', out.get('status'))} {out.get('message', '')}"]
    return []


def check_reject(case: dict) -> list:
    out = run_execute(case["reference_sql"], dry_run=False)
    if out.get("status") != "error" or out.get("error_type") != "PERMISSION_ERROR":
        return [f"写操作未被拒绝（实际 {out.get('status')}/{out.get('error_type')}）"]
    return []


def run_case(case: dict) -> dict:
    behavior = case.get("expected_behavior")
    failures = []
    if behavior == "clarify":
        pass  # 预期澄清：无 SQL 检查，正确行为是模型提问而非执行
    elif behavior == "reject":
        failures = check_reject(case)
    else:
        failures = check_knowledge(case) + check_patterns(case) + check_explain(case)
    return {"id": case["id"], "question": case["question"],
            "behavior": behavior or "sql", "failures": failures}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--case", help="只跑指定用例（调试用）")
    args = ap.parse_args()

    cases = load_cases()
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            print(f"未找到用例 {args.case}")
            return 1

    results = [run_case(c) for c in cases]
    passed = [r for r in results if not r["failures"]]
    failed = [r for r in results if r["failures"]]
    clarify_n = sum(1 for r in results if r["behavior"] == "clarify")
    reject_n = sum(1 for r in results if r["behavior"] == "reject")

    print("=" * 60)
    print(f"回归评测：{len(passed)}/{len(results)} 通过"
          f"（clarify {clarify_n}、reject 防线 {reject_n}）")
    print("=" * 60)
    for r in failed:
        print(f"\n✗ {r['id']} —— {r['question']}")
        for f in r["failures"]:
            print(f"    - {f}")
    if not failed:
        print("全部通过。")
    return 0 if not failed else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
