"""
检索层基类 —— Retriever

统一 API 模式和 Web 模式的检索接口。
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, Optional

from models import PatentRecord, SearchResult


class Retriever(ABC):
    """检索器基类"""

    source_name: str = "unknown"

    def __init__(self, config: dict[str, Any]):
        self.config = config

    @abstractmethod
    def search(
        self,
        target: str,
        keywords: str,
        therapy_filter: str,
        start_date: Optional[str],
        end_date: str,
    ) -> SearchResult:
        """
        执行检索。
        
        Args:
            target:        靶点名称 (TSHR / APJ / PCSK9 / CYP51)
            keywords:     靶点关键词检索式
            therapy_filter: 治疗用途限定（AND 子句）
            start_date:   起始日期 YYYY-MM-DD，None 表示不限
            end_date:     截止日期 YYYY-MM-DD
        
        Returns:
            SearchResult
        """
        ...

    def search_with_timing(self, *args, **kwargs) -> SearchResult:
        """带计时包装"""
        t0 = time.time()
        result = self.search(*args, **kwargs)
        result.elapsed_seconds = round(time.time() - t0, 2)
        return result


class RetrieverError(Exception):
    """检索异常基类"""


class CaptchaBlockedError(RetrieverError):
    """被验证码阻断"""


class RateLimitedError(RetrieverError):
    """被限流"""
