# Judge 模块使用指南

Judge 用一个 OpenAI-compatible 模型 API 评判 PDF 或文本格式的论文，并生成结构化评分、问题清单和 Markdown 报告。

当前实现保持为单模型、单轮调用。直接输入论文时默认只评价论文正文，不要求准备 DeepScientist 的 outline、LaTeX 源码、evidence ledger 或实验日志。

## 快速启动

以下命令均在仓库根目录运行：

```powershell
cd F:\projects\AIscientist\DeepScientist
```

### 1. 安装

首次使用或代码更新后执行：

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -U pip
& .\.venv\Scripts\python.exe -m pip install -e .
```

PowerShell 无法运行 `Activate.ps1` 不影响使用，直接调用 `.venv` 中的程序即可。

### 2. 配置模型 API

```powershell
$env:DEEPSCIENTIST_JUDGE_API_BASE = "https://你的服务地址/v1"
$env:DEEPSCIENTIST_JUDGE_API_KEY = "你的 API Key"
$env:DEEPSCIENTIST_JUDGE_MODEL = "你的模型名称"
```

使用当前已经联调过的 DeepSeek-compatible 服务时，例如：

```powershell
$env:DEEPSCIENTIST_JUDGE_API_BASE = "https://api.deepseek.com"
$env:DEEPSCIENTIST_JUDGE_API_KEY = "你的 API Key"
$env:DEEPSCIENTIST_JUDGE_MODEL = "deepseek-v4-flash"
```

模型名必须以 API 服务实际支持的名称为准。不要把 API Key 写进仓库。

### 3. 检查 PDF 提取

`--dry-run` 不调用模型，也不会产生 API 费用：

```powershell
& .\.venv\Scripts\ds.exe judge `
  "C:\Users\HOMER\Desktop\latentODE.pdf" `
  --dry-run
```

确认输出中的以下项目正常：

- `page_count` 与论文页数一致。
- `suspected_scanned` 为 `false`。
- `truncated` 为 `false`，或截断符合预期。
- `warnings` 为空，或警告可以接受。

dry-run 生成的分数只是管线占位结果，不能用于评价论文质量。

### 4. 正式评判

```powershell
& .\.venv\Scripts\ds.exe judge `
  "C:\Users\HOMER\Desktop\latentODE.pdf" `
  --model "deepseek-v4-flash"
```

直接输入文件时默认使用 `standalone_pdf`，只评价论文正文。系统会自动创建一个 Quest，并打印报告路径。

复用已有 Quest：

```powershell
& .\.venv\Scripts\ds.exe judge `
  "C:\Users\HOMER\Desktop\latentODE.pdf" `
  --quest-id 003 `
  --model "deepseek-v4-flash"
```

## 评判模式

### `standalone_pdf`

适合直接评判一篇论文或成果报告，也是 CLI 默认值。

评分维度包括：

- 研究意义
- 创新性与相关工作定位
- 方法合理性
- 实验充分性
- baseline 可比性
- 结论与证据一致性
- 写作清晰度
- 论文完整度

该模式不会因为缺少 DeepScientist 内部材料而扣分。当前 PDF 流程只向模型提供提取文本，因此图表视觉质量会显示为 `not_assessed`，且不参与总分。

显式指定方式：

```powershell
& .\.venv\Scripts\ds.exe judge "F:\papers\example.pdf" `
  --judge-profile standalone_pdf
```

### `research_package`

适合评判完整 DeepScientist Quest。除论文正文外，还会检查 manifest、paper contract、coverage、language validation 和成果证据路径。

```powershell
& .\.venv\Scripts\ds.exe judge "F:\papers\example.pdf" `
  --quest-id 003 `
  --judge-profile research_package
```

不要用该模式评判只有一个 PDF 的外部论文，否则成果包缺失会合理地反映在 package 相关维度中。

## CLI 参数

完整命令格式：

```text
ds judge INPUT_PATH
  [--quest-id QUEST_ID]
  [--package-type PACKAGE_TYPE]
  [--judge-profile standalone_pdf|research_package]
  [--model MODEL]
  [--api-base API_BASE]
  [--api-key-env ENV_NAME]
  [--dry-run]
```

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `INPUT_PATH` | 必填 | PDF、Markdown、纯文本、LaTeX 或 reStructuredText 文件路径 |
| `--quest-id` | 自动创建 | 将输入和报告写入指定 Quest |
| `--package-type` | `review_package` | 写入 paper manifest 的成果包类型 |
| `--judge-profile` | `standalone_pdf` | 选择正文评判或完整成果包评判 |
| `--model` | 配置或环境变量 | 本次调用使用的模型名 |
| `--api-base` | 配置或环境变量 | OpenAI-compatible API 根地址 |
| `--api-key-env` | 自动解析 | 保存 API Key 的环境变量名称，不是 Key 本身 |
| `--dry-run` | `false` | 只验证提取和报告管线，不调用模型 |

不把 Key 放入默认环境变量时，可以指定自定义变量名：

```powershell
$env:MY_JUDGE_KEY = "你的 API Key"

