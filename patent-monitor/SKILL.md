---
name: patent-monitor
description: Run configurable patent monitoring for any topic, target, technology or company defined in config.yaml. Use when the user asks to run patent monitoring or search recent patents on a topic or target.
---

# Patent Monitor — 可配置专利监控

监控任意主题的专利：药物靶点、技术方向、材料、公司……全部由 `config.yaml → targets` 定义，**代码里没有任何写死的监控对象**。

## 添加/修改监控项（核心操作）

编辑 `scripts/config.yaml → targets`，一个 key 就是一个监控项：

```yaml
targets:
  固态电池:                      # 名称任意，Excel 工作表/报告分组自动跟随
    keywords: '"solid-state battery" OR "solid electrolyte"'
    therapy_filter: ''           # 可选收窄子句
    exclude_terms: []            # 标题+摘要命中即剔除
    screening: generic           # pharma / generic / none
    description: "固态电池相关专利"
    wipo_field: "ALL"
```

筛选模式：
- **generic**（默认）— 排除词过滤 + 关键词覆盖度检查，适用于任何主题
- **pharma** — 创新药模式：保留药物/治疗相关，剔除诊断/器械/农用，推断技术方向与应用说明
- **none** — 只做排除词过滤，其余全保留（如监控某公司全部专利动向）

改完配置后：`python run_monitor.py --full-rebuild`（新监控项需全量初建）。

## 执行流程

### 1. 健康检查（首次或排障时）

```powershell
.trae\skills\patent-monitor\scripts\run.ps1 -Diagnose
```

### 2. 运行监控

```powershell
.trae\skills\patent-monitor\scripts\run.ps1
```

参数：`--full-rebuild`（全量）| `--no-download`（不下载PDF）| `--date YYYY-MM-DD`（回溯）| `--target 名称`（指定监控项）| `--mode web|api`（切换检索模式）

退出码：0 成功 | 1 部分成功 | 2 失败。末尾打印 `[SUMMARY] 新增: N`。

### 3. 检查输出

- `reports/patent_monitor_report_*.md` 存在且非空
- `patent_summary.xlsx` 各监控项工作表正常
- `task_state.json` 已更新
- PDF/HTML 在 `patents/{监控项}/`

### 4. 汇报（中文，必须包含）

1. 新增数量（每监控项各多少件）
2. 主要申请人
3. 主题方向分布（pharma 模式下为技术方向）
4. 自我审查发现（WARNING/ERROR 解释影响面）
5. 一句话趋势点评
6. 报告和 Excel 的绝对路径

## 关键约束（不可违反）

- 专利号标准化后去重：`(监控项, publication_number)` 必须唯一
- PDF 文件头必须是 `%PDF`，否则自动降级 `.html`
- WIPO 检索默认 `ALL=` 字段（有些关键词只出现在摘要/权利要求）
- 排除词务必配置：如 "APJ" 会匹配通信 Access Point、公司名缩写会撞其他领域
- 零结果 ≠ 无新增，必须先确认检索技术无异常
- 检索失败不展示 Mock 数据，返回空结果 + 明确错误原因
- 距上次运行不足 2 天自动跳过（隔日规则）

## 两种检索模式

| | Web 模式（默认，零配置） | API 模式（服务器） |
|---|---|---|
| 数据源 | WIPO PATENTSCOPE + Google Patents | PatentHub / 智慧芽 / incoPat |
| 速度 | 分钟级 | 秒级 |
| 切换 | `--mode web` | `--mode api` + config.yaml 填 api_key |

## 定时任务

```powershell
cd .trae\skills\patent-monitor\scripts
.\register_windows_task.ps1 -Weekly -Weekday 1 -Hour 8 -Minute 0
```

## 自包含文件结构

```
patent-monitor/
├── SKILL.md                     ← 本文件
├── scripts/
│   ├── run.ps1                  ← 一键入口（推荐）
│   ├── run_monitor.py           ← 主流程
│   ├── diagnose.py              ← 健康检查
│   ├── screening.py             ← 筛选 + 自我审查（三模式）
│   ├── downloader.py            ← PDF 下载 + %PDF 校验
│   ├── reporter.py              ← Markdown + Excel（动态工作表）
│   ├── models.py                ← 数据模型
│   ├── config_loader.py         ← 配置加载
│   ├── config.example.yaml      ← 配置模板（含药物靶点 + 通用主题两种示例）
│   ├── register_windows_task.ps1
│   └── retriever/
│       ├── __init__.py
│       ├── web_retriever.py     ← WIPO + Google Patents
│       └── api_retriever.py     ← PatentHub / 智慧芽 / incoPat
└── references/
```
