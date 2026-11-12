# patent-monitor Skill — 安装说明

可配置的专利监控 Skill —— 监控**任意主题**的专利（药物靶点、技术方向、材料、公司……），全部由 `config.yaml` 定义。

纯 Python 标准库（零依赖），Windows / macOS / Linux 均可运行。

---

## 前置条件

- Python 3.9+（PATH 里能直接调 `python` 或 `python3`）
- Trae IDE（或支持 Skill 的 Trae 产品）

---

## 安装方式（三选一）

### 方式 1：ZIP 导入（推荐）

1. 下载本仓库根目录的 `patent-monitor-skill.zip`
2. Trae → 设置 → Skills → **导入** → 选 ZIP

### 方式 2：手动放目录

把 `patent-monitor/` 整个目录复制到：

| 场景 | 路径 |
|---|---|
| 本项目专用 | `<工作区>/.trae/skills/patent-monitor/` |
| 全局所有项目 | `C:\Users\<你>\.trae-cn\skills\patent-monitor\`（CN 版）<br>`C:\Users\<你>\.trae\skills\patent-monitor\`（国际版） |

### 方式 3：让 AI 安装

在 Trae 里说："帮我从 GitHub 安装 https://github.com/Aminoacid1226/patent"

---

## 首次配置（必须做）

```powershell
# 1. 复制配置模板
copy patent-monitor\scripts\config.example.yaml ^
      patent-monitor\scripts\config.yaml

# 2. 编辑 config.yaml：
#    ① output.root → 改成你想存放输出的目录（建议绝对路径）
#    ② targets 节 → 定义你要监控的对象（见下节）
```

---

## 定义监控项（核心功能）

`targets` 下每个 key 就是一个监控项，**名称和数量完全自定义**：

```yaml
targets:
  # 药物靶点（创新药筛选模式）
  TSHR:
    keywords: 'TSHR OR "thyroid stimulating hormone receptor" OR thyrotropin'
    therapy_filter: 'AND (treatment OR therapeutic OR pharmaceutical OR drug)'
    exclude_terms: []
    screening: pharma
    wipo_field: "ALL"

  # 技术主题（通用模式）
  固态电池:
    keywords: '"solid-state battery" OR "solid electrolyte"'
    therapy_filter: ''
    exclude_terms: []
    screening: generic
    wipo_field: "ALL"

  # 公司专利动向（不过滤模式）
  宁德时代:
    keywords: '"CATL" OR "Contemporary Amperex" OR "宁德时代"'
    therapy_filter: ''
    exclude_terms: []
    screening: none
    wipo_field: "ALL"
```

### 筛选模式说明

| 模式 | 行为 | 适用场景 |
|---|---|---|
| `generic`（默认） | 排除词过滤 + 关键词覆盖检查 | 任何技术主题 |
| `pharma` | 创新药筛选：保留药物/治疗相关，剔除诊断/器械/农用，自动推断技术方向 | 药物靶点 |
| `none` | 只做排除词过滤，其余全部保留 | 公司/机构动向 |

### 添加监控项后

```powershell
# 新监控项需要全量初建
patent-monitor\scripts\run.ps1 -FullRebuild
```

---

## 使用

### 让 AI 自动触发

在 Trae 里说："帮我跑专利监控"、"监控固态电池最近的新专利"。

### 命令行

```powershell
patent-monitor\scripts\run.ps1                # 完整运行
patent-monitor\scripts\run.ps1 -Diagnose      # 健康检查（首次必跑）
patent-monitor\scripts\run.ps1 -NoDownload    # 不下载 PDF（快很多）
patent-monitor\scripts\run.ps1 -FullRebuild   # 全量重建
patent-monitor\scripts\run.ps1 -Target 固态电池  # 只跑某个监控项
```

### 定时任务

```powershell
cd patent-monitor\scripts
.\register_windows_task.ps1 -Weekly -Weekday 1 -Hour 8 -Minute 0
```

---

## 输出产物

```
output.root/
├── task_state.json           ← 运行状态
├── patent_summary.xlsx       ← Excel 汇总（工作表 = 监控项，自动跟随配置）
├── patent_records.json       ← 完整记录
├── reports/                  ← Markdown 报告（带时间戳）
└── patents/{监控项}/          ← 下载的 PDF/HTML
```

---

## 常见问题

**Q: 想监控多个主题？** 在 `targets` 下加多个节点即可，Excel 自动生成对应工作表。

**Q: 检索结果太多/太杂？** 加 `exclude_terms` 排除词，或在 `keywords` 用引号短语精确化，必要时把 `wipo_field` 改成 `TI`（仅标题）或 `AB`（仅摘要）。

**Q: 跑起来慢？** Web 模式从 WIPO 逐条抓详情页（每监控项 30~120 秒）。用 `-NoDownload` 先看结果。

**Q: WIPO 返回 0 条？** 可能被验证码拦截，跑 `-Diagnose` 确认，等几分钟重试。

**Q: 旧版（4 个写死靶点）的数据还能用吗？** 能。`records.json` 里的旧列名（技术方向/用途/适应症）会自动映射到新列名（主题方向/应用说明）。
