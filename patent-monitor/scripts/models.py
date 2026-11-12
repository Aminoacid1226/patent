"""
专利检索流程 —— 公共类型定义与数据模型

所有模块共享的数据结构和常量定义。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Any, Literal, Optional


# ============================================================================
# 枚举 / 字面量类型
# ============================================================================

Mode = Literal["api", "web"]
RunType = Literal["initial", "update", "skip", "rebuild"]
Source = Literal["wipo", "google", "espacenet", "uspto", "patenthub", "zhihuia"]
# 监控项（target）不限于任何预设名单 —— 完全由 config.yaml 的 targets 节定义，
# 可以是药物靶点、技术主题、材料、公司等任意监控对象。

COLS = [
    "收录日期",
    "公开日期",
    "专利号",
    "标题",
    "申请人",
    "主题方向",
    "应用说明",
    "法律状态（如有）",
    "摘要要点",
    "本地文件路径",
    "报告来源",
]

# 旧版 records.json 列名 → 新列名（读取旧数据时自动映射）
LEGACY_COL_MAP = {
    "技术方向": "主题方向",
    "用途/适应症": "应用说明",
}


# ============================================================================
# 核心数据类
# ============================================================================

@dataclass
class PatentRecord:
    """单条专利记录（统一格式）"""
    target: str                                    # TSHR / APJ / PCSK9 / CYP51
    publication_number: str                        # 专利号，已标准化
    publication_date: str                          # YYYY-MM-DD
    title: str                                     # 英文标题
    title_zh: str = ""                             # 中文翻译（可选）
    applicant: str = ""
    abstract: str = ""
    source: str = ""                               # 数据来源
    # 筛选后填充
    is_innovation_drug: bool = True
    tech_direction: str = "未分类"
    indication: str = ""
    legal_status: str = ""
    # 下载后填充
    local_path: str = ""
    download_status: str = "未下载"
    # 内部字段（不写入 Excel）
    _confidence: float = 1.0                       # 筛选置信度 0~1
    _raw_keywords: list[str] = field(default_factory=list)

    @property
    def dedup_key(self) -> tuple[str, str]:
        """去重键：(靶点, 专利号)"""
        return (self.target, normalize_pub_no(self.publication_number))

    def to_excel_row(self, collect_date: str, report_name: str) -> dict[str, Any]:
        """转为 Excel 行格式"""
        return {
            "收录日期": collect_date,
            "公开日期": self.publication_date,
            "专利号": normalize_pub_no(self.publication_number),
            "标题": self.title_zh or self.title,
            "申请人": self.applicant,
            "主题方向": self.tech_direction,
            "应用说明": self.indication,
            "法律状态（如有）": self.legal_status,
            "摘要要点": self.abstract[:500] if self.abstract else "",
            "本地文件路径": self.local_path,
            "报告来源": report_name,
        }


@dataclass
class SearchResult:
    """一次检索的完整结果"""
    target: str
    source: str                                   # wipo / google / ...
    start_date: Optional[str]                     # YYYY-MM-DD
    end_date: str
    records: list[PatentRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    # 元数据
    raw_result_count: int = 0                      # 原始返回数（可能重复/不精确）
    after_dedup_count: int = 0                     # 去重后数量


@dataclass
class RunState:
    """运行状态（对应 task_state.json）"""
    last_date: str = ""                           # YYYY-MM-DD
    last_type: str = ""                           # initial / update
    last_run_at: str = ""                         # ISO 时间戳
    status: str = ""                              # success / failed / partial
    new_records_total: int = 0
    new_patents_by_target: dict[str, list[str]] = field(default_factory=dict)
    report_path: str = ""
    excel_path: str = ""
    cumulative_totals: dict[str, int] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "RunState":
        return cls(**{k: data.get(k, "") for k in cls.__dataclass_fields__})


@dataclass
class AuditIssue:
    """自我审查发现的问题"""
    severity: Literal["ERROR", "WARNING", "INFO"]
    category: str                                  # 完整性 / 准确性 / 覆盖率 / 去重 / PDF校验
    message: str
    details: str = ""


# ============================================================================
# 工具函数
# ============================================================================

_PUB_NO_CLEAN_RE = re.compile(r"[^A-Za-z0-9]")


def normalize_pub_no(pub_no: str) -> str:
    """
    标准化专利号：去连字符、去空格、大写
    
    示例：
      "WO/2024/005113" → "WO2024005113"
      "US 10,596,168 B2" → "US10596168B2"
      "EP 4 831 285 A1" → "EP4831285A1"
    """
    if not pub_no:
        return ""
    return _PUB_NO_CLEAN_RE.sub("", pub_no).upper()


def normalize_date(value: Any) -> str:
    """
    统一日期格式为 YYYY-MM-DD
    
    支持输入：
      - "20261110" → "2026-11-10"
      - "2026-11-10" → 原样
      - "10.11.2026" (DD.MM.YYYY) → "2026-11-10"
      - datetime/date 对象 → isoformat
    """
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    # YYYYMMDD
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    # YYYY-MM-DD / YYYY/MM/DD
    if re.fullmatch(r"\d{4}[-/]\d{2}[-/]\d{2}", text):
        return text.replace("/", "-")
    # DD.MM.YYYY / DD/MM/YYYY
    m = re.fullmatch(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", text)
    if m:
        d, mo, y = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    # 无法识别，原样返回
    return text


def today_iso() -> str:
    return date.today().isoformat()


def safe_filename(text: str) -> str:
    """替换 Windows 文件名非法字符"""
    return re.sub(r'[\\/:*?"<>|]+', "_", str(text))


def ensure_dir(path: Any) -> Any:
    from pathlib import Path
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p
