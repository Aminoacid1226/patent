"""
run_monitor.py —— 专利检索流程主入口

使用方式：
  # 默认：读取 config.yaml，执行一次完整监控
  python run_monitor.py

  # 全量重建（忽略 state）
  python run_monitor.py --full-rebuild

  # 指定配置文件
  python run_monitor.py --config my_config.yaml

  # 仅检索，不下载全文
  python run_monitor.py --no-download

  # 指定日期（模拟定时任务）
  python run_monitor.py --date 2026-11-12

  # 仅检索某靶点
  python run_monitor.py --target TSHR --target APJ

  # 强制指定模式
  python run_monitor.py --mode web

退出码：
  0 = 成功（零更新也算成功）
  1 = 部分成功（部分源失败）
  2 = 失败（所有源都失败或关键流程异常）
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

# 确保能导入同级模块
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config_loader import load_config
from models import (
    AuditIssue,
    PatentRecord,
    RunState,
    SearchResult,
    RunType,
    ensure_dir,
    today_iso,
)
from retriever import Retriever
from retriever.web_retriever import create_web_retriever
from retriever.api_retriever import create_api_retriever
from screening import (
    cross_source_verify,
    screen_records,
    check_data_quality,
)
from downloader import ApplicantAbbrManager, PatentDownloader
from reporter import generate_markdown_report, ExcelWriter


# ============================================================================
# 日志
# ============================================================================

class SimpleLogger:
    """极简日志（纯标准库）"""

    LEVELS = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3}

    def __init__(self, level: str = "INFO", file_path: Any = None):
        self.level = self.LEVELS.get(level.upper(), 1)
        self.file_path = Path(file_path) if file_path else None
        if self.file_path:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def _log(self, level: str, msg: str) -> None:
        if self.LEVELS[level] < self.level:
            return
        ts = dt.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] [{level}] {msg}"
        print(line, flush=True)
        if self.file_path:
            with self.file_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    def debug(self, msg: str) -> self: self._log("DEBUG", msg); return self
    def info(self, msg: str) -> self: self._log("INFO", msg); return self
    def warning(self, msg: str) -> self: self._log("WARNING", msg); return self
    def error(self, msg: str) -> self: self._log("ERROR", msg); return self


# ============================================================================
# 主流程编排
# ============================================================================

class PatentMonitor:
    """
    专利监控主类
    
    编排顺序：
      1. 加载配置 → 确定运行模式、靶点、输出目录
      2. 决定本次执行类型（全量/增量/跳过）
      3. 多源检索 → 去重合并
      4. 创新药筛选 + 自我审查
      5. 全文下载（可选）
      6. 生成 Markdown 报告 + 追加 Excel
      7. 更新 task_state.json
    """

    def __init__(self, config_path: Optional[str] = None):
        self.cfg = load_config(config_path)
        self.logger = SimpleLogger(
            level=self.cfg.get("logging", {}).get("level", "INFO"),
            file_path=self.cfg.get("logging", {}).get("file"),
        )

        # 输出路径
        out_cfg = self.cfg.get("output", {})
        self.root = Path(out_cfg.get("root", "patent_monitor")).resolve()
        self.report_dir = ensure_dir(self.root / out_cfg.get("report_dir", "reports"))
        self.patent_dir = ensure_dir(self.root / out_cfg.get("patent_dir", "patents"))
        self.excel_path = self.root / out_cfg.get("excel_file", "patent_summary.xlsx")
        self.state_path = self.root / out_cfg.get("state_file", "task_state.json")
        self.abbr_path = self.root / out_cfg.get("abbr_file", "applicant_abbr.json")
        self.records_path = self.root / out_cfg.get("records_file", "patent_records.json")

        # 运行参数（会被 CLI 覆盖）
        self.run_mode = self.cfg.get("mode", "web")
        self.full_rebuild = self.cfg.get("execution", {}).get("full_rebuild", False)
        self.do_download = True
        self.targets_filter: Optional[list[str]] = None
        self.override_date: Optional[str] = None

        # 状态
        self.state: RunState = self._load_state()
        self._existing_records: dict[str, list[dict[str, Any]]] = self._load_records()
        self.abbr_manager = ApplicantAbbrManager(self.abbr_path)

    # ── 状态管理 ──────────────────────────────────────────────────────

    def _load_state(self) -> RunState:
        if self.state_path.exists():
            try:
                with self.state_path.open("r", encoding="utf-8") as f:
                    return RunState.from_json(json.load(f))
            except Exception:
                pass
        return RunState()

    def _load_records(self) -> dict[str, list[dict[str, Any]]]:
        if self.records_path.exists():
            try:
                with self.records_path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {t: [] for t in self.cfg.get("targets", {})}

    def _save_state(self) -> None:
        data = self.state.to_json()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _save_records(self) -> None:
        with self.records_path.open("w", encoding="utf-8") as f:
            json.dump(self._existing_records, f, ensure_ascii=False, indent=2)

    # ── 执行类型决策 ──────────────────────────────────────────────────

    def decide_run(self, current_date: str) -> tuple[RunType, Optional[str], str]:
        """
        返回 (run_type, start_date, window_description)
        
        - initial:  首次运行 / 强制全量，从 1970-01-01 起
        - update:   增量，从 last_date + 1 天起
        - skip:     距上次不足 2 天，跳过
        """
        if self.full_rebuild:
            return "initial", None, "全量重建（忽略 state）"

        if not self.state.last_date:
            return "initial", None, "首次运行"

        last = dt.date.fromisoformat(self.state.last_date)
        curr = dt.date.fromisoformat(current_date)
        gap = (curr - last).days

        # 定时任务隔日规则（来自原始提示词）
        if self.state.last_type in ("initial", "", None):
            # 全量后的第一次增量，即使只隔一天也允许
            if gap >= 1:
                start = (last + dt.timedelta(days=1)).isoformat()
                return "update", start, f"增量更新（窗口 {start} ~ {current_date}）"
        else:
            # 距上次增量不足 2 天 → 跳过
            if gap < 2:
                return "skip", None, f"距上次 {gap} 天，按隔日规则跳过"
            start = (last + dt.timedelta(days=1)).isoformat()
            return "update", start, f"增量更新（窗口 {start} ~ {current_date}）"

        start = (last + dt.timedelta(days=1)).isoformat()
        return "update", start, f"增量更新（窗口 {start} ~ {current_date}）"

    # ── 检索 ──────────────────────────────────────────────────────────

    def _create_retrievers(self) -> list[Retriever]:
        """根据 mode 创建检索器列表"""
        retrievers: list[Retriever] = []
        if self.run_mode == "api":
            retrievers.append(create_api_retriever(self.cfg))
        else:
            for source in self.cfg.get("web", {}).get("sources", ["wipo", "google"]):
                try:
                    retrievers.append(create_web_retriever(source, self.cfg))
                except Exception as e:
                    self.logger.warning(f"跳过检索源 {source}: {e}")
        return retrievers

    def _get_targets(self) -> dict[str, dict[str, Any]]:
        targets = self.cfg.get("targets", {})
        if self.targets_filter:
            targets = {k: v for k, v in targets.items() if k in self.targets_filter}
        return targets

    def run_search(
        self,
        retrievers: list[Retriever],
        targets: dict[str, dict[str, Any]],
        start_date: Optional[str],
        end_date: str,
    ) -> tuple[list[SearchResult], dict[str, list[PatentRecord]]]:
        """
        执行多源多靶点检索
        
        Returns:
            (所有 SearchResult 列表, 按靶点合并去重后的 PatentRecord 列表)
        """
        all_results: list[SearchResult] = []
        merged: dict[str, dict[tuple[str, str], PatentRecord]] = {}

        for target, tgt_cfg in targets.items():
            merged.setdefault(target, {})
            keywords = tgt_cfg.get("keywords", "")
            therapy_filter = tgt_cfg.get("therapy_filter", "")

            for retriever in retrievers:
                self.logger.info(f"检索 {target} @ {retriever.source_name} ...")
                try:
                    sr = retriever.search_with_timing(
                        target, keywords, therapy_filter, start_date, end_date
                    )
                except Exception as e:
                    self.logger.error(f"检索 {target} @ {retriever.source_name} 异常: {e}")
                    sr = SearchResult(
                        target=target, source=getattr(retriever, "source_name", "unknown"),
                        start_date=start_date, end_date=end_date,
                        errors=[str(e)],
                    )

                all_results.append(sr)

                # 合并到去重表
                for rec in sr.records:
                    key = rec.dedup_key
                    existing = merged[target].get(key)
                    if existing is None:
                        merged[target][key] = rec
                    else:
                        # 已存在 → 补充缺失字段（WIPO 数据通常更完整）
                        _merge_records(existing, rec, prefer_source=sr.source)

                self.logger.info(
                    f"  → {sr.source}: {sr.after_dedup_count} 条有效"
                    + (f" (原始 {sr.raw_result_count})" if sr.raw_result_count else "")
                    + (f" [{sr.elapsed_seconds}s]" if sr.elapsed_seconds else "")
                )

        # 转为 list
        merged_list: dict[str, list[PatentRecord]] = {
            target: list(recs.values()) for target, recs in merged.items()
        }
        return all_results, merged_list

    # ── 主执行 ────────────────────────────────────────────────────────

    def run(self) -> int:
        current = self.override_date or today_iso()
        self.logger.info(f"===== 专利监控启动 (current={current}, mode={self.run_mode}) =====")
        self.logger.info(f"输出目录: {self.root}")

        # 1. 决定执行类型
        run_type, start_date, window_desc = self.decide_run(current)
        self.logger.info(f"执行类型: {run_type} — {window_desc}")

        if run_type == "skip":
            self.logger.info("本次跳过，生成存活确认报告")
            self._write_skip_report(current, window_desc)
            return 0

        targets = self._get_targets()
        self.logger.info(f"监控靶点: {list(targets.keys())}")

        # 2. 检索
        retrievers = self._create_retrievers()
        if not retrievers:
            self.logger.error("没有可用的检索源！检查配置。")
            return 2

        all_results, merged = self.run_search(retrievers, targets, start_date, current)

        # 3. 筛选 + 自我审查
        audit_issues: list[AuditIssue] = []
        screened: dict[str, list[PatentRecord]] = {}

        # 多源交叉验证
        if self.cfg.get("audit", {}).get("cross_source_verify", True):
            for target in targets:
                tgt_results = [r for r in all_results if r.target == target]
                cs_report = cross_source_verify(tgt_results, self.cfg.get("audit", {}))
                audit_issues.extend(cs_report.issues)

        # 各靶点独立筛选
        for target, recs in merged.items():
            exclude_terms = targets.get(target, {}).get("exclude_terms", [])
            passed, issues = screen_records(recs, target, exclude_terms)
            screened[target] = passed
            audit_issues.extend(issues)

        # 数据完整性检查
        all_screened = [r for recs in screened.values() for r in recs]
        audit_issues.extend(check_data_quality(all_screened, self.cfg.get("audit", {})))

        self.logger.info(
            f"筛选后专利数: "
            + ", ".join(f"{t}={len(recs)}" for t, recs in screened.items())
        )

        # 4. 去重（与已有记录对比）
        known_keys: set[tuple[str, str]] = set()
        for t, rows in self._existing_records.items():
            for row in rows:
                known_keys.add((t, row.get("专利号", ""), row.get("公开日期", "")))

        truly_new: dict[str, list[PatentRecord]] = {}
        for target, recs in screened.items():
            new_list = []
            for rec in recs:
                key = (target, rec.publication_number, rec.publication_date)
                if key not in known_keys and rec.publication_number:
                    new_list.append(rec)
                    known_keys.add(key)
            truly_new[target] = new_list

        total_new = sum(len(v) for v in truly_new.values())
        self.logger.info(f"与已有记录去重后，新增 {total_new} 件")

        # 5. 下载全文（可选，并发）
        if self.do_download and total_new > 0:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            self.logger.info("开始下载专利全文（并发）...")
            downloader = PatentDownloader(
                patent_dir=self.patent_dir,
                abbr_manager=self.abbr_manager,
                timeout=90,
            )
            dl_cfg = self.cfg.get("web", {}).get("http", {})
            if dl_cfg.get("user_agent"):
                downloader.user_agent = dl_cfg["user_agent"]

            workers = self.cfg.get("execution", {}).get("concurrency", {}).get("download_workers", 4)
            all_download_tasks = [(t, r) for t, recs in truly_new.items() for r in recs]
            success_count = 0
            fail_count = 0

            with ThreadPoolExecutor(max_workers=workers) as pool:
                future_map = {pool.submit(downloader.download, rec): (t, rec) for t, rec in all_download_tasks}
                for future in as_completed(future_map):
                    target, rec = future_map[future]
                    try:
                        path, status = future.result()
                    except Exception as e:
                        path, status = "", f"下载异常: {e}"
                        fail_count += 1
                    else:
                        if path:
                            success_count += 1
                        else:
                            fail_count += 1
                    rec.local_path = path
                    rec.download_status = status
                    self.logger.info(f"  {rec.publication_number}: {status[:80]}")

            self.logger.info(f"下载完成: 成功 {success_count}, 失败/降级 {fail_count}, 并发={workers}")
            self.abbr_manager.save()

        # 6. 更新 records JSON + Excel
        report_name = _report_filename(current)
        for target, recs in truly_new.items():
            collect_date = current
            target_cfg = self.cfg.get("targets", {}).get(target, {})
            existing_list = self._existing_records.setdefault(target, [])
            for rec in recs:
                row = rec.to_excel_row(collect_date, report_name)
                existing_list.append(row)

        self._save_records()

        # Excel 全量重建（records.json 是事实源）
        excel_writer = ExcelWriter(self.excel_path)
        counts = excel_writer.rebuild_all(self._existing_records)
        self.logger.info(
            f"Excel 已重建: "
            + ", ".join(f"{t}={n}" for t, n in counts.items())
            + f" → {self.excel_path}"
        )

        # 7. 生成 Markdown 报告
        report_path = self.report_dir / report_name
        run_type_label = {
            "initial": "全量初建",
            "update": "增量更新",
            "skip": "无新增确认",
            "rebuild": "全量重建",
        }.get(run_type, run_type)

        # 计算汇总统计
        cumulative_totals = {
            t: len(self._existing_records.get(t, []))
            for t in self.cfg.get("targets", {})
        }

        generate_markdown_report(
            path=report_path,
            current_date=current,
            run_type=run_type_label,
            start_date=start_date,
            all_new=truly_new,
            errors=[e for sr in all_results for e in sr.errors],
            audit_issues=audit_issues,
            search_results=all_results,
        )
        self.logger.info(f"报告已生成: {report_path}")

        # 8. 更新 state
        self.state = RunState(
            last_date=current,
            last_run_at=dt.datetime.now().isoformat(),
            last_type="initial" if run_type in ("initial", "rebuild") else "update",
            status="success",
            new_records_total=total_new,
            new_patents_by_target={
                t: [r.publication_number for r in recs]
                for t, recs in truly_new.items() if recs
            },
            report_path=str(report_path),
            excel_path=str(self.excel_path),
            cumulative_totals=cumulative_totals,
        )
        self._save_state()

        self.logger.info("===== 完成 =====")
        self.logger.info(f"新增 {total_new} 件专利")
        self.logger.info(f"报告: {report_path}")
        self.logger.info(f"Excel: {self.excel_path}")

        # 汇总输出（供定时任务日志捕获）
        print("")
        print(f"[SUMMARY] 新增: {total_new}")
        for t, recs in truly_new.items():
            print(f"[SUMMARY]   {t}: {len(recs)} ({', '.join(r.publication_number for r in recs)})")
        print(f"[SUMMARY] 报告: {report_path}")
        print(f"[SUMMARY] Excel: {self.excel_path}")

        return 0 if total_new > 0 or not any(sr.errors for sr in all_results) else 1

    # ── 辅助 ──────────────────────────────────────────────────────

    def _write_skip_report(self, current: str, message: str) -> None:
        report_path = self.report_dir / _report_filename(current)
        text = f"""# 靶点专利监控报告 ({current})

