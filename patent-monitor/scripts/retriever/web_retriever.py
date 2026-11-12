"""
Web 模式检索器 —— 使用免费公开源

支持：
  - WIPO PATENTSCOPE（主源）
  - Google Patents（补充）
  - EPO Espacenet（补充）
  - USPTO（补充）

特性：
  - HTTP 标准库实现（无 requests 依赖）
  - 自动重试 + 指数退避
  - 兼容解析不同源的返回结构
  - 去重（按标准化专利号）
"""
from __future__ import annotations

import html as html_mod
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from models import PatentRecord, SearchResult, normalize_date, normalize_pub_no
from retriever import Retriever, CaptchaBlockedError, RateLimitedError


# ============================================================================
# HTTP 工具
# ============================================================================

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "Chrome/124.0 Safari/537.36"
)


class HttpClient:
    """极简 HTTP 客户端（纯标准库）"""

    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: int = 60,
        max_retries: int = 3,
        retry_interval: int = 30,
    ):
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_interval = retry_interval

    def get(self, url: str, headers: dict[str, str] | None = None) -> bytes:
        hdrs = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if headers:
            hdrs.update(headers)

        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            req = urllib.request.Request(url, headers=hdrs)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = resp.read()
                    # 检测验证码
                    if b"captcha" in data.lower() or b"robot" in data.lower() or b"security check" in data.lower():
                        raise CaptchaBlockedError(f"URL {url} 触发了验证码")
                    return data
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    raise RateLimitedError(f"URL {url} 被限流") from e
                if e.code in (403, 503) and attempt < self.max_retries - 1:
                    last_err = e
                    time.sleep(self.retry_interval)
                    continue
                last_err = e
            except (urllib.error.URLError, TimeoutError) as e:
                last_err = e
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_interval)
                    continue
            except CaptchaBlockedError:
                raise
            except RateLimitedError:
                raise

        raise RuntimeError(f"HTTP 失败（重试 {self.max_retries} 次）: {url}: {last_err}")

    def get_json(self, url: str, headers: dict[str, str] | None = None) -> Any:
        data = self.get(url, headers)
        return json.loads(data.decode("utf-8", errors="replace"))


# ============================================================================
# WIPO PATENTSCOPE 检索
# ============================================================================

