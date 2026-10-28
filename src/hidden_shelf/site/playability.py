"""容器与编码 → 浏览器能不能直接播（`play_hint`）。

三档：`native`（主流浏览器都能播）、`check`（取决于平台，前端用 `canPlayType` 再探）、
`unsupported`（浏览器不认这个容器，只能给「复制路径」）。只按 ffprobe 读到的容器与编码判，
不下载不解码。
"""
from __future__ import annotations

NATIVE = "native"
CHECK = "check"
UNSUPPORTED = "unsupported"

_MP4_LIKE = frozenset({"mp4", "m4v", "mov"})
_WEBM = frozenset({"webm"})
#: 浏览器一概不收的容器。
_UNSUPPORTED_CONTAINERS = frozenset({"mkv", "avi", "wmv", "rmvb", "rm", "flv", "ts", "m2ts", "mts",
                                     "mpg", "mpeg", "iso", "strm", "asf", "vob", "3gp"})
_NATIVE_AUDIO = frozenset({"aac", "mp3", ""})
_WEBM_AUDIO = frozenset({"vorbis", "opus", ""})
#: 有的平台能解、有的不能：Safari 认 ac3/flac，Chrome 认 opus/flac。
_CHECK_AUDIO = frozenset({"opus", "ac3", "eac3", "flac", "alac"})
#: HEVC 看硬件与系统，AV1 看浏览器版本。
_CHECK_VIDEO = frozenset({"hevc", "h265", "av1"})


def play_hint(container: str, vcodec: str, acodec: str) -> str:
    container = str(container or "").lower().lstrip(".")
    vcodec = str(vcodec or "").lower()
    acodec = str(acodec or "").lower()
    if container in _UNSUPPORTED_CONTAINERS or not container:
        return UNSUPPORTED
    if container in _MP4_LIKE:
        if vcodec == "h264":
            if acodec in _NATIVE_AUDIO:
                return NATIVE
            if acodec in _CHECK_AUDIO:
                return CHECK
            return UNSUPPORTED
        if vcodec in _CHECK_VIDEO:
            return CHECK if acodec in (_NATIVE_AUDIO | _CHECK_AUDIO) else UNSUPPORTED
        return UNSUPPORTED
    if container in _WEBM:
        if vcodec in {"vp8", "vp9", "av1"}:
            return NATIVE if acodec in _WEBM_AUDIO else CHECK
        return UNSUPPORTED
    return UNSUPPORTED
