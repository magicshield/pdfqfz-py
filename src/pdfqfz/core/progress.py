"""并发小工具：预览请求门闸 + 惰性页缓存（移植 C# PreviewOverlayRequestGate / PageCache）。"""

from __future__ import annotations

import threading
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


class RequestGate:
    def __init__(self) -> None:
        self._cur = 0
        self._lock = threading.Lock()

    def begin_next(self) -> int:
        with self._lock:
            self._cur += 1
            return self._cur

    def is_current(self, request_id: int) -> bool:
        with self._lock:
            return self._cur == request_id


class PageCache(Generic[T]):
    """按页号惰性加载；容量上限 FIFO 回收（C# 无上限，这里是有意的改进）。"""

    def __init__(self, loader: Callable[[int], T], capacity: int = 32) -> None:
        self._loader = loader
        self._capacity = max(1, capacity)
        self._pages: dict[int, T] = {}
        self._order: list[int] = []
        self._disposed = False

    def get_page(self, page_index: int) -> T:
        if self._disposed:
            raise RuntimeError("cache disposed")
        if page_index in self._pages:
            return self._pages[page_index]
        value = self._loader(page_index)
        self._pages[page_index] = value
        self._order.append(page_index)
        while len(self._order) > self._capacity:
            old = self._order.pop(0)
            self._pages.pop(old, None)
        return value

    def clear(self) -> None:
        self._pages.clear()
        self._order.clear()

    def dispose(self) -> None:
        self.clear()
        self._disposed = True
