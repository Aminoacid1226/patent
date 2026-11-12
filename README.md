# patent-monitor-skill

多靶点创新药专利监控 Skill，监控 **TSHR**（甲状腺刺激激素受体）/ **APJ**（Apelin receptor）/ **PCSK9**（降脂靶点）/ **CYP51**（真菌抗真菌靶点）四个靶点。

纯 Python 标准库，零依赖，Windows / macOS / Linux 均可运行。

## 快速上手

### 方式 1：下载 ZIP 导入 Skill（推荐）

1. 从本仓库根目录下载 [patent-monitor-skill.zip](./patent-monitor-skill.zip)
2. Trae → 设置 → Skills → **导入** → 选这个 ZIP
3. 详细步骤看 [安装说明](./patent-monitor-安装说明.md)

### 方式 2：手动克隆整个仓库

`ash
git clone https://github.com/Aminoacid1226/patent.git
`

然后把 patent-monitor/ 目录整个复制到：

| 场景 | 路径 |
|---|---|
| 本项目专用 | <工作区>/.trae/skills/patent-monitor/ |
| 全局所有项目 | C:\Users\<你>\.trae-cn\skills\patent-monitor\ |

## 使用

让 AI 说一句就能触发：
- "帮我跑专利监控"
- "TSHR 最近有没有新专利"
- "patent monitor"

或者命令行：

`powershell
patent-monitor\scripts\run.ps1                # 完整运行
patent-monitor\scripts\run.ps1 -Diagnose     # 健康检查
patent-monitor\scripts\run.ps1 -NoDownload   # 不下载 PDF（快）
`

## 两种检索模式

| | Web 模式（默认，零配置） | API 模式（商业数据库） |
|---|---|---|
| 数据源 | WIPO PATENTSCOPE + Google Patents | PatentHub / 智慧芽 / incoPat |
| 速度 | 分钟级 | 秒级 |
| 是否要 API Key | 否 | 是 |

## 文件清单

`
patent-monitor/
├── SKILL.md                     ← Skill 指令
└── scripts/
    ├── run.ps1                  ← 一键入口（推荐用这个）
    ├── run_monitor.py           ← 主流程
    ├── diagnose.py              ← 健康检查
    ├── screening.py             ← 创新药筛选 + 自我审查
    ├── downloader.py            ← PDF 下载 + %PDF 校验
    ├── reporter.py              ← Markdown + Excel 生成
    ├── models.py
    ├── config_loader.py
    ├── config.example.yaml      ← 配置模板
    ├── register_windows_task.ps1
    └── retriever/
        ├── __init__.py
        ├── web_retriever.py
        └── api_retriever.py
`

## License

MIT
