"""端口选择：默认 8031（8000–8099 段，只监听 127.0.0.1）；默认口被占往后找，指定口被占就报错。"""
from __future__ import annotations

import socket

DEFAULT_PORT = 8031
PORT_RANGE = (8000, 8099)
HOST = "127.0.0.1"


class PortInUse(RuntimeError):
    """要的端口被占着。"""


def is_free(port: int, host: str = HOST) -> bool:
    """试绑一次就放掉。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, int(port)))
        except OSError:
            return False
    return True


def candidates(default: int = DEFAULT_PORT, port_range: tuple[int, int] = PORT_RANGE) -> list[int]:
    """默认口先，接着往后到段尾，再从段头补到默认口之前。"""
    low, high = port_range
    after = [port for port in range(default + 1, high + 1)]
    before = [port for port in range(low, default)]
    return [default, *after, *before]


def pick_port(preferred: int | None = None, *, host: str = HOST, default: int = DEFAULT_PORT,
              port_range: tuple[int, int] = PORT_RANGE) -> int:
    """给了 `preferred` 只试它；没给按 `candidates()` 找第一个空闲口。"""
    if preferred is not None:
        port = int(preferred)
        if not (1 <= port <= 65535):
            raise PortInUse(f"端口要在 1–65535 之间：{preferred}")
        if not is_free(port, host):
            raise PortInUse(f"端口 {port} 已被占用，换一个 --port 或停掉占着它的程序")
        return port
    for port in candidates(default, port_range):
        if is_free(port, host):
            return port
    low, high = port_range
    raise PortInUse(f"{low}–{high} 段没有空闲端口")
