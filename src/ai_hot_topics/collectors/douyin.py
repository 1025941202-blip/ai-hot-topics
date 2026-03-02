from __future__ import annotations

from .browser_base import BrowserSearchCollectorBase


class DouyinCollector(BrowserSearchCollectorBase):
    platform = "douyin"

    def search_url(self, keyword: str) -> str:
        return f"https://www.douyin.com/search/{self.q(keyword)}?type=video"

