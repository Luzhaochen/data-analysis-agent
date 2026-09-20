"""gen_golden.py —— E2E 第 2 步：生成与维护标准答案（golden results）

用法：
  .venv/Scripts/python eval_e2e/gen_golden.py               # 现场执行 reference_sql 生成 golden
  .venv/Scripts/python eval_e2e/gen_golden.py --mark-reviewed  # 人工审核通过后盖章

设计原则（每一条都是可以面试讲的点）：
1. 答案与考生不同仓：reference_sql 只存在于仓库外的私有目录
   （EVAL_PRIVATE_DIR，默认仓库的兄弟目录 data-analysis-agent-eval-private），
   仓库里只留题目（eval_e2e/cases.json 无任何答案痕迹）；
2. golden 不抄历史记录：每次生成都现场执行 reference_sql，并记录
   生成时间、git 版本、MySQL 版本——任何环境变化都有据可查；
3. 关键指标双重校验：主 SQL 与交叉 SQL 走两条独立路径（月度分组求和 /
   明细求和），对拍一致才允许落盘；
4. 人工闸门：生成后的 golden 状态是 auto-generated，人工对照历史实测
   审核后才 --mark-reviewed——"答案"的信任链必须有人签字。
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_PY = sys.executable
_EXECUTE = _REPO / "skills" / "database-query" / "scripts" / "execute_query.py"

# 私有目录：默认仓库的兄弟目录，可用环境变量覆盖
_PRIVATE_DIR = Path(os.environ.get(
    "EVAL_PRIVATE_DIR",
    str(_REPO.parent / "data-analysis-agent-eval-private"),
))
_CASES_PRIVATE = _PRIVATE_DIR / "cases_private.json"
_GOLDEN_PATH = _PRIVATE_DIR / "golden_results.json"

MONEY_EPS = 0.01  # 金额对拍容差：0.01 元（一分钱）


def run_sql(sql: str) -> list:
    """复用 execute_query.py 执行 SQL，返回 rows（list[dict]，数值已归一化为 float）。"""
    proc = subprocess.run(
        [_PY, str(_EXECUTE), "--session", "golden-gen", "--sql", sql],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
    )
    out = json.loads(proc.stdout.strip())
    if out.get("status") != "ok":
        raise RuntimeError(f"SQL 执行失败：{out.get('error_type')} {out.get('message')}")
    return out["rows"]


def almost_equal(a, b, eps: float = MONEY_EPS) -> bool:
    return abs(float(a) - float(b)) <= eps


def cross_check(case_id: str, case: dict, primary_rows: list, cross_rows: list) -> list:
    """主 SQL 与交叉 SQL 对拍，返回不一致清单（空列表 = 拍平）。

    v1 只实现两种对拍规则，够覆盖现有两题；新题型再补新规则：
    - monthly_sum_then_total：交叉 SQL 按月分组 → 逐月求和必须等于主 SQL 的总量，
      客单价 = round(总额/总量, 2) 必须与主 SQL 一致（001 题）；
    - detail_sum_then_total：主 SQL 给逐行明细 → 明细逐行求和必须等于交叉 SQL 的总量
      （002 题）。
    """
    errors = []
    ctype = case["crosscheck"]["type"]
    if ctype == "monthly_sum_then_total":
        months = cross_rows
        expect = case["crosscheck"].get("expect_month_rows")
        if expect and len(months) != expect:
            errors.append(f"交叉 SQL 应返回 {expect} 个月，实际 {len(months)} 行")
        p = primary_rows[0]
        total_c = sum(m["c"] for m in months)
        total_s = sum(float(m["s"]) for m in months)
        if int(total_c) != int(p["valid_orders"]):
            errors.append(f"订单量对拍不一致：逐月求和 {int(total_c)} vs 主 SQL {int(p['valid_orders'])}")
        if not almost_equal(total_s, p["gmv"]):
            errors.append(f"GMV 对拍不一致：逐月求和 {total_s} vs 主 SQL {p['gmv']}")
        if not almost_equal(round(total_s / total_c, 2), p["avg_price"]):
            errors.append(f"客单价对拍不一致：推导值 {round(total_s / total_c, 2)} vs 主 SQL {p['avg_price']}")
    elif ctype == "detail_sum_then_total":
        t = cross_rows[0]
        detail = primary_rows
        expect = case["crosscheck"].get("expect_detail_rows")
        if expect and len(detail) != expect:
            errors.append(f"主 SQL 应返回 {expect} 行明细，实际 {len(detail)} 行")
        cnt_sum = sum(int(r["pay_order_cnt"]) for r in detail)
        amt_sum = round(sum(float(r["pay_amt"]) for r in detail), 2)
        if cnt_sum != int(t["total_cnt"]):
            errors.append(f"订单量对拍不一致：明细求和 {cnt_sum} vs 总量 {int(t['total_cnt'])}")
        if not almost_equal(amt_sum, t["total_amt"]):
            errors.append(f"金额对拍不一致：明细求和 {amt_sum} vs 总量 {t['total_amt']}")
    else:
        errors.append(f"未知对拍类型：{ctype}")
    return errors


def build_golden() -> dict:
    """现场执行全部 reference_sql，对拍后组装 golden_results。"""
    private = json.loads(_CASES_PRIVATE.read_text(encoding="utf-8"))
    git_rev = subprocess.run(["git", "-C", str(_REPO), "rev-parse", "HEAD"],
                             capture_output=True, text=True).stdout.strip() or "(未知)"
    mysql_version = run_sql("SELECT VERSION() AS v")[0]["v"]

    cases = {}
    for case_id, case in private["cases"].items():
        primary = run_sql(case["primary_sql"])
        cross = run_sql(case["crosscheck"]["sql"])
        errors = cross_check(case_id, case, primary, cross)
        if errors:
            raise RuntimeError(f"{case_id} 对拍失败，拒绝落盘：\n  " + "\n  ".join(errors))
        cases[case_id] = {
            "primary_rows": primary,
            "human_note": case.get("human_note", ""),
        }

    return {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "git_rev": git_rev,
            "mysql_version": mysql_version,
            "dataset": private["meta"]["dataset"],
            "schema_note": "schema 变更（mock_data/schema.sql）后必须重新生成本文件",
            "review_status": "auto-generated",  # 人工审核后 --mark-reviewed
        },
        "cases": cases,
    }


def mark_reviewed() -> None:
    """人工闸门：审核通过后盖章（对照历史实测/独立计算后执行）。"""
    golden = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))
    if golden["meta"]["review_status"] == "human-reviewed":
        print("已是 human-reviewed，无需重复盖章。")
        return
    golden["meta"]["review_status"] = "human-reviewed"
    golden["meta"]["reviewed_at"] = datetime.now().isoformat(timespec="seconds")
    _GOLDEN_PATH.write_text(json.dumps(golden, ensure_ascii=False, indent=2), encoding="utf-8")
    print("已盖章 human-reviewed。golden 现在可以作为评测标准答案。")
    print(f"  对照历史实测（Phase 3 iter_log）逐项核对：")
    for case_id, c in golden["cases"].items():
        print(f"  - {case_id}: {c['human_note']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mark-reviewed", action="store_true", help="人工审核通过后盖章")
    args = ap.parse_args()

    if not _CASES_PRIVATE.exists():
        print(f"私有用例文件不存在：{_CASES_PRIVATE}")
        print("参考 SQL 是标准答案，必须放在仓库外的私有目录（默认仓库的兄弟目录）。")
        return 1

    if args.mark_reviewed:
        mark_reviewed()
        return 0

    golden = build_golden()
    _GOLDEN_PATH.write_text(json.dumps(golden, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"golden 已生成：{_GOLDEN_PATH}")
    print(f"  git {golden['meta']['git_rev'][:8]} · MySQL {golden['meta']['mysql_version']}")
    for case_id, c in golden["cases"].items():
        rows = c["primary_rows"]
        print(f"  {case_id}: {len(rows)} 行标准答案，状态 {golden['meta']['review_status']}")
        for r in rows[:2]:
            print(f"    {r}")
    print("下一步：人工对照 iter_log 核对 → --mark-reviewed 盖章。")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
