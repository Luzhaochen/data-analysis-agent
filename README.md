# DataAnalysis Agent — knowledge-driven SQL with human-approved self-evolution

> [中文版](README.zh-CN.md)

A data-analysis agent built as a Claude Code plugin: **knowledge-base-driven SQL generation +
session-end self-evolution, gated by human permission**. Built on deterministic mock data
(modeled after a major e-commerce retailer) with known answers — fully reproducible and
evaluation-ready.

Core idea: an agent is only as good as its knowledge base. Table docs, calibers, SQL
snippets, and syntax rules are distilled into Markdown knowledge; at the end of every
session, the agent **proposes** what it learned (what / preview / why / source) and the
user approves, edits, or rejects each proposal before anything is written.

## The three interaction ideas (course project core)

1. **Permission-gated memory self-evolution** — after each session the agent proposes
   knowledge updates with four fields (what to remember, content preview, why, source).
   Nothing enters the knowledge base without an explicit per-item user decision.
   A memory browser (`list_memories.py`) makes the knowledge base inspectable at any time.
2. **Provenance-cited verification** — every SQL is displayed with each caliber annotated
   by its source (file + section) before execution; conclusions cite their knowledge
   sources; five post-query sanity checks (empty / magnitude / ratio / all-NULL /
   cross-table reconciliation) report anomalies instead of hiding them.
3. **User-curated context** — the agent reports its retrieval in one line (files read,
   caliber adopted, its source); the knowledge base is plain Markdown the user can edit
   directly — edit a file and the next answer changes with it.

A Streamlit **Human Oversight Console** prototypes this interaction layer with three
panels: verify before execution, approve memory proposals, inspect the knowledge base.

```powershell
streamlit run oversight_console.py
```

## Architecture

Three layers — hands (deterministic scripts), brain (knowledge base), mind (workflow):

| Layer | Contents |
|---|---|
| `skills/analysis/SKILL.md` | Six-step workflow (intent → retrieval → SQL → execute/retry → five checks → interpretation → proposal-based self-evolution) with 5 hard rules and per-step self-checks |
| `skills/database-query/` | Deterministic scripts: `execute_query.py` (read-only policy, auto-LIMIT, EXPLAIN dry-run, four-way error classification, retry log), `get_metadata.py`, `doc_table.py`, `scan_tables.py`, `list_memories.py` |
| `memory/` | Knowledge base: table index + per-table docs (usage / granularity / time fields / calibers / pitfalls / join keys), reusable SQL snippets, syntax rules |
| `hooks/` | Two self-evolution paths: session hooks (queue-based usage counting + doc drafts, deterministic, reported at next session start) and team-space scanning (new-table DDL → draft → human review) |

## Quick start

```powershell
# 1. Create database and tables (root; DROPs and recreates jd_demo)
cmd /c "mysql -u root -p < mock_data\schema.sql"
copy mock_data\setup.sql.example mock_data\setup.sql      # fill in your password
cmd /c "mysql -u root -p < mock_data\setup.sql"            # read-only data_agent account
copy config\connection.ini.example config\connection.ini  # fill in data_agent password

# 2. Generate data (deterministic, seed=42, ~1-3 min)
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python mock_data\gen_mock_data.py

# 3. Health check against known answers
.venv\Scripts\python mock_data\check_data.py
```

Security: the `data_agent` account is SELECT-only; credentials live in gitignored local
files; the mock dataset includes five planted dirty-data traps for verification training.

## Evaluation

**Deterministic regression suite** (`eval/`): 15 contract-test cases — knowledge coverage,
SQL must/must-not rules, EXPLAIN validation, and a write-rejection case. No LLM calls.

**End-to-end suite** (`eval_e2e/`): real isolated agent sessions answering business
questions. Standard answers are generated from reference SQLs with independent
cross-check queries and **human review**; answer keys live in a private directory outside
this repository. Each run uses a fresh conversation and fresh task files, and every
run's evidence is committed under `eval_e2e/results/`.

| Case | What it measures | Result |
|---|---|---|
| 001–003 | Q2 GMV / 618 daily payments / vague question must be clarified | 3/3, 3/3, 3/3 (behavior) |
| 004 | Refund-rate caliber before/after user approval | 3/3 correct before; **0/2 confidently wrong with an injected wrong caliber**; 2/2 correct after approval |
| 005 | Category-attribution rule before/after approval | correct answers in both states; after approval the agent cites the approved rule |

The injected-wrong-caliber run is a controlled ablation simulating an update that
bypassed the approval gate: the agent followed the polluted source confidently and ran
3–4× longer. **The user's approval is the variable that separates 0/2 from 5/5.**

**User studies** (`user_study/`): (1) do provenance citations help users find planted
caliber errors? (n = 4, counterbalanced — null result, 5/8 vs 5/8, explained by
verification cost–benefit); (2) can users gate memory proposals? (n = 3 — checkable
errors rejected 3/3, meaning-based errors approved 0/3 → proposal format iterated to
require a checkable reference). Scoring and raw responses: `user_study/results.md`;
the real-session flow: `docs/cs619-session-excerpt.md`.

## Repository layout

```
oversight_console.py   # Streamlit oversight console (prototype of the interaction layer)
install.ps1            # idempotent install/uninstall (skills junction + hooks merge)
config/                # local connection config (connection.ini gitignored)
_lib/                  # shared database client (connection / output / error classification)
skills/                # analysis workflow + database-query scripts
memory/                # knowledge base: tables / sql_snippets / sql_syntax.md
hooks/                 # session_evolution (path ①) + scan_tables (path ②)
eval/                  # deterministic contract tests (15 cases)
eval_e2e/              # end-to-end suite: driver / golden / compare / graders / results
user_study/            # user-study materials, scoring, results
mock_data/             # deterministic dataset (seed=42) + known answers
docs/                  # session excerpts and supplementary documents
```

*The knowledge base and workflow prompts are written in Chinese (the team's working
language). The console UI and this README are in English; the agent reads the Chinese
knowledge base natively.*
