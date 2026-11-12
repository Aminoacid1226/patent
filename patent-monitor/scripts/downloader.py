"""
专利文件下载器

特性：
  - 按专利类型智能选择下载源
  - 强制 PDF 有效性校验（文件头必须是 %PDF）
  - PDF 失败时自动降级保存 HTML
  - 文件名标准化：{公开日期}_{申请人缩写}_{专利号}.pdf
  - 申请人缩写跨次一致（维护 applicant_abbr.json）
"""
from __future__ import annotations

import hashlib
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

from models import PatentRecord, safe_filename


# ============================================================================
# PDF URL 选择策略
# ============================================================================

def _preferred_pdf_urls(pub_no: str) -> list[str]:
    """
    按优先级返回可能的 PDF 下载 URL 列表
    
    US 专利 → USPTO image-ppubs（最稳定）
    其他    → Google Patents PDF（覆盖 WO/EP/CN/JP/KR 等）
    """
    urls: list[str] = []

    # US 专利：USPTO
    if pub_no.startswith("US"):
        # 去掉 "US" 前缀后的数字部分
        us_num = pub_no[2:].split("B")[0].split("A")[0].split("D")[0]  # 取纯数字
        us_num = re.sub(r'\D', '', us_num)
        if len(us_num) >= 6:
            urls.append(
                f"https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/{pub_no}"
            )

    # Google Patents PDF（通用 fallback）
    urls.append(f"https://patents.google.com/patent/{urllib.parse.quote(pub_no)}/pdf")

    return urls


def _google_html_url(pub_no: str) -> str:
    """Google Patents HTML 详情页（作为 PDF 全部失败时的降级）"""
    return f"https://patents.google.com/patent/{urllib.parse.quote(pub_no)}/en"


# ============================================================================
# PDF 校验
# ============================================================================

def is_valid_pdf(data: bytes) -> bool:
    """
    检查数据是否为有效 PDF
    
    规则：文件头 4 字节必须是 %PDF
    （这是 PDF 规范要求的，也是我们之前踩过的坑——伪 PDF 头）
    """
    return data[:4] == b"%PDF"


def is_valid_pdf_file(path: Path) -> bool:
    """检查本地文件是否为有效 PDF"""
    try:
        with path.open("rb") as f:
            return f.read(4) == b"%PDF"
    except OSError:
        return False


# ============================================================================
# 申请人缩写管理
# ============================================================================

class ApplicantAbbrManager:
    """
    申请人缩写管理器
    
    规则：
      - 跨次运行保持一致（持久化到 applicant_abbr.json）
      - 同一申请人永远映射到同一缩写
      - 缩写冲突时自动追加后缀避免重复
    """

    def __init__(self, json_path: Path):
        self.json_path = json_path
        self._mapping: dict[str, str] = self._load()

    def _load(self) -> dict[str, str]:
        if self.json_path.exists():
            try:
                import json
                with self.json_path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save(self) -> None:
        self.json_path.parent.mkdir(parents=True, exist_ok=True)
        import json
        with self.json_path.open("w", encoding="utf-8") as f:
            json.dump(self._mapping, f, ensure_ascii=False, indent=2, sort_keys=True)

    def get_abbr(self, applicant: str) -> str:
        """获取申请人缩写（不存在则创建）"""
        applicant = applicant or "Unknown"
        # 取第一个申请人（分号分隔）
        first = applicant.split(";")[0].strip() or "Unknown"

        if first in self._mapping:
            return self._mapping[first]

        # 生成缩写：
        #   - 只有一个词 → 取该词前 8 字符大写
        #   - 多个词 → 若第一个词 ≥5 字符，取第一词前 8 字符；
        #              否则取各词首字母组合（≤10 字符）
        words = re.findall(r"[A-Za-z0-9]+", first)
        if not words:
            base = "APP"
        elif len(words) == 1:
            base = words[0][:8].upper()
        else:
            if len(words[0]) >= 5:
                # 第一个词足够有辨识度，直接截它
                base = words[0][:8].upper()
            else:
                # 短词首字母组合
                base = "".join(w[0] for w in words[:5]).upper()
        base = base[:10] or "APP"

        # 确保不冲突
        existing = set(self._mapping.values())
        abbr = base
        i = 2
        while abbr in existing:
            abbr = f"{base[:8]}{i}"
            i += 1

        self._mapping[first] = abbr
        return abbr

    def list_all(self) -> dict[str, str]:
        return dict(self._mapping)


# ============================================================================
# 下载器主类
# ============================================================================

class PatentDownloader:
    """
    专利文件下载器
    
    用法：
        downloader = PatentDownloader(patent_dir, abbr_manager)
        path, status = downloader.download(record)
    """

    def __init__(
        self,
        patent_dir: Path,
        abbr_manager: ApplicantAbbrManager,
        timeout: int = 60,
        max_retries: int = 2,
        user_agent: str = "",
    ):
        self.patent_dir = patent_dir
        self.abbr_manager = abbr_manager
        self.timeout = timeout
        self.max_retries = max_retries
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "Chrome/124.0 Safari/537.36"
        )

    def download(self, record: PatentRecord) -> tuple[str, str]:
        """
        下载专利全文。
        
        Returns:
            (本地文件路径, 状态描述)
        """
        # 目标目录：patent_dir/{靶点}/
        target_dir = self.patent_dir / record.target
        target_dir.mkdir(parents=True, exist_ok=True)

        # 生成文件名
        abbr = self.abbr_manager.get_abbr(record.applicant)
        pub_date = record.publication_date or "0000-00-00"
        pub_no = record.publication_number
        stem = safe_filename(f"{pub_date}_{abbr}_{pub_no}")

        pdf_path = target_dir / f"{stem}.pdf"
        html_path = target_dir / f"{stem}.html"

        # 已存在有效 PDF → 直接返回
        if pdf_path.exists() and is_valid_pdf_file(pdf_path):
            return str(pdf_path), "PDF有效（已存在）"
        # 已存在 HTML → 直接返回
        if html_path.exists():
            return str(html_path), "HTML已存在"

        # 尝试下载 PDF
        last_error = ""
        for url in _preferred_pdf_urls(pub_no):
            try:
                data = self._http_get(url)
                if is_valid_pdf(data):
                    pdf_path.write_bytes(data)
                    return str(pdf_path), "PDF有效（刚下载）"
                last_error = "返回内容非PDF格式"
            except Exception as e:
                last_error = str(e)

        # PDF 全部失败 → 降级为 HTML
        try:
            data = self._http_get(_google_html_url(pub_no))
            html_path.write_bytes(data)
            return str(html_path), f"保存HTML（PDF获取失败: {last_error[:100]}）"
        except Exception as e:
            return "", f"全文获取失败: PDF→{last_error[:80]}; HTML→{e}"

    def _http_get(self, url: str) -> bytes:
        headers = {"User-Agent": self.user_agent}
        req = urllib.request.Request(url, headers=headers)
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.read()
            except Exception as e:
                last_err = e
                if attempt < self.max_retries:
                    time.sleep(5)
        raise RuntimeError(f"HTTP 下载失败: {url}: {last_err}")
