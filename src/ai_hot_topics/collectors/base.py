from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from ..models import RawItem


class CollectorError(RuntimeError):
    pass


@dataclass
class CollectorResult:
    platform: str
    items: list[RawItem] = field(default_factory=list)
    warning: str | None = None
    error: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class Collector(Protocol):
    platform: str

    def collect(
        self,
        keywords: list[str],
        since_ts: datetime,
        max_per_keyword: int = 5,
    ) -> CollectorResult:
        ...
