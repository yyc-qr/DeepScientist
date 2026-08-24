# Paper Judge Integration

本文档总结本次在 `MCTS` 分支上新增的论文/成果报告评判能力，包括设计目标、技术原理、框架接入点、配置方式、输出文件和改动清单。

## 目标

本次改动的核心目标是：在现有 DeepScientist 工作流中加入一个可更换模型 API 的 paper/report judge，用于对论文草稿、成果报告或提交包进行证据约束的质量评估。

优先评判对象是：

- 论文草稿
- review package
- submission package
- 研究成果报告
- 由 `paper_bundle_manifest.json` 描述的 paper-like deliverable

judge 的定位不是替代现有的 coverage、language、outline 等硬性校验，而是提供一个更接近审稿人视角的结构化质量信号。直接输入论文时使用 `standalone_pdf`，只评价正文；完整 Quest 使用 `research_package`，才会将这些硬性校验和成果包材料纳入判断。

## 方法原理

本次采用的是单次 evidence-grounded LLM-as-a-judge 方案，主要吸收了以下几类较成熟的 judge 思路：

- 结构化 rubric：避免让模型只给一个笼统总分，而是按多个维度分别评分。
- 证据约束评审：要求 judge 只能基于 manuscript、manifest、contract health、coverage、language validation、evidence paths 等已有材料判断。
- JSON contract：要求模型返回稳定 JSON，便于机器读取、记录、比较和后续路由。
- 缺证据处理：无法评估的维度记为 `not_assessed`，不再自动补成 1 分。
- 程序化总分：模型负责分项判断，总分和 readiness 由有效分项的算术平均确定。
- readiness routing：输出不仅包含分数，还包含 `readiness` 和 `recommended_route`，让系统可以把评判结果接回任务流。

当前第一版是单 judge、单轮结构化评审。后续可以继续扩展为：

- multi-judge self-consistency
- pairwise judge，对比两个 draft 或两个 result package
- rubric calibration，用历史好/坏论文样例校准评分
- adversarial reviewer + author response loop
- 领域专用 rubric profile

## 新增模块

新增目录：

```text
src/deepscientist/judge/
```

包含文件：

```text
src/deepscientist/judge/__init__.py
src/deepscientist/judge/client.py
src/deepscientist/judge/documents.py
src/deepscientist/judge/paper.py
src/deepscientist/judge/prompts.py
src/deepscientist/judge/schemas.py
```

### `schemas.py`

定义默认 paper judge rubric、报告归一化逻辑和异常类型。

`standalone_pdf` 使用八项论文正文 rubric：

- `problem_significance`
- `novelty_positioning`
- `method_soundness`
- `evidence_sufficiency`
- `baseline_comparability`
- `claim_support`
- `writing_clarity`
- `manuscript_completeness`

`research_package` 使用的 rubric 包括：

- `problem_significance`
- `novelty_positioning`
- `method_soundness`
- `evidence_sufficiency`
- `baseline_comparability`
- `claim_support`
- `reproducibility`
- `writing_clarity`
- `figure_table_quality`
- `submission_readiness`

同时定义：

- `PaperJudgeError`
- `normalize_rubric(...)`
- `normalize_judge_profile(...)`
- `rubric_for_profile(...)`
- `normalize_judge_report(...)`
- score clamp 逻辑
- issue list 标准化逻辑

归一化后的 judge report 会固定包含：

- `overall_score`
- `confidence`
- `readiness`
- `recommended_route`
- `summary`
- `scores`
- `score_calculation`
- `unassessed_dimensions`
- `fatal_issues`
- `major_issues`
- `minor_issues`
- `required_followups`
- `claim_downgrade_recommendations`

### `prompts.py`

负责构造 paper judge prompt。

prompt 的关键约束是：

- 以 skeptical but constructive expert reviewer 的方式评审。
- 不允许编造实验、引用、指标或结论。
- 证据不足时必须标记 evidence gap。
- 独立 PDF 不因缺少 DeepScientist 内部成果包材料而扣分。
- 比较指标前必须判断数值是越高越好还是越低越好。
- 未提供视觉输入时禁止评价图表视觉设计。
- 只返回合法 JSON。

### `client.py`

实现 OpenAI-compatible judge client。

当前请求接口为：

```text
POST {api_base}/chat/completions
```

支持字段：

- `model`
- `messages`
- `temperature`
- `max_tokens`
- `response_format: {"type": "json_object"}`

API key 解析优先级：

1. 显式传入的 `api_key`
2. 配置中的 `api_key_env`
3. 环境变量 `DEEPSCIENTIST_JUDGE_API_KEY`
4. 环境变量 `OPENAI_API_KEY`

API base 解析优先级：

1. 显式配置的 `api_base`
2. 环境变量 `DEEPSCIENTIST_JUDGE_API_BASE`
3. 环境变量 `OPENAI_BASE_URL`
4. 默认 `https://api.openai.com/v1`

模型解析优先级：

