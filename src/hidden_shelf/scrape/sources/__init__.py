"""站点解析器：契约在 `base`，一个站一个模块，全部登记在 `SITE_SOURCES`。"""
from __future__ import annotations

from .avbase import AVBASE, AVBaseSource
from .base import (COOLDOWN_ACTIONS, MISS_REASONS, PERMANENT_REASONS, REASON_KINDS, FailureReason, Page, Session,
                   SiteConfig, SiteRecord, SiteSource, SourceFailure, challenge_page, http_failure)
from .dmm import DMM, DmmSource
from .fc2 import FC2, Fc2Source
from .javarchive import JAVARCHIVE, JavArchiveSource
from .javbus import JAVBUS, JavBusSource
from .javdb import JAVDB, JavDBSource
from .onepondo import ONEPONDO, OnePondoSource
from .r18dev import R18DEV, R18DevSource
from .tokyohot import TOKYOHOT, TokyoHotSource

#: 来源名 → 站的类。9 站齐全，与 `policy.SOURCE_SPECS`、`access.SOURCES` 同键。
SITE_SOURCES: dict[str, type[SiteSource]] = {
    R18DEV.name: R18DevSource,
    DMM.name: DmmSource,
    ONEPONDO.name: OnePondoSource,
    TOKYOHOT.name: TokyoHotSource,
    FC2.name: Fc2Source,
    JAVARCHIVE.name: JavArchiveSource,
    JAVDB.name: JavDBSource,
    JAVBUS.name: JavBusSource,
    AVBASE.name: AVBaseSource,
}

__all__ = ["COOLDOWN_ACTIONS", "MISS_REASONS", "PERMANENT_REASONS", "REASON_KINDS", "SITE_SOURCES",
           "AVBASE", "DMM", "FC2", "JAVARCHIVE", "JAVBUS", "JAVDB", "ONEPONDO", "R18DEV", "TOKYOHOT",
           "AVBaseSource", "DmmSource", "Fc2Source", "JavArchiveSource", "JavBusSource", "JavDBSource",
           "OnePondoSource", "R18DevSource", "TokyoHotSource",
           "FailureReason", "Page", "Session", "SiteConfig", "SiteRecord", "SiteSource", "SourceFailure",
           "challenge_page", "http_failure"]