class WipoRetriever(Retriever):
    """
    WIPO PATENTSCOPE 检索器
    
    检索策略：
      - 使用 ALL=(关键词) AND DP:[起始 TO 截止] 语法
      - ALL 字段确保 CYP51 等出现在摘要/权利要求中的靶点也能被覆盖
      - 先获取结果列表页面，再逐条 fetch 详情页补全著录项
      
    限制：
      - 会触发图片验证码（2026年已多次碰到）
      - 详情页逐条获取较慢，建议增量检索窗口不超过 14 天
    """

    source_name = "wipo"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        http_cfg = config.get("web", {}).get("http", {})
        self.http = HttpClient(
            user_agent=http_cfg.get("user_agent"),
            timeout=http_cfg.get("timeout", 90),
            max_retries=http_cfg.get("max_retries", 3),
            retry_interval=http_cfg.get("retry_interval", 30),
        )

    def search(
        self,
        target: str,
        keywords: str,
        therapy_filter: str,
        start_date: Optional[str],
        end_date: str,
    ) -> SearchResult:
        result = SearchResult(target=target, source=self.source_name, start_date=start_date, end_date=end_date)

        # 构建检索式
        wipo_field = self._get_wipo_field(target)
        query = f"{wipo_field}=({keywords}) {therapy_filter}"
        # WIPO 日期格式：YYYYMMDD TO YYYYMMDD
        start_compact = start_date.replace("-", "") if start_date else "19700101"
        end_compact = end_date.replace("-", "")
        query += f" AND DP:[{start_compact} TO {end_compact}]"

        # 编码 URL
        params = urllib.parse.urlencode({
            "_afrWindowMode": "0",
            "query": query,
            "sort": "Pub Date Desc",
        })
        search_url = f"https://patentscope.wipo.int/search/en/result.jsf?{params}"

        try:
            raw = self.http.get(search_url)
        except CaptchaBlockedError as e:
            result.errors.append(f"WIPO 检索触发验证码: {e}")
            return result
        except Exception as e:
            result.errors.append(f"WIPO 检索失败: {e}")
            return result

        html_text = raw.decode("utf-8", errors="replace")

        # 从结果页解析 docId 列表
        doc_ids = re.findall(
            r'href="[^"]*detail\.jsf[^"]*docId=([A-Za-z0-9_-]+)"',
            html_text,
        )
        # 去重保序
        seen_ids = set()
        unique_doc_ids = []
        for did in doc_ids:
            if did not in seen_ids:
                seen_ids.add(did)
                unique_doc_ids.append(did)

        result.raw_result_count = len(unique_doc_ids)
        if not unique_doc_ids:
            return result

        # 逐条 fetch 详情页（控制并发 = 串行，WIPO 有速率限制）
        for doc_id in unique_doc_ids:
            detail = self._fetch_detail(doc_id, target)
            if detail is not None:
                # 去重检查
                if detail.dedup_key not in {r.dedup_key for r in result.records}:
                    result.records.append(detail)
                # 轻微限速
                time.sleep(1)

        result.after_dedup_count = len(result.records)
        return result

    def _get_wipo_field(self, target: str) -> str:
        """获取靶点的 WIPO 检索字段（从 config 读取，默认 ALL）"""
        targets_cfg = self.config.get("targets", {})
        return targets_cfg.get(target, {}).get("wipo_field", "ALL")

    def _fetch_detail(self, doc_id: str, target: str) -> Optional[PatentRecord]:
        """抓取 WIPO 详情页并解析"""
        detail_url = f"https://patentscope.wipo.int/search/en/detail.jsf?docId={doc_id}"
        try:
            raw = self.http.get(detail_url)
        except Exception:
            return None

        text = raw.decode("utf-8", errors="replace")

        pub_no = self._extract_publication(text)
        if not pub_no:
            return None
        pub_no = normalize_pub_no(pub_no)

        pub_date = normalize_date(self._extract_pub_date(text))
        title = self._extract_title(text)
        applicant = self._extract_applicant(text)
        abstract = self._extract_abstract(text)

        return PatentRecord(
            target=target,
            publication_number=pub_no,
            publication_date=pub_date,
            title=title,
            applicant=applicant,
            abstract=abstract,
            source=self.source_name,
        )

    @staticmethod
    def _extract_publication(text: str) -> str:
        m = re.search(
            r'Publication Number\s*[:\s]*([A-Z]{2}/?\d{4}/\d+|[A-Z]{2}\d{8,})',
            text,
        )
        if m:
            return m.group(1)
        m = re.search(r'(WO/\d{4}/\d+|US\d{11,}|EP\d{8,})', text)
        return m.group(1) if m else ""

    @staticmethod
    def _extract_pub_date(text: str) -> str:
        m = re.search(r'Publication Date\s*[:\s]*(\d{2}\.\d{2}\.\d{4})', text)
        if m:
            parts = m.group(1).split(".")
            return f"{parts[2]}-{parts[1]}-{parts[0]}"
        return ""

    @staticmethod
    def _extract_title(text: str) -> str:
        m = re.search(r'Title\s*\(EN\)\s*[:\s]*([^\n<]{5,300})', text)
        if m:
            return html_mod.unescape(m.group(1)).strip()
        m = re.search(r'<span[^>]*class="[^"]*title[^"]*"[^>]*>([^<]+)', text, re.I)
        return html_mod.unescape(m.group(1)).strip() if m else ""

    @staticmethod
    def _extract_applicant(text: str) -> str:
        m = re.search(r'Applicants?\s*[:\s]*([^\n<]{3,500})', text)
        if m:
            raw = html_mod.unescape(m.group(1)).strip()
            # 去除国家标记如 [US]/[CN]
            raw = re.sub(r'\[[A-Z]{2}\]', '', raw).strip()
            return raw
        return ""

    @staticmethod
    def _extract_abstract(text: str) -> str:
        m = re.search(r'Abstract\s*\(EN\)\s*[:\s]*([^\n]{10,2000})', text)
        if m:
            return html_mod.unescape(m.group(1)).strip()
        m = re.search(r'<div[^>]*class="[^"]*abstract[^"]*"[^>]*>(.{10,2000})', text, re.I)
        return html_mod.unescape(m.group(1)).strip() if m else ""


