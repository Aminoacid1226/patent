"""
创新药专利筛选 + 自我审查模块

筛选逻辑：
  1. 规则匹配 —— 保留药物/治疗相关，剔除诊断/器械/农用
  2. 关键词覆盖度检查 —— 验证标题+摘要是否确实包含靶点关键词
  3. 排除词过滤 —— 如 CYP51 排除髓鞘再生、APJ 排除通信 Access Point

自我审查（Audit）：
  - 多源交叉验证：某源结果数异常偏少则告警
  - 关键词覆盖率：标题+摘要未含关键词的比例
  - 数据缺失率：关键字段（标题、申请人、日期）为空的比例
  - 去重完整性：公开号标准化后检查同族重复
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from models import AuditIssue, PatentRecord, SearchResult


# ============================================================================
# 创新药筛选规则
# ============================================================================

# 命中 → 判定为创新药相关
KEEP_RE = re.compile(
    r"\b("
    r"compound|composition|pharmaceutical|therapeutic|treat(?:ment|ing)?|therapy|"
    r"drug|antibody|inhibitor|agonist|antagonist|inverse agonist|"
    r"siRNA|antisense|gene therapy|cell therapy|fusion protein|"
    r"peptide|polypeptide|vaccine|small molecule|modulator|"
    r"macrolide|azole|antifungal|antibiotic"
    r")\b",
    re.I,
)

# 命中且未同时命中 KEEP → 判定为应剔除
DROP_RE = re.compile(
    r"\b("
    r"diagnostic kit|diagnosis only|detection kit|screening method|"
    r"device|apparatus|implant|catheter|stent|"
    r"agricultural|pesticide|herbicide|fertilizer|"
    r"food additive|feed additive"
    r")\b",
    re.I,
)


# ============================================================================
# 技术方向判定
# ============================================================================

DIRECTION_MAP: dict[str, str] = {
    "antibody": "抗体/蛋白药",
    "siRNA": "核酸药物/siRNA",
    "antisense": "核酸药物/反义",
    "gene therapy": "基因疗法",
    "fusion protein": "融合蛋白",
    "peptide": "多肽药物",
    "polypeptide": "多肽药物",
    "vaccine": "疫苗",
    "agonist": "小分子激动剂",
    "antagonist": "小分子拮抗剂",
    "inhibitor": "小分子抑制剂",
    "inverse agonist": "小分子反向激动剂",
    "modulator": "小分子调节剂",
    "antifungal": "抗真菌药",
    "azoe": "唑类抗真菌",
}


def infer_direction(blob: str) -> str:
    """从文本推断技术方向"""
    lower = blob.lower()
    for key, label in DIRECTION_MAP.items():
        if key in lower:
            return label
    if "antibody" in lower:
        return "抗体/蛋白药"
    return "小分子/药物组合物"


def infer_indication(blob: str) -> str:
    """从文本推断用途/适应症"""
    patterns = [
        r"treat(?:ing|ment)? of ([^.；;\n]{3,150})",
        r"for ([^.；;\n]{3,150})",
        r"用于([^。；;\n]{3,100})",
        r"indications?[:\s]+([^.；;\n]{3,150})",
    ]
    for pattern in patterns:
        m = re.search(pattern, blob, re.I)
        if m:
            text = m.group(1).strip()
            # 去除尾部连接词
            text = re.split(r"[,;.;\s]+and\s+", text)[0].strip()
            if 3 <= len(text) <= 150:
                return text
    return "未明确/待从全文复核"


# ============================================================================
# 筛选主流程
# ============================================================================

def screen_records(
    records: list[PatentRecord],
    target: str,
    exclude_terms: list[str] | None = None,
) -> tuple[list[PatentRecord], list[AuditIssue]]:
    """
    对检索到的专利记录执行创新药筛选 + 关键词覆盖检查。
    
    Returns:
        (筛选后的记录列表, 审查发现的问题列表)
    """
    issues: list[AuditIssue] = []
    passed: list[PatentRecord] = []
    excluded_count = 0
    keyword_miss_count = 0
    invalid_count = 0

    # 靶点关键词（简化：从 PatentRecord 内部字段读取，或用 target 名称兜底）
    target_keyword_hints = _get_target_keyword_hints(target)

    for rec in records:
        blob = f"{rec.title} {rec.abstract}"
        blob_lower = blob.lower()

        # Step 1: 排除词过滤
        if exclude_terms:
            matched_exclude = [t for t in exclude_terms if t.lower() in blob_lower]
            if matched_exclude:
                excluded_count += 1
                issues.append(AuditIssue(
                    severity="WARNING",
                    category="排除词过滤",
                    message=f"专利 {rec.publication_number} 命中排除词: {matched_exclude}",
                    details=f"靶点 {target}，申请人 {rec.applicant}",
                ))
                continue

        # Step 2: 关键词覆盖检查（是否包含靶点关键词）
        has_keyword = any(hint.lower() in blob_lower for hint in target_keyword_hints)
        if not has_keyword:
            keyword_miss_count += 1
            issues.append(AuditIssue(
                severity="WARNING",
                category="关键词覆盖度",
                message=f"专利 {rec.publication_number} 标题+摘要未包含靶点关键词",
                details=f"靶点 {target}，标题: {rec.title[:80]}...",
            ))
            # 不直接剔除，降低置信度但保留
            rec._confidence = 0.3
            rec._raw_keywords = ["无关键词匹配 - 存疑"]

        # Step 3: 创新药判定
        is_keep = KEEP_RE.search(blob) is not None
        is_drop = DROP_RE.search(blob) is not None

        if is_drop and not is_keep:
            # 明确应剔除
            excluded_count += 1
            continue

        if not is_keep and not is_drop:
            # 既没命中保留也没命中剔除 → 存疑，保留但降低置信度
            rec._confidence = min(rec._confidence, 0.5)
            rec.tech_direction = "存疑（无治疗关键词匹配）"
            rec.indication = "待人工复核"
        else:
            rec.is_innovation_drug = True
            rec.tech_direction = infer_direction(blob)
            rec.indication = infer_indication(blob)

        passed.append(rec)

    # 汇总统计问题
    total = len(records)
    if total > 0:
        keyword_miss_ratio = keyword_miss_count / total
        if keyword_miss_ratio > 0.2:
            issues.append(AuditIssue(
                severity="ERROR" if keyword_miss_ratio > 0.5 else "WARNING",
                category="关键词覆盖度",
                message=f"靶点 {target} 有 {keyword_miss_count}/{total} 条记录未命中关键词（{keyword_miss_ratio:.0%}）",
                details="可能是检索式过宽或检索源质量问题，建议人工复核",
            ))

    return passed, issues


def _get_target_keyword_hints(target: str) -> list[str]:
    """获取靶点的关键词提示列表（用于覆盖度检查）"""
    hints = {
        "TSHR": ["tshr", "thyroid stimulating hormone receptor", "thyrotropin receptor"],
        "APJ": ["apj", "aplnr", "apelin receptor"],
        "PCSK9": ["pcsk9", "proprotein convertase subtilisin", "kexin type 9"],
        "CYP51": ["cyp51", "cytochrome p450 51", "sterol 14", "14α-demethylase", "14-alpha-demethylase", "lanosterol"],
    }
    return hints.get(target, [target.lower()])


# ============================================================================
# 多源交叉验证
# ============================================================================

@dataclass
class CrossSourceReport:
    """多源交叉验证结果"""
    issues: list[AuditIssue] = field(default_factory=list)
    source_counts: dict[str, int] = field(default_factory=dict)
    primary_source: str = ""
    primary_count: int = 0


def cross_source_verify(
    results: list[SearchResult],
    audit_cfg: dict[str, Any],
) -> CrossSourceReport:
    """
    多源交叉验证
    
    检查：
      - 各源结果数量分布是否合理
      - 主源结果过少可能意味着检索异常
      - 各源之间的关键词覆盖度差异
    """
    report = CrossSourceReport()
    if not results:
        return report

    min_ratio = audit_cfg.get("min_source_ratio", 0.3)
    coverage_threshold = audit_cfg.get("min_keyword_coverage", 0.8)

    # 统计各源数量
    source_counts: dict[str, int] = {}
    for r in results:
        source_counts[r.source] = r.after_dedup_count
    report.source_counts = source_counts

    # 主源 = 结果最多的源
    primary = max(source_counts.items(), key=lambda x: x[1])
    report.primary_source = primary[0]
    report.primary_count = primary[1]

    for source, count in source_counts.items():
        if source == primary[0]:
            continue
        if primary[1] == 0:
            continue
        ratio = count / primary[1]
        if count == 0:
            report.issues.append(AuditIssue(
                severity="WARNING",
                category="多源交叉验证",
                message=f"源 {source} 返回 0 条结果，主源 {primary[0]} 返回 {primary[1]} 条",
                details=f"可能是检索异常或源本身无数据",
            ))
        elif ratio < min_ratio:
            report.issues.append(AuditIssue(
                severity="WARNING",
                category="多源交叉验证",
                message=f"源 {source} 结果数（{count}）仅为主源 {primary[0]}（{primary[1]}）的 {ratio:.0%}",
                details=f"低于阈值 {min_ratio:.0%}，可能存在检索偏差",
            ))

    # 关键词覆盖率检查
    keyword_hints_cache: dict[str, list[str]] = {}
    for result in results:
        hints = _get_target_keyword_hints(result.target)
        keyword_hints_cache[result.target] = hints
        if not result.records:
            continue
        miss = 0
        for rec in result.records:
            blob = f"{rec.title} {rec.abstract}".lower()
            if not any(h.lower() in blob for h in hints):
                miss += 1
        coverage = 1 - miss / len(result.records)
        if coverage < coverage_threshold:
            report.issues.append(AuditIssue(
                severity="WARNING",
                category="关键词覆盖率",
                message=f"{result.target}@{result.source}: 关键词覆盖率仅 {coverage:.0%} ({len(result.records) - miss}/{len(result.records)})",
                details=f"低于阈值 {coverage_threshold:.0%}",
            ))

    return report


# ============================================================================
# 数据完整性检查
# ============================================================================

def check_data_quality(records: list[PatentRecord], audit_cfg: dict[str, Any]) -> list[AuditIssue]:
    """
    数据完整性检查
    
    - 关键字段（标题、申请人、公开日期）为空的比例
    - 公开号格式异常
    """
    issues: list[AuditIssue] = []
    if not records:
        return issues

    max_null = audit_cfg.get("max_null_ratio", 0.05)
    total = len(records)

    null_title = sum(1 for r in records if not r.title.strip())
    null_applicant = sum(1 for r in records if not r.applicant.strip())
    null_date = sum(1 for r in records if not r.publication_date.strip())

    for field, null_count in [("标题", null_title), ("申请人", null_applicant), ("公开日期", null_date)]:
        ratio = null_count / total
        if ratio > max_null:
            issues.append(AuditIssue(
                severity="WARNING",
                category="数据完整性",
                message=f"{field} 为空的比例 {ratio:.0%}（{null_count}/{total}）",
                details=f"超过阈值 {max_null:.0%}",
            ))

    # 公开号格式检查
    bad_format = []
    for r in records:
        pub = r.publication_number
        if not re.match(r'^[A-Z]{2}\d+[A-Z]?\d*$', pub):
            bad_format.append(pub)
    if bad_format:
        issues.append(AuditIssue(
            severity="INFO",
            category="公开号格式",
            message=f"有 {len(bad_format)} 条专利号格式非标准",
            details=f"样例: {bad_format[:5]}",
        ))

    return issues
