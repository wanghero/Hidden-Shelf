"""站点解析器：契约在 `base`，一个站一个模块，全部登记在 `SITE_SOURCES`。"""
from __future__ import annotations

from .avbase import AVBASE, AVBaseSource
from .base import (COOLDOWN_ACTIONS, MISS_REASONS, PERMANENT_REASONS, REASON_KINDS, FailureReason, Page, Session,
                   SiteConfig, SiteRecord, SiteSource, SourceFailure, challenge_page, http_failure)
from .dmm import DMM, DmmSource
from .javbus import JAVBUS, JavBusSource
from .javdb import JAVDB, JavDBSource
from .onepondo import ONEPONDO, OnePondoSource
from .r18dev import R18DEV, R18DevSource

#: 来源名 → 站的类。各站任务逐个登记。
SITE_SOURCES: dict[str, type[SiteSource]] = {
    R18DEV.name: R18DevSource,
    DMM.name: DmmSource,
    ONEPONDO.name: OnePondoSource,
    JAVDB.name: JavDBSource,
    JAVBUS.name: JavBusSource,
    AVBASE.name: AVBaseSource,
}

__all__ = ["COOLDOWN_ACTIONS", "MISS_REASONS", "PERMANENT_REASONS", "REASON_KINDS", "SITE_SOURCES",
           "AVBASE", "DMM", "JAVBUS", "JAVDB", "ONEPONDO", "R18DEV",
           "AVBaseSource", "DmmSource", "JavBusSource", "JavDBSource", "OnePondoSource", "R18DevSource",
           "FailureReason", "Page", "Session", "SiteConfig", "SiteRecord", "SiteSource", "SourceFailure",
           "challenge_page", "http_failure"]
