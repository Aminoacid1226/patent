"""
Markdown 报告 + Excel 汇总生成器

Markdown 报告结构：
  - 执行类型 + 检索窗口
  - 变更日志（简要表格）
  - 监控项摘要
  - 各专利详情（按监控项分组）
  - 自我审查发现
  - 趋势总评
  - 附录：下载文件清单 + 参考来源

Excel 汇总：
  - 四个工作表，名称固定为 TSHR / APJ / PCSK9 / CYP51
  - 追加模式：检查 (专利号, 公开日期) 是否已存在
"""
from __future__ import annotations

import datetime as dt
import html as html_mod
import json
import os
import re
import zipfile
from pathlib import Path
from typing import Any

from models import AuditIssue, COLS, PatentRecord, SearchResult


# ============================================================================
# Markdown 报告
# ============================================================================

def generate_markdown_report(
    path: Path,
    current_date: str,
    run_type: str,
    start_date: str | None,
    all_new: dict[str, list[PatentRecord]],
    errors: list[str],
    audit_issues: list[AuditIssue],
    search_results: list[SearchResult] | None = None,
) -> None:
    """生成完整 Markdown 报告"""
    total = sum(len(v) for v in all_new.values())
    lines: list[str] = []

    # 标题
    lines.append(f"# 专利监控报告 ({current_date})")
    lines.append("")
    lines.append(f"**执行类型**：{run_type}")
    lines.append("")
    if start_date:
        lines.append(f"**检索窗口**：{start_date} 至 {current_date}")
    else:
        lines.append(f"**检索窗口**：历史全量，截至 {current_date}")
    lines.append("")

    # 检索源耗时（有 search_results 时）
    if search_results:
        lines.append("**各源检索耗时**：")
        for sr in search_results:
            lines.append(f"  - {sr.source}@{sr.target}: {sr.elapsed_seconds}s, 返回 {sr.after_dedup_count} 条")
        lines.append("")

    # ── 变更日志 ──────────────────────────────────────────────────
    lines.append("## 变更日志（简要）")
    lines.append("")
    if total > 0:
        if run_type == "全量初建":
            lines.append(f"> 全量初建：累计收录 **{total}** 件专利")
            lines.append("")
        lines.append("| 监控项 | 本次新增专利号 |")
        lines.append("|---|---|")
        for target, rows in all_new.items():
            if rows:
                pubs = "；".join(r.publication_number for r in rows)
            else:
                pubs = "零更新"
            lines.append(f"| {target} | {pubs} |")
        lines.append("")
    else:
        lines.append("> **本次无新增专利**")
        lines.append("")

    # ── 监控项摘要 ──────────────────────────────────────────────────
    lines.append("## 监控项摘要")
    lines.append("")
    lines.append("| 监控项 | 本次新增 | 技术方向分布 |")
    lines.append("|---|---:|---|")
    for target, rows in all_new.items():
        direction_dist = _count_distribution([r.tech_direction for r in rows])
        dist_str = "、".join(f"{k}×{v}" for k, v in direction_dist.items()) if direction_dist else "-"
        lines.append(f"| {target} | {len(rows)} | {dist_str} |")
    lines.append("")

    # ── 各专利详情 ─────────────────────────────────────────────────
    lines.append("## 各专利详情")
    lines.append("")
    for target, rows in all_new.items():
        lines.append(f"### {target}")
        lines.append("")
        if not rows:
            lines.append("_本次无新增。_")
            lines.append("")
            continue
        for rec in rows:
            lines.append(f"#### {rec.publication_number} - {rec.title}")
            lines.append("")
            lines.append(f"- **申请人**：{rec.applicant or '未获取'}")
            lines.append(f"- **公开日期**：{rec.publication_date or '未获取'}")
            lines.append(f"- **来源**：{rec.source}")
            lines.append(f"- **技术方向**：{rec.tech_direction}")
            lines.append(f"- **用途/适应症**：{rec.indication}")
            lines.append(f"- **摘要**：{rec.abstract[:400]}{'...' if len(rec.abstract) > 400 else ''}")
            if rec._confidence < 1.0:
                lines.append(f"- ⚠️ **置信度**：{rec._confidence:.0%}（关键词覆盖或信息完整度不足）")
            lines.append("")

    # ── 自我审查发现 ────────────────────────────────────────────────
    if audit_issues:
        lines.append("## 自我审查发现")
        lines.append("")
        for issue in audit_issues:
            severity_icon = {"ERROR": "🔴", "WARNING": "🟡", "INFO": "🔵"}.get(issue.severity, "⚪")
            lines.append(f"- {severity_icon} [{issue.severity}] **{issue.category}**: {issue.message}")
            if issue.details:
                lines.append(f"  - {issue.details}")
        lines.append("")

    # ── 检索异常 ──────────────────────────────────────────────────
    if errors:
        lines.append("## 检索异常")
        lines.append("")
        for err in errors:
            lines.append(f"- {err}")
        lines.append("")

    # ── 趋势总评 ──────────────────────────────────────────────────
    lines.append("## 趋势总评")
    lines.append("")
    if total > 0:
        lines.append(_generate_trend_comment(all_new))
    else:
        lines.append("本次未发现新的监控项相关专利公开。")
    lines.append("")

    # ── 附录：下载文件 ──────────────────────────────────────────────
    lines.append("## 附录：下载文件清单及有效性")
    lines.append("")
    lines.append("| 监控项 | 专利号 | 本地文件 | 状态 |")
    lines.append("|---|---|---|---|")
    file_entries = 0
    for target, rows in all_new.items():
        for rec in rows:
            path_str = rec.local_path or "(未下载)"
            status = rec.download_status
            if path_str != "(未下载)":
                file_entries += 1
            lines.append(f"| {target} | {rec.publication_number} | {path_str} | {status} |")
    if file_entries == 0:
        lines.append("| - | - | - | 本次无下载 |")
    lines.append("")

    # ── 参考来源 ──────────────────────────────────────────────────
    lines.append("## 参考来源")
    lines.append("")
    if search_results:
        for sr in search_results:
            lines.append(f"### {sr.source} 检索结果 - {sr.target}")
            lines.append("")
            if sr.source == "wipo":
                start_c = sr.start_date.replace("-", "") if sr.start_date else "19700101"
                end_c = sr.end_date.replace("-", "")
                lines.append(f"- 检索 URL: https://patentscope.wipo.int/search/en/result.jsf?_afrWindowMode=0&query=ALL%3D%28{sr.target}%29+AND+DP%3A%5B{start_c}+TO+{end_c}%5D&sort=Pub+Date+Desc")
            elif sr.source == "google":
                lines.append(f"- Google Patents XHR 检索 (target={sr.target}, {sr.start_date or '不限'} ~ {sr.end_date})")
            # 每件新增专利的 WIPO 详情页
            if all_new.get(sr.target):
                lines.append("")
                lines.append("**新增专利详情页**：")
                for rec in all_new[sr.target]:
                    pub = rec.publication_number
                    lines.append(f"  - {pub}: https://patentscope.wipo.int/search/en/detail.jsf?docId={pub}")
            lines.append("")
    else:
        lines.append("_本次未记录检索源详情。_")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _count_distribution(items: list[str]) -> dict[str, int]:
    dist: dict[str, int] = {}
    for item in items:
        dist[item] = dist.get(item, 0) + 1
    return dict(sorted(dist.items(), key=lambda x: -x[1]))


