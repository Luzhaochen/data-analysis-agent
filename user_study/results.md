# User study results (2026-10-31)

Two paper-based studies, run with classmates (no business background required — both studies
measure claim-vs-reference checking, not domain judgment). Answer keys are kept in the
private evaluation directory outside this repository. Participants are anonymized as P1–P4.

## Study 1 — Do provenance citations help users find caliber errors? (n = 4)

**Design.** Two analysis outputs (A: Q2 GMV report; B: Q1 refund-rate report), each with four
caliber statements, two of them wrong (A2, A4, B2, B4). Within-subjects, counterbalanced:
packet 1 = A with citations / B without; packet 2 = A without / B with. Participants could
consult printed knowledge-base excerpts.

**Per-participant hits (planted errors detected / 2).**

| Participant | With citations | Without citations | False alarms |
|---|---|---|---|
| P1 | 1/2 (A4) | 0/2 | 3 |
| P2 | 0/2 | 1/2 (B4) | 0 |
| P3 | 2/2 (B2, B4) | 2/2 (A2, A4) | 0 |
| P4 | 2/2 (B2, B4) | 2/2 (A2, A4) | 0 |
| **Total** | **5/8** | **5/8** | 3 |

**Result: no difference between conditions (5/8 vs 5/8).** No consistent within-person
pattern either (+1, −1, 0, 0). Individual differences dominated: P3/P4 detected every
planted error in both conditions; P1/P2 missed almost all of them even with citations.

**Qualitative notes.**

- P4 on B2 (the planted claim that dirty rows were excluded): "没有剔除操作，只定位了"
  — the sharpest catch of the study, made in the *cited* condition by verifying the claim
  against the excerpt.
- P3 on A4: "客单价商品明细行数我没找到在哪" — reported searching for the referenced
  quantity, then marked the claim wrong correctly.
- P2 marked all four statements in task A correct (the cited condition), and noted on B2:
  "不明白为什么这三条是脏数据".
- P1 flagged two correct statements as wrong and missed both planted errors in B.

**Interpretation (used in the course report).** Output design lowers the *cost* of checking,
but engagement is decided by its *benefit* (Vasconcelos cost–benefit account): participants
with no stake did not verify even when the path was one line long. Citations worked as
designed for the participants who decided to check.

## Study 2 — Can users gate memory proposals? (n = 3)

**Design.** Six proposals in the production format (what / preview / why / source): three
correct (①③⑤) and three wrong — ② double-subtraction of refunds from GMV (business-meaning
error), ④ wrong index name (checkable fact), ⑥ reversed promotion filter (logic error).
Participants approved, edited, or rejected each.

**Per-participant decisions (✓ = correct decision).**

| Proposal | Truth | P1 | P2 | P4 | Correct |
|---|---|---|---|---|---|
| ① caliber confirmed | correct | 确认 ✓ | 确认 ✓ | 确认 ✓ | 3/3 |
| ② GMV double-subtraction | wrong | 确认 ✗ | 修改 ✓ ("先和用户确认再写入") | 确认 ✗ | 1/3 |
| ③ reusable snippet | correct | 拒绝 ✗ ("不是常态结论") | 确认 ✓ | 拒绝 ✗ | 1/3 |
| ④ wrong index name | wrong | 拒绝 ✓ | 拒绝 ✓ | 拒绝 ✓ | 3/3 |
| ⑤ new-table draft | correct | 确认 ✓ | 确认 ✓ | 确认 ✓ | 3/3 |
| ⑥ reversed IS NULL filter | wrong | 确认 ✗ | 确认 ✗ | 确认 ✗ | 0/3 |

**Wrong proposals intercepted: 5/9. Correct proposals approved: 6/9.**

**Findings.**

1. Users intercept what they can *verify*: the checkable-fact error was rejected 3/3; the
   meaning-based errors were approved 0/3 (⑥) and 1/3 (②, caught via process caution).
2. Proposal ⑥ was approved by all three participants — a strong signal that proposals
   correcting existing knowledge must attach the passage being corrected.
3. **Design iteration applied to the workflow:** proposal sources must now include a
   checkable reference to any knowledge being corrected (see `skills/analysis/SKILL.md`,
   Step 6).
