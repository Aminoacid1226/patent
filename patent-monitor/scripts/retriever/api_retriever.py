"""
API 模式检索器 —— 使用商业专利数据库 API

支持：
  - PatentHub (patenthub.cn)
  - 智慧芽 (zhihuia.com) — 占位骨架
  - incoPat — 占位骨架

鉴权方式：
  - header → Authorization / X-API-Key / X-Access-Token
  - param  → URL 查询参数 ?t=<token>

所有 API 响应采用"兼容解析"，先读顶层错误码，再对 data 的多种结构做分支提取。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from models import PatentRecord, SearchResult, normalize_date, normalize_pub_no
from retriever import Retriever, RetrieverError


class ApiRetriever(Retriever):
    """
    商业专利数据库 API 检索基类
    
    子类通过重写 _build_url / _parse_response 适配不同供应商。
    """

    source_name = "api"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.provider = config.get("api", {}).get("provider", "patenthub")
        self.provider_cfg = config.get("api", {}).get(self.provider, {})
        self.base_url = self.provider_cfg.get("base_url", "")
        self.auth_type = self.provider_cfg.get("auth_type", "param")  # header | param
        self.header_name = self.provider_cfg.get("header_name", "X-API-Key")
        self.api_key = self.provider_cfg.get("api_key", "")
        self.timeout = self.provider_cfg.get("timeout", 60)
        self.max_retries = self.provider_cfg.get("max_retries", 3)

    def search(
        self,
        target: str,
        keywords: str,
        therapy_filter: str,
        start_date: Optional[str],
        end_date: str,
    ) -> SearchResult:
        result = SearchResult(target=target, source=self.source_name, start_date=start_date, end_date=end_date)

        if not self.api_key or self.api_key == "YOUR_API_KEY_HERE":
            result.errors.append(f"API Key 未配置，跳过 {self.provider}")
            return result

        # 构建请求
        query = self._build_query(keywords, therapy_filter, start_date, end_date)
        url = self._build_url(query)
        headers = self._build_headers()

        try:
            payload = self._request_json(url, headers)
        except Exception as e:
            result.errors.append(f"{self.provider} API 请求失败: {e}")
            return result

        # 解析响应
        records = self._parse_response(payload, target)
        seen = set()
        for rec in records:
            if rec.dedup_key not in seen:
                seen.add(rec.dedup_key)
                result.records.append(rec)

        result.raw_result_count = len(records)
        result.after_dedup_count = len(result.records)
        return result

    # ── 子类实现 ──────────────────────────────────────────────────────────

    def _build_query(self, keywords: str, therapy_filter: str, start_date: Optional[str], end_date: str) -> str:
        """构建供应商特定的检索式"""
        # 默认拼接（PatentHub 风格）
        query = f"({keywords}) {therapy_filter}"
        start_c = start_date.replace("-", "") if start_date else ""
        end_c = end_date.replace("-", "")
        if start_c:
            query += f" AND pubDate:[{start_c} TO {end_c}]"
        else:
            query += f" AND pubDate:[19700101 TO {end_c}]"
        return query

    def _build_url(self, query: str) -> str:
        """构建完整 URL（含鉴权参数）"""
        encoded_q = urllib.parse.quote(query)
        url = f"{self.base_url}/s?q={encoded_q}"
        if self.auth_type == "param":
            url += f"&t={urllib.parse.quote(self.api_key)}"
        return url

    def _build_headers(self) -> dict[str, str]:
        """构建请求头（含鉴权）"""
        headers = {
            "User-Agent": "PatentMonitor/1.0",
            "Accept": "application/json",
        }
        if self.auth_type == "header":
            headers[self.header_name] = self.api_key
        return headers

    def _parse_response(self, payload: Any, target: str) -> list[PatentRecord]:
        """
        兼容解析 API 响应
        
        先读顶层错误码（code/msg/status/error），
        再对 data 的多种可能结构做分支提取（list/rows/items/result/list）。
        """
        records: list[PatentRecord] = []

        # 1. 错误检查
        if isinstance(payload, dict):
            code = payload.get("code") or payload.get("status") or payload.get("errorCode")
            msg = payload.get("msg") or payload.get("message") or payload.get("errorMessage")
            if code is not None and code not in (200, "200", 0, "success"):
                raise RetrieverError(f"API 返回错误 code={code}, msg={msg}")

            # 2. 数据提取（兼容多种结构）
            data = payload.get("data", payload)
            items = None
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = (
                    data.get("list")
                    or data.get("rows")
                    or data.get("items")
                    or data.get("result")
                    or data.get("patents")
                    or data.get("records")
                    or data.get("data")
                )
            if items is None and isinstance(payload, dict):
                items = payload.get("list") or payload.get("rows") or payload.get("items")

            if not items:
                return records

            for item in items:
                if not isinstance(item, dict):
                    continue
                pub_no = (
                    item.get("publicationNumber")
                    or item.get("publication_number")
                    or item.get("patentNumber")
                    or item.get("patent_number")
                    or item.get("pubNo")
                    or ""
                )
                pub_no = normalize_pub_no(str(pub_no))
                if not pub_no:
                    continue

                records.append(PatentRecord(
                    target=target,
                    publication_number=pub_no,
                    publication_date=normalize_date(
                        item.get("publicationDate")
                        or item.get("publication_date")
                        or item.get("pubDate")
                        or item.get("openDate")
                        or ""
                    ),
                    title=item.get("title") or item.get("titleEn") or item.get("title_en") or "",
                    title_zh=item.get("titleZh") or item.get("title_zh") or "",
                    applicant=self._extract_applicant(item),
                    abstract=item.get("abstract") or item.get("summary") or "",
                    source=self.source_name,
                    legal_status=item.get("legalStatus") or item.get("status") or "",
                ))

        return records

    @staticmethod
    def _extract_applicant(item: dict[str, Any]) -> str:
        app = item.get("applicant") or item.get("assignee") or item.get("applicants") or item.get("assignees") or ""
        if isinstance(app, list):
            parts = []
            for a in app:
                if isinstance(a, dict):
                    parts.append(a.get("name", "") or a.get("text", ""))
                else:
                    parts.append(str(a))
            return "; ".join(p for p in parts if p)
        if isinstance(app, dict):
            return app.get("name", "") or app.get("text", "")
        return str(app) if app else ""

    # ── HTTP 底层 ─────────────────────────────────────────────────────────

    def _request_json(self, url: str, headers: dict[str, str]) -> Any:
        """发送 HTTP GET 请求，返回解析后的 JSON"""
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            req = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = resp.read()
                    return json.loads(data.decode("utf-8", errors="replace"))
            except urllib.error.HTTPError as e:
                if e.code in (429, 503) and attempt < self.max_retries - 1:
                    last_err = e
                    time.sleep(2 ** attempt)  # 指数退避
                    continue
                last_err = e
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                last_err = e
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue

        raise RetrieverError(f"API 请求失败: {url}: {last_err}") from last_err


# ============================================================================
# 工厂函数
# ============================================================================

def create_api_retriever(config: dict[str, Any]) -> ApiRetriever:
    """创建 API 检索器实例"""
    provider = config.get("api", {}).get("provider", "patenthub")
    # 所有供应商共用同一实现，通过 config 中的 provider 区分
    return ApiRetriever(config)