def _generate_trend_comment(all_new: dict[str, list[PatentRecord]]) -> str:
    """自动生成趋势总评"""
    comments: list[str] = []
    for target, rows in all_new.items():
        if not rows:
            continue
        # 技术方向分布
        directions = _count_distribution([r.tech_direction for r in rows])
        top_direction = max(directions.items(), key=lambda x: x[1]) if directions else ("-", 0)
        comments.append(f"- **{target}**：新增 {len(rows)} 件，主流技术方向为「{top_direction[0]}」（{top_direction[1]}件）")
    return "\n".join(comments) if comments else "本次更新无明显趋势。"


# ============================================================================
# Excel 汇总（纯标准库，无 openpyxl 依赖）
# ============================================================================

class ExcelWriter:
    """
    使用 zipfile 直接写入 OOXML，生成多工作表 Excel。
    
    策略：每次从 records 数据**全量重建** Excel（records.json 是事实源）。
    这样不会丢失旧行，天然支持去重。
    """

    # 工作表 = 监控项名称，完全由 config.yaml 的 targets 节决定（动态）

    def __init__(self, xlsx_path: Path, targets: list[str] | None = None):
        self.xlsx_path = xlsx_path
        self.targets = targets  # None 时由 rebuild_all 从 records 的 key 推断

    def rebuild_all(self, records: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
        """
        全量重建 Excel 工作簿。

        Args:
            records: {target: [row_dict, ...]} 每条 dict 的 key 对应 COLS

        Returns:
            每个 target 的记录数
        """
        # 工作表清单：优先用传入的 targets（配置顺序），否则用 records 的 key
        sheet_names = self.targets or sorted(records.keys())
        # 合并 records 中有数据但不在配置里的 key（防御性）
        for k in records:
            if k not in sheet_names:
                sheet_names.append(k)

        self.xlsx_path.parent.mkdir(parents=True, exist_ok=True)
        counts: dict[str, int] = {}

        with zipfile.ZipFile(self.xlsx_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", _content_types_xml(len(sheet_names)))
            zf.writestr("_rels/.rels", _rels_xml())
            zf.writestr("xl/workbook.xml", _workbook_xml(sheet_names))
            zf.writestr("xl/_rels/workbook.xml.rels", _workbook_rels_xml(len(sheet_names)))
            zf.writestr("xl/styles.xml", _styles_xml())

            for idx, target in enumerate(sheet_names, start=1):
                rows = [COLS]
                target_rows = records.get(target, [])
                seen_keys: set[tuple[str, str]] = set()
                for rec in target_rows:
                    pub_no = str(rec.get("专利号", ""))
                    pub_date = str(rec.get("公开日期", ""))
                    key = (pub_no, pub_date)
                    if pub_no and key not in seen_keys:
                        seen_keys.add(key)
                        rows.append([rec.get(col, "") for col in COLS])
                counts[target] = len(rows) - 1  # 减去表头
                zf.writestr(f"xl/worksheets/sheet{idx}.xml", _sheet_xml(rows))

        return counts


# ============================================================================
# 辅助函数（纯 XML 构建）
# ============================================================================

def _xml_escape(value: str) -> str:
    return html_mod.escape(str(value), quote=True)


def _col_name(idx: int) -> str:
    """列索引（1-based）→ Excel 列名"""
    result = ""
    while idx:
        idx, rem = divmod(idx - 1, 26)
        result = chr(65 + rem) + result
    return result


def _content_types_xml(sheet_count: int) -> str:
    sheets = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, sheet_count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        f"{sheets}</Types>"
    )


def _rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    )


def _workbook_xml(names: list[str]) -> str:
    sheets = "".join(
        f'<sheet name="{_xml_escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
        for i, name in enumerate(names, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheets}</sheets></workbook>"
    )


def _workbook_rels_xml(sheet_count: int) -> str:
    rels = "".join(
        f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, sheet_count + 1)
    )
    rels += (
        f'<Relationship Id="rId{sheet_count + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{rels}</Relationships>"
    )


def _styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
        '</styleSheet>'
    )


def _sheet_xml(rows: list[list[Any]]) -> str:
    body: list[str] = []
    for r_idx, row in enumerate(rows, start=1):
        cells: list[str] = []
        for c_idx, value in enumerate(row, start=1):
            ref = f"{_col_name(c_idx)}{r_idx}"
            text = _xml_escape(str(value or ""))
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>')
        body.append(f'<row r="{r_idx}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'
        '<sheetData>'
        f"{''.join(body)}"
        '</sheetData></worksheet>'
    )
