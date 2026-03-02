from __future__ import annotations

from .browser_base import BrowserSearchCollectorBase


class XCollector(BrowserSearchCollectorBase):
    platform = "x"

    def search_url(self, keyword: str) -> str:
        return f"https://x.com/search?q={self.q(keyword)}&src=typed_query&f=live"