# ============================================================================
# Google Patents 检索（XHR API）
# ============================================================================

class GoogleRetriever(Retriever):
    """
    Google Patents 检索器
    
    使用 patents.google.com 的内部 XHR API 返回 JSON 格式结果。
    作为 WIPO 的补充源，覆盖 US/EP/CN 等地区专利。
    
    限制：
      - API 是非官方的，可能随时变化
      - 速率限制较严，建议低优先级使用
    """

    source_name = "google"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        http_cfg = config.get("web", {}).get("http", {})
        self.http = HttpClient(
            user_agent=http_cfg.get("user_agent"),
            timeout=http_cfg.get("timeout", 60),
            max_retries=http_cfg.get("max_retries", 2),
            retry_interval=http_cfg.get("retry_interval", 30),
        )

    def search(
        self,
        target: str,
        keywords: str,
        therapy_filter: str,
        start_date: Optional[str],
        end_date: str,
    ) -> SearchResult:
        result = SearchResult(target=target, source=self.source_name, start_date=start_date, end_date=end_date)

        # 构建 Google Patents 查询
        terms = f"({keywords})"
        params: dict[str, str] = {
            "q": terms,
            "dups": "language",
            "before": f"publication:{end_date.replace('-', '')}",
        }
        if start_date:
            params["after"] = f"publication:{start_date.replace('-', '')}"

        inner = urllib.parse.urlencode(params)
        url = "https://patents.google.com/xhr/query?url=" + urllib.parse.quote(inner, safe="")

        try:
            payload = self.http.get_json(url)
        except Exception as e:
            result.errors.append(f"Google 检索失败: {e}")
            return result

        # 兼容解析 Google 的结果结构
        clusters = payload.get("results", {}).get("cluster", [])
        seen = set()

        for cluster in clusters:
            for item in cluster.get("result", []):
                patent = item.get("patent", item)
                pub = (
                    patent.get("publication_number")
                    or patent.get("publicationNumber")
                    or patent.get("id")
                    or ""
                )
                if isinstance(pub, list):
                    pub = pub[0] if pub else ""
                pub = normalize_pub_no(str(pub))
                if not pub or pub in seen:
                    continue
                seen.add(pub)

                assignee = patent.get("assignee") or patent.get("assignee_orig") or []
                inventor = patent.get("inventor") or []
                title = _clean_text(patent.get("title") or patent.get("title_l10n") or "")
                abstract = _clean_text(patent.get("abstract") or patent.get("snippet") or "")

                records = [a.get("name", "") if isinstance(a, dict) else str(a) for a in assignee]
                if not records:
                    records = [i.get("name", "") if isinstance(i, dict) else str(i) for i in inventor]
                applicant = "; ".join(r for r in records if r)

                pub_date = normalize_date(patent.get("publication_date") or patent.get("publicationDate") or "")

                result.records.append(PatentRecord(
                    target=target,
                    publication_number=pub,
                    publication_date=pub_date,
                    title=title,
                    applicant=applicant,
                    abstract=abstract,
                    source=self.source_name,
                ))

        result.raw_result_count = len(seen)
        result.after_dedup_count = len(result.records)
        return result


def _clean_text(value: Any) -> str:
    if isinstance(value, list):
        value = " ".join(str(v) for v in value)
    return re.sub(r"\s+", " ", html_mod.unescape(re.sub(r"<[^>]+>", " ", str(value)))).strip()


# ============================================================================
# 工厂函数
# ============================================================================

RETRIEVER_REGISTRY: dict[str, type[Retriever]] = {
    "wipo": WipoRetriever,
    "google": GoogleRetriever,
}


def create_web_retriever(source: str, config: dict[str, Any]) -> Retriever:
    """创建 Web 检索器实例"""
    cls = RETRIEVER_REGISTRY.get(source)
    if cls is None:
        raise ValueError(f"未知的 Web 检索源: {source}，已注册: {list(RETRIEVER_REGISTRY.keys())}")
    return cls(config)