1. 显式传入的 `model`
2. judge 配置中的 `model`
3. 环境变量 `DEEPSCIENTIST_JUDGE_MODEL`

### `paper.py`

实现 `PaperJudgeService`，是 judge 模块的核心服务。

主要职责：

- 构造 judge input
- 整合 paper contract、contract health、coverage validation、language validation
- 收集 manifest 和 evidence paths
- 调用模型 API
- dry-run 时生成本地 placeholder report
- 标准化 judge 输出

核心方法：

```python
PaperJudgeService.build_input(...)
PaperJudgeService.judge(...)
```

### `documents.py`

实现 Judge 统一文档加载和文本型 PDF 支持：

- 使用 `pypdf` 按页提取 PDF 文本。
- 在文本中保留 `--- Page N ---` 标记，支持报告引用页码。
- 记录 SHA-256、页数、选取页、字符数、截断状态和解析警告。
- 对加密、损坏、空白或疑似扫描 PDF 返回明确错误。
- 对超长 PDF 从全文范围选页，并保留首页和末页。

## 配置新增

修改文件：

```text
src/deepscientist/config/models.py
```

新增默认配置：

```yaml
judge:
  enabled: false
  provider: runner_default
  api_base: inherit
  api_key_env: inherit
  model: inherit
  temperature: 0.1
  max_output_tokens: 6000
  timeout_seconds: 120
  dry_run: false
  target_sample_chars: 120000
  pdf:
    enabled: true
    parser: pypdf
    max_file_mb: 50
    max_pages: 80
    max_chars: 120000
    min_text_chars_per_page: 40
```

设计含义：

- `provider: runner_default`：默认跟随 runner 的模型提供方。
- `api_base: inherit`：默认从 runner/provider metadata 继承。
- `api_key_env: inherit`：默认从 runner/provider metadata 继承。
- `model: inherit`：默认跟 runner 使用同一个模型。
- `dry_run: true`：用于本地管线测试，不会调用外部模型 API。
- `target_sample_chars`：限制送入 judge 的目标文本长度，避免一次传入过长 manuscript。

## Artifact 接入

修改文件：

```text
src/deepscientist/artifact/service.py
```

新增主要方法：

```python
ArtifactService.judge_paper(...)
ArtifactService.get_latest_paper_judge(...)
```

### `judge_paper(...)`

执行完整 paper/report judge 流程。

输入来源：

- 显式 `target_path`
- `paper/paper_bundle_manifest.json`
- `paper/draft.md`
- paper contract
- paper contract health
- manuscript coverage validation
- manuscript language validation
- manifest 中登记的 evidence paths

输出文件：

```text
paper/judge/judge_input_manifest.json
paper/judge/extraction_manifest.json
paper/judge/extracted_text.txt
paper/judge/judge_report.json
paper/judge/judge_report.md
paper/judge/judge_raw_response.jsonl
```

同时会调用 `artifact.record(...)` 登记一个 report artifact：

```text
kind: report
report_type: paper_judge
flow_type: paper_judge
status: completed
```

### `get_latest_paper_judge(...)`

读取当前 active paper workspace 下最新 judge report。

如果不存在，会返回：

```json
{
  "ok": false,
  "message": "No paper judge report exists for the active paper workspace."
}
```

## MCP 工具接入

修改文件：

```text
src/deepscientist/mcp/server.py
```

新增 MCP tools：

```text
artifact.judge_paper(...)
artifact.get_latest_paper_judge(...)
```

`judge_paper(...)` 是 state-changing tool，会写入 judge report 并登记 artifact。

`get_latest_paper_judge(...)` 是 read-only tool，只读取最新 judge 输出。

同时更新了 `compact_paper_write_result(...)`，让 `judge_paper` 的返回结果在 MCP 响应里保持精简，重点暴露：

- overall score
- confidence
- readiness
- recommended route
- fatal/major issue count
- 输出路径

## Runner 接入

修改文件：

```text
src/deepscientist/runners/codex.py
```

把以下工具加入 artifact MCP 自动批准列表：

```text
judge_paper
get_latest_paper_judge
```

这样 Codex runner 在执行论文写作、评审、收尾流程时可以直接调用 paper judge 工具。

## Skill 工作流接入

修改文件：

```text
src/skills/write/SKILL.md
src/skills/review/SKILL.md
src/skills/finalize/SKILL.md
src/skills/optimize/SKILL.md
```

### write skill

新增要求：

- 对 reviewable 或 submission-facing paper/report package，生成 bundle 后应调用 `artifact.judge_paper(...)`。
- judge 不得覆盖 coverage 或 language gate。
- judge 可以把任务路由回 `write`、`review`、`analysis-campaign`、`baseline`、`scout`、`decision` 或 `finalize`。

### review skill

新增要求：

- 如果已有当前 paper/report bundle 且没有 fresh judge report，应调用 `artifact.judge_paper(...)`。
- 如果已有 judge report，应读取 `artifact.get_latest_paper_judge(...)`。
- judge report 只是 reviewer signal，不能替代人工式 evidence audit。

