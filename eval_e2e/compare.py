"""compare.py —— E2E 第 3 步：结果比对器（candidate_sql 现场重执行 vs golden）

用法：
  .venv/Scripts/python eval_e2e/compare.py --run eval_e2e/results/001-q2-gmv/20260920-182041
  .venv/Scripts/python eval_e2e/compare.py --case 001-q2-gmv   # 自动挑该用例最近一次运行

本步的核心方法论（每条都是数据质量思维，面试可讲）：
1. 不信 Agent 自报的结果——candidate_sql 由评测方自己重新执行，结果来自独立
   执行而不是来自转录（防止"Agent 说它对"的自证循环）；
2. 不比 SQL 字符串，比结果集——两条写法不同但语义等价的 SQL 应该同分；
3. 归一化是比对的命根子：金额带 eps 容差（一分钱）、计数精确相等、
   日期统一 ISO 字符串、列名不参与比对（按数值集合/日期键匹配），
   避免口径外的误判——Agent 起别名叫 cnt 还是 total_cnt 不影响判分；
4. 结果被 LIMIT 截断时拒绝判分——没有完整证据就不下结论（宁可 unknown，
   不可误判）。
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from driver import parse_events  # 复用第 1 步的事件解析（同一个证据来源，解析器只有一份）

_REPO = Path(__file__).resolve().parents[1]
_PY = sys.executable
_EXECUTE = _REPO / "skills" / "database-query" / "scripts" / "execute_query.py"
_PRIVATE_DIR = Path(os.environ.get(
    "EVAL_PRIVATE_DIR",
    str(_REPO.parent / "data-analysis-agent-eval-private"),
))
_GOLDEN_PATH = _PRIVATE_DIR / "golden_results.json"

MONEY_EPS = 0.01  # 金额容差：一分钱


def run_sql(sql: str) -> dict:
    """独立重执行 candidate_sql，返回 {status, rows, truncated}。"""
    proc = subprocess.run(
        [_PY, str(_EXECUTE), "--session", "eval-compare", "--sql", sql],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
    )
    out = json.loads(proc.stdout.strip())
    if out.get("status") != "ok":
        return {"status": "error", "error": f"{out.get('error_type')} {out.get('message')}",
                "rows": [], "truncated": False}
    return {"status": "ok", "rows": out["rows"],
            "truncated": out.get("truncated", False)}


def is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_date_like(v) -> bool:
    """日期归一化判断：ISO 字符串（execute_query 已把 date 转成 'YYYY-MM-DD'）。"""
    return isinstance(v, str) and len(v) >= 10 and v[4] == "-" and v[7] == "-"


def normalize_numbers(row: dict) -> list:
    """抽出一行的全部数值（列名不参与比对——见模块 docstring 第 3 条）。"""
    return [float(v) for v in row.values() if is_number(v)]


def compare_numbers(golden_nums: list, actual_nums: list, eps: float) -> list:
    """数值集合比对：数量必须一致；排序后逐对比较——计数精确、金额带容差。"""
    failures = []
    if len(golden_nums) != len(actual_nums):
        failures.append(f"数值个数不一致：golden {len(golden_nums)} 个 vs 实际 {len(actual_nums)} 个")
        return failures
    for g, a in zip(sorted(golden_nums), sorted(actual_nums)):
        if abs(g - round(g)) < 1e-9 and abs(a - round(a)) < 1e-9:
            # 两个都是整数形态 → 计数类，精确相等
            if int(g) != int(a):
                failures.append(f"计数不一致：golden {int(g)} vs 实际 {int(a)}")
        elif abs(g - a) > eps:
            failures.append(f"数值超容差：golden {g} vs 实际 {a}（eps={eps}）")
    return failures


def compare_rows(golden_rows: list, actual_rows: list) -> list:
    """按用例形态选择比对策略：
    - 1 行 golden → 标量题：整行数值集合比对；
    - 多行且首列是日期 → 表格题：按日期键匹配，逐行数值集合比对。
    """
    if not golden_rows:
        return ["golden 为空，无法比对"]
    if len(golden_rows) == 1:
        return compare_numbers(normalize_numbers(golden_rows[0]),
                               normalize_numbers(actual_rows[0]) if actual_rows else [],
                               MONEY_EPS)
    # 表格题：找 golden 的日期键列（第一个日期形态的列）
    date_key = next((k for k in golden_rows[0] if is_date_like(golden_rows[0][k])), None)
    if date_key is None:
        return ["golden 多行但找不到日期键列，比对器不支持该形态"]

    def keyed(rows):
        out = {}
        for r in rows:
            k = str(r.get(date_key))
            if is_date_like(k):
                out[k] = r
        return out

    g_map, a_map = keyed(golden_rows), keyed(actual_rows)
    failures = []
    for k in sorted(set(g_map) | set(a_map)):
        if k not in g_map:
            failures.append(f"多出 golden 没有的日期行：{k}")
        elif k not in a_map:
            failures.append(f"缺少日期行：{k}（golden 有，实际无）")
        else:
            failures += compare_numbers(normalize_numbers(g_map[k]),
                                        normalize_numbers(a_map[k]), MONEY_EPS)
    return failures


def compare_run(run_dir: Path, golden: dict) -> dict:
    """一个运行目录的完整比对：取 candidate_sql → 独立重执行 → 归一化比对。"""
    case_id = run_dir.parent.name
    case_golden = golden["cases"].get(case_id)
    if case_golden is None:
        return {"error": f"golden 里没有用例 {case_id}"}

    raw = (run_dir / "session.jsonl").read_text(encoding="utf-8")
    events = parse_events(raw)
    # candidate = 最后一次非 dry-run 的 execute_query（dry-run 是验语法不是取数）
    executed = [s for s in events["sql_calls"] if not s["dry_run"]]
    if not executed:
        return {"error": "会话里没有真正执行过 SQL（只有 dry-run 或根本没有查询）"}
    candidate = executed[-1]["sql"]
    dry_runs = [s["sql"] for s in events["sql_calls"] if s["dry_run"]]

    exec_out = run_sql(candidate)
    if exec_out["status"] != "ok":
        return {"case": case_id, "candidate_sql": candidate, "dry_run_sqls": dry_runs,
                "result_correct": False,
                "failures": [f"candidate_sql 无法执行：{exec_out['error']}"],
                "truncated": False}
    if exec_out["truncated"]:
        return {"case": case_id, "candidate_sql": candidate, "dry_run_sqls": dry_runs,
                "result_correct": None,
                "failures": ["结果被 LIMIT 截断，拒绝判分（证据不完整）"],
                "truncated": True}

    failures = compare_rows(case_golden["primary_rows"], exec_out["rows"])
    verdict = {
        "case": case_id,
        "run_dir": str(run_dir),
        "compared_at": datetime.now().isoformat(timespec="seconds"),
        "candidate_sql": candidate,
        "dry_run_sqls": dry_runs,
        "golden_rows": case_golden["primary_rows"],
        "actual_rows": exec_out["rows"],
        "truncated": False,
        "result_correct": not failures,
        "failures": failures,
    }
    (run_dir / "verdict.json").write_text(
        json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8")
    return verdict


def latest_run(case_id: str) -> Path:
    """该用例最近一次运行目录（driver.py 的命名是 results/<case>/<时间戳>/）。"""
    runs = sorted((_REPO / "eval_e2e" / "results" / case_id).glob("*/"))
    if not runs:
        raise SystemExit(f"用例 {case_id} 还没有运行记录，先跑 driver.py --case {case_id}")
    return runs[-1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", help="指定运行目录（results/<case>/<时间戳>）")
    ap.add_argument("--case", help="或指定用例 ID，自动挑最近一次运行")
    args = ap.parse_args()

    if args.run:
        run_dir = Path(args.run)
    elif args.case:
        run_dir = latest_run(args.case)
    else:
        ap.error("必须给 --run 或 --case 之一")

    golden = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))
    if golden["meta"]["review_status"] != "human-reviewed":
        print("⚠ 注意：golden 尚未人工审核（auto-generated），比对结果仅供参考。")

    verdict = compare_run(run_dir, golden)
    if "error" in verdict:
        print(f"✗ 无法比对：{verdict['error']}")
        return 1

    print("=" * 62)
    print(f"用例：{verdict['case']}   （golden 状态：{golden['meta']['review_status']}）")
    print(f"candidate_sql：{verdict['candidate_sql'][:120]}{'...' if len(verdict['candidate_sql']) > 120 else ''}")
    if verdict["dry_run_sqls"]:
        print(f"先执行了 {len(verdict['dry_run_sqls'])} 次 dry-run（EXPLAIN 验语法）")
    print(f"golden 行数 {len(verdict['golden_rows'])} / 实际行数 {len(verdict['actual_rows'])}")
    if verdict["result_correct"] is True:
        print("✓ 结果比对：通过（与 golden 一致）")
    elif verdict["result_correct"] is False:
        print("✗ 结果比对：不通过")
        for f in verdict["failures"]:
            print(f"    - {f}")
    else:
        print("? 结果比对：无法判分")
        for f in verdict["failures"]:
            print(f"    - {f}")
    print(f"详细报告：{run_dir / 'verdict.json'}")
    print("=" * 62)
    return 0 if verdict["result_correct"] is True else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
