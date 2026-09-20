# Hooks 调试笔记（Phase 4 踩坑记录）

> 记录钩子开发中的全部踩坑与修复。hooks 是"看不见 stdout"的开发场景，
> 每一个坑都对应一个工程判断。

## 踩坑清单

### 1. hooks 的 stdout 没人看 → 调试必须写日志文件
开发前预判的坑，实测确认。echo 钩子的唯一可靠反馈渠道是追加写
`runs/hook_debug.log`。修复方式：所有钩子内错误统一 `log()` 到 `runs/hook.log`。

### 2. settings.json 改动只在会话启动时加载
当前会话里改 hooks 配置不生效——第一轮验证时 Stop 钩子静默无果，新开会话才触发。
排查 hook 没跑时，先确认"是不是当前会话加载的还是旧配置"。

### 3. SessionEnd 只有 1.5 秒共享预算（官方文档实测确认）
→ 设计对策：队列化。SessionEnd 只做毫秒级入队（enqueue），重活（计数/建档）
交给 SessionStart 的 process（预算 600s）。**钩子设计先查预算再定方案**。

### 4. transcript 是内部格式，官方不承诺稳定
逐字稿 JSONL 每行一个 JSON 对象，但字段结构随版本变化。对策：解析全程容错
（文件缺失/坏行跳过），**宁可少计数，不可崩钩子**。

### 5. 计数语义陷阱：「出现表名」≠「使用表」
第一版按"表名出现在逐字稿"计数，结果 9 张表全部 +1——因为模型读 overview.md 时
文件全文进了逐字稿，索引表格里 9 个表名全"出现"。修正：只匹配 SQL 的
`FROM/JOIN` 子句——知识库索引不会命中 FROM，只有真实查询会命中。
**计数的语义定义要在实现前想清楚：什么行为算"使用"。**

### 6. Python 类型 bug：`set |= list`
`bumped_all |= increment_overview_counts(used)`——函数返回 list，`|=` 只支持 set。
低端错误，但暴露了"钩子测试必须本地先跑"的必要性：本地模拟 stdin 跑 process
一秒钟就炸出来，比等真实会话触发快得多。

### 7. stdin 信实样（SessionEnd 实测）
```json
{"session_id": "...", "transcript_path": "C:\\Users\\...\\<id>.jsonl",
 "cwd": "D:\\data-analysis-agent", "hook_event_name": "SessionEnd",
 "reason": "prompt_input_exit"}
```
字段与官方协议一致；`reason` 取值 `prompt_input_exit`（用户 /exit）。

### 8. 用户级钩子全局触发 → cwd 守卫
Phase 6 用户级安装后，钩子在**所有项目**的会话里触发：其他项目的 SQL 里的
orders/users 这类常见表名会被计进本仓库 overview 的使用频次，无关会话还会被
注入 [自进化] 摘要。修复：`--enqueue` 用 stdin 的 `cwd` 做守卫，只有仓库内
会话才入队；`--process` 对旧队列里的仓库外会话直接过滤。**全局钩子的作用域
要自己想清楚：装的是用户级，动作就得有仓库边界。**

### 9. 队列语义：注释与实现不符 + 失败静默
code review 抓到的两个洞：① 注释写「未处理的原样保留」，实际 `unlink()` 无条件
清空整个队列；② `build_drafts` 用 `check=False` 且不判 returncode，建档失败照样
标记已处理，不可重试。修复：失败条目带 attempts 计数写回队列（上限 3 次），
计数/建档结果快照进条目（counted_tables / counted / drafted_tables），重试不会
重复 +1 或重复建档；无表名命中视为「处理完成」入 processed。**队列重试语义：
幂等靠快照，堵队靠上限。**

## 调试流程（可复用）

1. **最小钩子先行**：echo 钩子只写日志，验证事件触发 + 看 stdin 实样；
2. **本地模拟 stdin**：`'{"session_id":"..."}' | python hooks/session_evolution.py --enqueue`
   一条管道即可测逻辑，不等真实事件；
3. **真实触发验证**：新开会话 → 操作 → 退出 → 查队列/日志；
4. **幂等复跑**：同一队列跑两遍 process，第二遍必须零变化。

## 已知边界

- transcript JSONL 解析依赖内部格式（官方不承诺稳定），格式变化时计数可能失效——
  失效表现是"少计数"而非崩钩子，可接受；
- cwd 守卫：用户级安装下只有仓库内会话才入队自进化；仓库外会话照常使用技能，
  只是不沉淀知识（知识库属于本仓库）；
- 钩子内不调用 claude CLI（防递归）；
- 建草稿走子进程调 doc_table.py（连接失败不影响计数，只记日志）。
