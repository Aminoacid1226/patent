---
name: patent-monitor
description: Monitor drug innovation patents for targets TSHR APJ PCSK9 and CYP51. Use when the user asks to run patent monitoring or search recent patents for these targets.
---

# Patent Monitor — 多靶点创新药专利监控

监控四个靶点的创新药专利：**TSHR**（甲状腺刺激激素受体）、**APJ**（Apelin receptor）、**PCSK9**（降脂靶点）、**CYP51**（真菌抗真菌靶点）。

## 流程定位

本 Skill 是**自包含**的——所有 Python 代码在 `scripts/` 目录，纯标准库零依赖。脚本运行时的工作目录就是 `scripts/`。

首次运行前会自动从 `config.example.yaml` 复制生成 `config.yaml`。建议用户编辑 `config.yaml → output.root` 改成他想存放输出的目录。

## 执行流程

### 1. 健康检查（首次运行或遇到问题时）

```powershell
.trae\skills\patent-monitor\scripts\run.ps1 -Diagnose
```

确认配置可加载、网络可达、PDF 下载链路 OK、输出目录可写。如果某源不可用，在最终汇报里标注。

### 2. 运行监控

```powershell
.trae\skills\patent-monitor\scripts\run.ps1
```

或者手动调用：

```powershell
cd .trae\skills\patent-monitor\scripts
python run_monitor.py
```

可选参数（按需追加）：
| 参数 | 用途 |
|---|---|
| `--full-rebuild` | 忽略 task_state.json，强制从 1970 年全量检索 |
| `--no-download` | 仅检索+筛选，不下载 PDF |
| `--date YYYY-MM-DD` | 模拟运行日期，用于回溯测试 |
| `--target TSHR` | 仅检索某靶点（可重复传多个） |
| `--mode web` 或 `--mode api` | 强制切换检索模式 |
| `--config path` | 指定配置文件 |

退出码：0 成功 | 1 部分成功 | 2 失败。脚本末尾会打印 `[SUMMARY] 新增: N` 行，机器可读。

### 3. 检查输出

脚本完成后确认：
- `报告: ...patent_monitor_report_*.md` 存在且非空
- `Excel: ...patent_summary.xlsx` 存在，四工作表（TSHR / APJ / PCSK9 / CYP51）
- `task_state.json` 已更新 last_date 和累计统计
- 新增的 PDF/HTML 在 `patents/{靶点}/` 下（如果启用了下载）

### 4. 汇报

用中文总结本次结果，必须包含：
1. **新增数量**：每靶点各多少件，总计多少
2. **主要申请人**：哪几家公司/机构有动作
3. **技术方向分布**：抗体、siRNA、小分子、疫苗等各几件
4. **自我审查发现**：如果有 WARNING/ERROR 要解释并说清楚影响面
5. **趋势点评**：一句话说清楚这次反映了什么研发热点
6. **输出路径**：报告和 Excel 的绝对路径

## 关键约束（不可违反）

- 专利号标准化后去重：`(靶点, publication_number)` 必须唯一，同族重复入库会被剔除
- PDF 文件头必须是 `%PDF`：非 PDF 内容绝对不能以 `.pdf` 命名保存，自动降级 `.html`
- WIPO 检索式必须用 `ALL=` 字段，不能用 `TI=`——CYP51 常只出现在摘要/权利要求
- CYP51 仅限抗真菌方向，**排除词**：remyelination / multiple sclerosis / myelin（人源 CYP51 不属于监控范围）
- APJ 排除词：access point / wifi / wireless（"APJ" 会匹配通信术语）
- PCSK9 排除词：诊断方法 / 检测试剂盒（必须有治疗意图）
- 检索失败时不要展示 Mock 数据，返回空结果 + 明确错误原因
- 定时任务如果触发时距离上次不足 2 天，会自动跳过（隔日规则）

## 两种检索模式

| | Web 模式（默认，本机） | API 模式（服务器） |
|---|---|---|
| 数据源 | WIPO PATENTSCOPE + Google Patents | PatentHub / 智慧芽 |
| 速度 | 分钟级 | 秒级 |
| 切换 | `--mode web` | `--mode api` + 填 config.yaml 的 api_key |
| 鉴权 | 无 | header 或 URL param（看供应商） |

## 定时任务注册

```powershell
cd .trae\skills\patent-monitor\scripts
.\register_windows_task.ps1 -Weekly -Weekday 1 -Hour 8 -Minute 0
```

支持 `-Daily` / `-RunNow`，脚本会自动找 Python、卸载旧版本、注册新版本。

## 自包含文件结构

```
patent-monitor/
├── SKILL.md                     ← 本文件（Agent 指令）
├── scripts/
│   ├── run.ps1                  ← 统一入口（推荐用这个）
│   ├── run_monitor.py           ← 主流程
│   ├── diagnose.py              ← 健康检查
│   ├── screening.py             ← 创新药筛选 + 自我审查
│   ├── downloader.py            ← PDF 下载 + %PDF 校验
│   ├── reporter.py              ← Markdown + Excel 生成
│   ├── models.py                ← 数据模型
│   ├── config_loader.py         ← 配置加载
│   ├── config.example.yaml      ← 配置模板（首次运行自动复制为 config.yaml）
│   ├── register_windows_task.ps1← 定时任务注册
│   └── retriever/
│       ├── __init__.py
│       ├── web_retriever.py     ← WIPO + Google Patents
│       └── api_retriever.py     ← PatentHub / 智慧芽 / incoPat
└── references/
```