& .\.venv\Scripts\ds.exe judge "F:\papers\example.pdf" `
  --api-base "https://你的服务地址/v1" `
  --api-key-env "MY_JUDGE_KEY" `
  --model "你的模型名称"
```

查看本机安装版本支持的参数：

```powershell
& .\.venv\Scripts\ds.exe judge --help
```

## 配置文件

长期使用时，可以在 DeepScientist home 的 `config/config.yaml` 中保存非敏感配置。默认 home 通常为：

```text
C:\Users\你的用户名\DeepScientist
```

示例：

```yaml
judge:
  enabled: true
  provider: openai_compatible
  api_base: https://你的服务地址/v1
  api_key_env: DEEPSCIENTIST_JUDGE_API_KEY
  model: 你的模型名称
  temperature: 0.1
  max_output_tokens: 6000
  timeout_seconds: 120
  empty_response_max_attempts: 3
  thinking: auto
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

### Judge 参数

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `enabled` | `false` | Judge 功能配置标记；CLI 显式调用仍会运行 |
| `provider` | `runner_default` | API provider，目前支持 OpenAI-compatible 调用 |
| `api_base` | `inherit` | API 根地址；客户端请求 `{api_base}/chat/completions` |
| `api_key_env` | `inherit` | 保存 API Key 的环境变量名 |
| `model` | `inherit` | 模型名称；默认尝试继承 runner |
| `temperature` | `0.1` | 模型生成温度，评判建议保持较低 |
| `max_output_tokens` | `6000` | Judge JSON 最大输出 token 数 |
| `timeout_seconds` | `120` | 单次 HTTP 请求超时时间 |
| `empty_response_max_attempts` | `3` | API 返回空正文时的最大尝试次数 |
| `thinking` | `auto` | 推理模式；DeepSeek-compatible 接口会按实现处理 |
| `dry_run` | `false` | 是否默认只运行本地管线 |
| `target_sample_chars` | `120000` | 文本文件提供给 Judge 的最大字符数 |

### PDF 参数

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `pdf.enabled` | `true` | 是否允许 PDF 输入 |
| `pdf.parser` | `pypdf` | PDF 文本提取器 |
| `pdf.max_file_mb` | `50` | 最大 PDF 文件大小 |
| `pdf.max_pages` | `80` | 最多选择的 PDF 页数 |
| `pdf.max_chars` | `120000` | 最多送入 Judge 的 PDF 文本字符数 |
| `pdf.min_text_chars_per_page` | `40` | 判断页面是否具有有效文本层的阈值 |

配置解析优先级为：命令行参数、Judge 环境变量、配置文件或 runner 继承、通用 OpenAI 环境变量。

## 输出文件

每次评判会写入：

```text
<DeepScientist home>/quests/<quest_id>/paper/judge/
├── extraction_manifest.json
├── extracted_text.txt
├── judge_input_manifest.json
├── judge_raw_response.jsonl
├── judge_report.json
└── judge_report.md
```

| 文件 | 用途 |
| --- | --- |
| `judge_report.md` | 供人工阅读的最终报告 |
| `judge_report.json` | 规范化后的机器可读结果 |
| `judge_input_manifest.json` | 实际送入模型的 Profile、rubric、正文和元数据 |
| `judge_raw_response.jsonl` | API 原始响应及 token 使用记录 |
| `extraction_manifest.json` | PDF 页数、哈希、字符数、截断和警告 |
| `extracted_text.txt` | 从 PDF 提取并带页码标记的正文 |

`overall_score` 是所有有效分项的程序化算术平均，模型自行返回的总分不会直接采用。`unassessed_dimensions` 不参与总分。

Judge 是辅助审稿信号，不应作为论文质量或投稿决策的唯一依据。重点核对分项理由、页码证据、major issues 和 claim downgrade 建议。

## 常见问题

### `Paper judge model is not configured`

没有解析到模型名。设置 `DEEPSCIENTIST_JUDGE_MODEL`，或传入 `--model`。

### `400 Bad Request`

检查 API base、Key 和模型名。错误详情中的 `response` 通常会列出服务实际支持的模型名称。

### API 返回空内容

客户端会自动重试，并保存每次 `finish_reason` 和 token usage。推理 token 占满输出预算时，可关闭模型 thinking，或适当提高 `max_output_tokens`。

### PDF 提示 `likely scanned`

PDF 没有足够的可提取文本，通常是扫描件。当前版本不包含 OCR，请先生成带文本层的 PDF。

### PDF 被截断

检查 `extraction_manifest.json`，并调整 `judge.pdf.max_pages` 或 `judge.pdf.max_chars`。提高限制也会增加输入 token 和 API 成本。

### PowerShell 禁止运行脚本

无需执行 `Activate.ps1`。直接使用：

```powershell
& .\.venv\Scripts\ds.exe judge "F:\papers\example.pdf"
```

## 验证安装

安装 pytest 后运行：

```powershell
& .\.venv\Scripts\python.exe -m pip install pytest
$env:PYTHONPATH = "src"
& .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests/test_paper_judge.py
```

模块原理、代码结构和改动清单参见 [PAPER_JUDGE_INTEGRATION.md](PAPER_JUDGE_INTEGRATION.md)。
