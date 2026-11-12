# patent-monitor Skill — 安装说明

多靶点创新药专利监控 Skill，监控 TSHR / APJ / PCSK9 / CYP51 四个靶点。

纯 Python 标准库（零依赖），Windows / macOS / Linux 均可运行。

---

## 前置条件

- Python 3.9+（在 PATH 里能直接调 `python` 或 `python3`）
- Trae IDE（或支持 Skill 的 Trae 产品）

---

## 安装方式（三选一）

### 方式 1：ZIP 导入（最直观）

1. 拿到 `patent-monitor-skill.zip`
2. Trae → 设置 → Skills → 导入 → 选 ZIP 文件
3. 等待解压完成，Skill 自动可用

### 方式 2：手动放入目录

解压 ZIP，把 `patent-monitor/` 整个目录复制到：

| 用途 | 路径 |
|---|---|
| 本项目专用（推荐） | `<你的工作区>/.trae/skills/patent-monitor/` |
| 全局所有项目 | `C:\Users\<你>\.trae-cn\skills\patent-monitor\`（CN 版）<br>`C:\Users\<你>\.trae\skills\patent-monitor\`（国际版） |

### 方式 3：GitHub（如果发布了）

让 Trae 里的 Agent 说："帮我从 GitHub 安装 [仓库地址]"。

---

## 首次使用（必须做）

Skill 里的输出目录默认是 `patent_monitor_output`（相对路径）。强烈建议改成你想存放产物的位置。

```powershell
# 1. 在工作区根目录找到这个文件，复制一份
copy .trae\skills\patent-monitor\scripts\config.example.yaml ^
      .trae\skills\patent-monitor\scripts\config.yaml

# 2. 打开 config.yaml，修改这一行：
#    output:
#      root: "C:\Users\你的名字\patent-monitor"   ← 改成你想要的绝对路径
```

不做这步也能跑——脚本会自动从 config.example.yaml 复制，但输出会落到 scripts 目录下面，不太整洁。

---

## 使用

### 方式 A：让 AI 自动触发（推荐）

在 Trae 里对话时说：
- "帮我跑一下专利监控"
- "TSHR 最近有没有新专利"
- "patent monitor 一下"

AI 会自动识别 Skill，按流程执行。

### 方式 B：命令行直接跑

```powershell
# 完整运行
.trae\skills\patent-monitor\scripts\run.ps1

# 健康检查（先确认环境没问题）
.trae\skills\patent-monitor\scripts\run.ps1 -Diagnose

# 不下载 PDF（快很多）
.trae\skills\patent-monitor\scripts\run.ps1 -NoDownload

# 全量重建（忽略上次状态）
.trae\skills\patent-monitor\scripts\run.ps1 -FullRebuild
```

### 方式 C：定时任务

```powershell
cd .trae\skills\patent-monitor\scripts

# 每周一 08:00 自动跑
.\register_windows_task.ps1 -Weekly -Weekday 1 -Hour 8 -Minute 0

# 每天 23:00 自动跑
.\register_windows_task.ps1 -Daily -Hour 23

# 注册完立即手动触发一次
.\register_windows_task.ps1 -Weekly -Weekday 1 -RunNow
```

---

## 两种检索模式

| | Web 模式（默认，零配置） | API 模式（商业数据库） |
|---|---|---|
| 数据源 | WIPO PATENTSCOPE + Google Patents | PatentHub / 智慧芽 / incoPat |
| 速度 | 分钟级 | 秒级 |
| 是否要 API Key | 否 | 是（填 config.yaml → api → 对应供应商） |
| 切换 | `--mode web` | `--mode api` |

---

## 输出产物

默认在 `output.root` 目录下：

```
patent_monitor_output/
├── task_state.json           ← 运行状态（上次日期、累计统计）
├── patent_summary.xlsx       ← Excel 汇总（4 个工作表）
├── patent_records.json       ← 完整记录 JSON
├── applicant_abbr.json       ← 申请人缩写映射
├── reports/
│   └── patent_monitor_report_YYYY-MM-DD_HHMMSS.md
└── patents/
    ├── TSHR/
    ├── APJ/
    ├── PCSK9/
    └── CYP51/
```

---

## 常见问题

**Q: 跑起来很慢？** Web 模式从 WIPO 逐条抓详情页确实慢（每个靶点 30~120 秒）。加 `--no-download` 先看看结果，不急着下载全文。或者周末挂个定时任务让它自己跑。

**Q: WIPO 返回 0 条？** 可能被验证码封锁。跑 `run.ps1 -Diagnose` 确认网络通。等几分钟再试，或用 `--mode api`（如果有 API Key）。

**Q: 想加新靶点？** 编辑 `scripts/config.yaml → targets:` 加一个节点即可。格式参照已有的 TSHR/APJ/PCSK9/CYP51。

**Q: 想加新检索源？** 现在内置 WIPO 和 Google Patents。想加 Espacenet/USPTO 需要在 `scripts/retriever/web_retriever.py` 里加对应的 Retriever 类。

**Q: 卸载？** 直接删除 Skill 目录。已生成的监控输出（reports/、patents/、Excel）不会被删。

---

## 文件清单（15 个）

```
patent-monitor/
├── SKILL.md                     ← Skill 指令（AI 读这个）
├── scripts/
│   ├── run.ps1                  ← 一键入口（推荐用这个）
│   ├── run_monitor.py           ← 主流程（22 KB）
│   ├── diagnose.py              ← 健康检查
│   ├── screening.py             ← 创新药筛选 + 自我审查
│   ├── downloader.py            ← PDF 下载 + %PDF 强制校验
│   ├── reporter.py              ← Markdown + Excel 生成（纯标准库）
│   ├── models.py                ← 数据模型
│   ├── config_loader.py         ← 配置加载
│   ├── config.example.yaml      ← 配置模板
│   ├── register_windows_task.ps1
│   └── retriever/
│       ├── __init__.py
│       ├── web_retriever.py     ← WIPO + Google Patents
│       └── api_retriever.py     ← PatentHub / 智慧芽 / incoPat
└── references/
```

---

## 故障排查

| 症状 | 排查 |
|---|---|
| `python 未找到` | 安装 Python 3.9+，加到 PATH |
| `output.root 不存在` | run.ps1 会自动创建 |
| WIPO 检索一直超时 | 跑 `run.ps1 -Diagnose`，可能是网络被封/限流，换网络或等一会 |
| Excel 打不开 | Office 2016+ 应该没问题。脚本直接写 OOXML，无第三方依赖 |
| PDF 打开报错 | 脚本有 `%PDF` 头校验，真正的 PDF 没问题。如果是 `.html` 后缀那本来就是网页 |