### finalize skill

新增要求：

- finalization 前应检查最新 judge report。
- 如果 judge report 低于 `submission_ready`，除非用户明确批准 waiver，否则不能直接 finalize。

### optimize skill

顺手修复了已有 skill contract 测试漂移，补充了两个原本测试要求的精确约束：

- optimization candidate report 的 legacy 记录方式说明
- 重复失败机制前应使用 `memory.search(...)`

## 测试新增与修改

新增文件：

```text
tests/test_paper_judge.py
```

覆盖：

- 模型输出包裹在说明文本或 Markdown code block 中时，仍能抽取 JSON。
- 空输出或非 object JSON 会抛出 `PaperJudgeError`。
- judge report 会按 rubric 补齐字段并 clamp 越界分数。
- 文本型 PDF 会按页提取内容、保留页码并生成解析元数据。
- 空白或疑似扫描 PDF 会被拒绝，不会把无效文本送入模型。
- `ds judge <paper.pdf> --dry-run` 会自动创建 Quest、manifest 和完整输出。
- 仅设置默认 Judge API 环境变量即可构造真实 API 请求。

修改文件：

```text
tests/test_memory_and_artifact.py
tests/test_mcp_servers.py
tests/test_skill_contracts.py
```

新增或更新覆盖：

- dry-run judge 会写入 report、JSON、input manifest 并登记 artifact。
- `get_latest_paper_judge(...)` 能读取最新 report。
- artifact MCP tool list 包含新增 judge tools。
- write/review/finalize skills 中包含新增 judge 约束。

## 验证结果

已通过：

```text
python -m pytest tests/test_paper_judge.py tests/test_skill_contracts.py
```

当前针对性结果：

```text
46 passed
```

已通过：

```text
python -m compileall src\deepscientist tests\test_paper_judge.py tests\test_memory_and_artifact.py tests\test_mcp_servers.py tests\test_skill_contracts.py
```

已通过：

```text
git diff --check
```

自动化 smoke test 已通过：

- 构造临时 quest
- 生成包含真实文本流的两页 PDF
- 通过 `ds judge <paper.pdf> --dry-run` 自动建立最小评判工作区
- 提取带页码文本并写入解析清单
- 成功生成 `paper/judge/judge_report.md`
- 成功生成 `paper/judge/judge_report.json`
- 成功登记 artifact

当前环境限制：

- 尚未配置真实 Judge API，因此真实外部模型请求使用 mock 验证，未执行计费 API 调用。
- 扩展回归中有 6 项 daemon/config 测试因沙箱拒绝写入 `C:\Users\HOMER\.codex\skills` 而失败；Judge 针对性测试不受影响。
- 扫描件 OCR、图表视觉理解和版面评判尚未实现。

## 使用方式

最小 CLI 使用方式会自动创建 Quest 和 paper manifest：

```powershell
$env:DEEPSCIENTIST_JUDGE_API_BASE = "https://你的服务地址/v1"
$env:DEEPSCIENTIST_JUDGE_API_KEY = "你的 API Key"
$env:DEEPSCIENTIST_JUDGE_MODEL = "你的模型名称"
& .\.venv\Scripts\ds.exe judge "F:\papers\example.pdf"
```

上述命令默认使用 `standalone_pdf`。检查完整成果包时使用 `--judge-profile research_package`。

仅验证 PDF 提取和报告管线：

```powershell
& .\.venv\Scripts\ds.exe judge "F:\papers\example.pdf" --dry-run
```

在具备 paper workspace 的 quest 中，可以通过 MCP 调用：

```python
artifact.judge_paper(
    target_path="paper/draft.md",
    package_type="review_package",
)
```

本地管线验证可使用：

```python
artifact.judge_paper(
    target_path="paper/draft.md",
    package_type="review_package",
    dry_run=True,
)
```

读取最新 judge report：

```python
artifact.get_latest_paper_judge()
```

## 设计边界

当前版本刻意保持为第一版可落地实现：

- 只实现 OpenAI-compatible `/chat/completions` API。
- 只实现单 judge、单轮评审。
- PDF 支持目前是文本层提取，不包含 OCR、图表视觉理解或版面质量评判。
- 不自动调用真实外部 API，除非配置好模型和 key。
- `standalone_pdf` 不读取 coverage/language/outline 等成果包 gates；`research_package` 保留这些检查。
- 不把 judge 分数当成唯一质量标准，而是作为 evidence-grounded reviewer signal。

## 后续可扩展方向

推荐下一步改进：

- 扩展更多领域或会议专用 profile。
- 增加多 judge self-consistency，对同一 package 做多次评审后聚合。
- 增加 pairwise judge，对比修改前后 draft 是否真的变好。
- 增加 calibration examples，让 judge 参考历史优秀/失败论文。
- 增加 Responses API adapter，进一步适配非 chat-completions 模型。
- 增加 budget-aware truncation，把长论文按 section 和 evidence priority 组织输入，而不是只按字符截断。