**执行类型**：无新增确认

## 变更日志（简要）

{message}

本次未执行检索，未生成新增数据。
"""
        report_path.write_text(text, encoding="utf-8")


def _report_filename(current_date: str) -> str:
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return f"patent_monitor_report_{stamp}.md"


def _merge_records(base: PatentRecord, incoming: PatentRecord, prefer_source: str) -> None:
    """合并两条同专利号的记录，补充缺失字段"""
    # 通用规则：优先保留已有的（先到先得），但如果 incoming 来自更可信的源则覆盖
    wipo_priority = {"wipo", "patenthub"}
    # 如果 base 来源不如 incoming 可信，允许覆盖标题/摘要
    if prefer_source in wipo_priority and incoming.source not in wipo_priority:
        # incoming 更可信 → 用 incoming 覆盖 base
        if incoming.title and not base.title:
            base.title = incoming.title
        if incoming.abstract and not base.abstract:
            base.abstract = incoming.abstract
        if incoming.applicant and not base.applicant:
            base.applicant = incoming.applicant
        if incoming.publication_date and not base.publication_date:
            base.publication_date = incoming.publication_date


# ============================================================================
# CLI
# ============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="靶点专利监控（TSHR, APJ, PCSK9, CYP51）",
    )
    parser.add_argument("--config", "-c", help="配置文件路径（默认 config.yaml）")
    parser.add_argument("--full-rebuild", action="store_true", help="强制全量重建，忽略 task_state.json")
    parser.add_argument("--no-download", action="store_true", help="仅检索+筛选，不下载 PDF")
    parser.add_argument("--date", help="模拟运行日期 YYYY-MM-DD（用于测试/回溯）")
    parser.add_argument("--target", action="append", help="仅检索指定靶点（可重复）")
    parser.add_argument("--mode", choices=["api", "web"], help="强制覆盖 config 中的 mode")
    parser.add_argument("--list-sources", action="store_true", help="列出可用检索源")

    args = parser.parse_args()

    monitor = PatentMonitor(config_path=args.config)

    # CLI 覆盖
    if args.full_rebuild:
        monitor.full_rebuild = True
    if args.no_download:
        monitor.do_download = False
    if args.date:
        monitor.override_date = args.date
    if args.target:
        monitor.targets_filter = args.target
    if args.mode:
        monitor.run_mode = args.mode

    return monitor.run()


if __name__ == "__main__":
    sys.exit(main())
