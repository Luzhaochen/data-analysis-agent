"""run_all.py —— E2E 第 4 步：重复实验 + 指标聚合

用法：
  .venv/Scripts/python eval_e2e/run_all.py                  # 全部用例，每题 3 次
  .venv/Scripts/python eval_e2e/run_all.py --case 001-q2-gmv --runs 2

本步的方法论：
1. LLM 有随机性，一次成功没有说服力——同一题多跑几遍，报告分布而不是单点；
2. 每次运行完立刻比对（driver + compare 串联），失败不中断——
   评测收集的是证据，不是心情；
3. 指标口径先定义清楚再算（同事 review 的指标表在本项目的落地子集）：
   - 成功率 Success Rate：比对通过次数 / 总运行次数（比对器在 compare.py）；
   - 一致性 Consistency：同一题多次运行的结果互相是否吻合——都过了还不算稳，
     3 次互相一致才算稳（用 compare.py 的同一套比对逻辑做两两互比）；
   - 效率 Efficiency：平均工具调用数 / 墙钟时间 / 成本（LLM 评测必须有成本意识）。
4. 汇总报告落盘 results/aggregate-<时间戳>.json——评测结论可追溯，不靠终端截图。
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from driver import load_cases, run_case
from compare import compare_rows, compare_run, _GOLDEN_PATH
from graders import grade_run

_REPO = Path(__file__).resolve().parents[1]
RESULTS_DIR = _REPO / "eval_e2e" / "results"


def run_one(case: dict, golden: dict) -> dict:
    """跑一次 + 立刻评分，返回单次记录（任何失败都不中断整轮）。

    评分入口按题型分流：clarify 题的正确行为是「提问不执行」，没有 candidate_sql
    可比，交给 graders 的行为检查；SQL 题先比对结果（compare），行为与安全
    由第 5 步的 graders 单独评。
    """
    meta = run_case(case)
    rec = {
        "run_dir": meta.get("run_dir", ""),
        "tool_calls": len(meta.get("tool_calls", [])),
        "wall_s": meta.get("wall_seconds"),
        "cost_usd": meta.get("cost_usd"),
    }
    if "error" in meta:
        rec.update({"result": False, "failures": [meta["error"]]})
        return rec
    if case.get("expected_behavior") == "clarify":
        grade = grade_run(Path(meta["run_dir"]), case)
        rec.update({
            "result": grade["safe"] and grade["behavior_score"] == 1.0,
            "failures": grade["violations"] +
                        [c["name"] for c in grade["checks"] if not c["passed"]],
        })
        return rec
    verdict = compare_run(Path(meta["run_dir"]), golden)
    if "error" in verdict:
        rec.update({"result": False, "failures": [verdict["error"]]})
    else:
        rec.update({
            "result": verdict["result_correct"],  # True/False/None（None=截断无法判分）
            "failures": verdict.get("failures", []),
            "actual_rows": verdict.get("actual_rows"),
        })
    return rec


def aggregate_case(case_id: str, case: dict, recs: list) -> dict:
    """单用例聚合：成功率 / 一致性 / 效率。"""
    n = len(recs)
    passed = [r for r in recs if r["result"] is True]
    # 一致性：通过了的运行两两互比（复用 compare.py 的比对逻辑）；
    # clarify 题没有结果集，一致性以行为分为准（不在两两互比范围内）
    pairs = 0
    consistent_pairs = 0
    if case.get("expected_behavior") != "clarify":
        for i in range(len(passed)):
            for j in range(i + 1, len(passed)):
                pairs += 1
                if not compare_rows(passed[i]["actual_rows"], passed[j]["actual_rows"]):
                    consistent_pairs += 1

    def avg(key):
        vals = [r[key] for r in recs if r.get(key) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    return {
        "name": case["name"],
        "runs": recs,
        "success_rate": f"{len(passed)}/{n}",
        "consistency": ("以行为分为准（clarify 题无结果集）"
                        if case.get("expected_behavior") == "clarify"
                        else (f"{consistent_pairs}/{pairs} 对互相一致" if pairs
                              else "无≥2次通过，无法计算")),
        "avg_tool_calls": avg("tool_calls"),
        "avg_wall_s": avg("wall_s"),
        "avg_cost_usd": avg("cost_usd"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=int, default=3, help="每题运行次数（默认 3）")
    ap.add_argument("--case", help="只跑指定用例（调试用）")
    args = ap.parse_args()

    cases = load_cases()
    if args.case:
        cases = {args.case: cases[args.case]}
    golden = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "runs_per_case": args.runs,
        "golden_review_status": golden["meta"]["review_status"],
        "cases": {},
    }

    for case_id, case in cases.items():
        print(f"[{datetime.now():%H:%M:%S}] 开始 {case_id}（{case['name']}）×{args.runs}",
              flush=True)
        recs = []
        for i in range(args.runs):
            t0 = time.time()
            rec = run_one(case, golden)
            rec["run_index"] = i + 1
            mark = "✓" if rec["result"] is True else ("✗" if rec["result"] is False else "?")
            print(f"  第 {i + 1}/{args.runs} 次 {mark}  "
                  f"({round(time.time() - t0)}s，工具 {rec['tool_calls']} 次，"
                  f"${rec.get('cost_usd')})", flush=True)
            recs.append(rec)
        report["cases"][case_id] = aggregate_case(case_id, case, recs)

    out = RESULTS_DIR / f"aggregate-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 62)
    print(f"汇总报告：{out}")
    for case_id, agg in report["cases"].items():
        print(f"\n{case_id}（{agg['name']}）")
        print(f"  成功率：{agg['success_rate']}    一致性：{agg['consistency']}")
        print(f"  效率：平均工具调用 {agg['avg_tool_calls']} 次 / "
              f"墙钟 {agg['avg_wall_s']}s / 成本 ${agg['avg_cost_usd']}")
        for rec in agg["runs"]:
            fails = rec["failures"][0][:80] if rec["failures"] else ""
            print(f"    第 {rec['run_index']} 次 {'✓' if rec['result'] is True else '✗'}  {fails}")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
