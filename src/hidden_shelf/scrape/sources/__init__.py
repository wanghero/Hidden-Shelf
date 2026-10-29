"""站点解析器：契约在 `base`，一个站一个模块，全部登记在 `SITE_SOURCES`。"""
from __future__ import annotations

from .base import (COOLDOWN_ACTIONS, MISS_REASONS, PERMANENT_REASONS, REASON_KINDS, FailureReason, Page, Session,
                   SiteConfig, SiteRecord, SiteSource, SourceFailure, challenge_page, http_failure)

#: 来源名 → 站的类。各站任务逐个登记。
SITE_SOURCES: dict[str, type[SiteSource]] = {}

__all__ = ["COOLDOWN_ACTIONS", "MISS_REASONS", "PERMANENT_REASONS", "REASON_KINDS", "SITE_SOURCES",
           "FailureReason", "Page", "Session", "SiteConfig", "SiteRecord", "SiteSource", "SourceFailure",
           "challenge_page", "http_failure"]
