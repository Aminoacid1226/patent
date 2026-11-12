# patent-monitor-skill

可配置的专利监控 Skill —— 监控**任意主题**的专利：药物靶点、技术方向、材料、公司……全部由 `config.yaml` 定义，代码零硬编码。

纯 Python 标准库，零依赖，Windows / macOS / Linux 均可运行。

## 快速上手

### 方式 1：下载 ZIP 导入 Skill（推荐）

1. 下载 [patent-monitor-skill.zip](./patent-monitor-skill.zip)
2. Trae → 设置 → Skills → **导入** → 选 ZIP
3. 详细步骤看 [安装说明](./patent-monitor-安装说明.md)

### 方式 2：手动克隆

```bash
git clone https://github.com/Aminoacid1226/patent.git
```

把 `patent-monitor/` 复制到 `<工作区>/.trae/skills/`（项目级）或 `C:\Users\<你>\.trae-cn\skills\`（全局）。

## 定义监控项（核心）

编辑 `config.yaml → targets`，一个 key 就是一个监控项，名称任意：

```yaml
targets:
  固态电池:                      # 可以是任何主题：技术、材料、公司……
    keywords: '"solid-state battery" OR "solid electrolyte"'
    exclude_terms: []
    screening: generic           # pharma / generic / none
    wipo_field: "ALL"
```

筛选模式：

| 模式 | 行为 | 适用 |
|---|---|---|
| `generic`（默认） | 排除词过滤 + 关键词覆盖检查 | 任何主题 |
| `pharma` | 创新药筛选：保留药物/治疗相关，剔除诊断/器械/农用，推断技术方向 | 药物靶点 |
| `none` | 只做排除词过滤 | 公司/机构专利动向 |

内置示例：4 个药物靶点（TSHR/APJ/PCSK9/CYP51，pharma 模式）+ 固态电池、宁德时代两个通用模板（注释状态，取消注释即用）。

## 使用

对 AI 说：
- "帮我跑专利监控"
- "监控一下固态电池的专利"（先在 config 加监控项）

或命令行：

```powershell
patent-monitor\scripts\run.ps1                # 完整运行
patent-monitor\scripts\run.ps1 -Diagnose      # 健康检查
patent-monitor\scripts\run.ps1 -NoDownload    # 不下载 PDF（快）
patent-monitor\scripts\run.ps1 -FullRebuild   # 新增监控项后全量初建
```

## 两种检索模式

| | Web 模式（默认，零配置） | API 模式（商业数据库） |
|---|---|---|
| 数据源 | WIPO PATENTSCOPE + Google Patents | PatentHub / 智慧芽 / incoPat |
| 速度 | 分钟级 | 秒级 |
| API Key | 不需要 | 需要（config.yaml → api） |

## 自我审查机制

- 多源交叉验证（次级源结果 < 主源 30% 告警）
- 关键词覆盖度（自动从检索式解析关键词，无需手写）
- 数据缺失率 + 专利号格式检查
- PDF 强制 `%PDF` 头校验，失败降级 HTML
- 专利号标准化去重（同族不入库）

## License

MIT
