from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from ..models import RawItem
from ..utils import now_utc
from .browser_base import BrowserSearchCollectorBase


class XiaohongshuCollector(BrowserSearchCollectorBase):
    platform = "xiaohongshu"

    def search_url(self, keyword: str) -> str:
        return f"https://www.xiaohongshu.com/search_result?keyword={self.q(keyword)}&source=web_explore_feed"

    def _extract_page_items(self, page, keyword: str, max_per_keyword: int) -> list[RawItem]:
        state_items = self._extract_state_items(page, max_per_keyword=max_per_keyword)
        if state_items:
            items = self._state_items_to_raw_items(state_items, keyword=keyword)
            self._enrich_author_profiles(page, items)
            return items

        try:
            page.wait_for_selector("section.note-item", timeout=8000)
        except Exception:
            return self._generic_extract(page, keyword, max_per_keyword)

        cards = page.evaluate(
            """
            (limit) => {
              const out = [];
              const sections = Array.from(document.querySelectorAll('section.note-item'));
              for (const section of sections) {
                const noteAnchor = section.querySelector('a[href*="/explore/"]');
                if (!noteAnchor) continue;
                const hrefRaw = noteAnchor.getAttribute('href') || '';
                if (!hrefRaw.includes('/explore/')) continue;
                const href = new URL(hrefRaw, location.origin).href;
                const authorAnchor = section.querySelector('a.author, a[href*="/user/profile/"]');
                const titleNode = section.querySelector('.title span, .title');
                const lines = (section.innerText || '')
                  .split('\\n')
                  .map(x => x.trim())
                  .filter(Boolean);
                const title = (titleNode && (titleNode.innerText || titleNode.textContent || '').trim())
                  || (lines[0] || '');
                const authorText = (authorAnchor && (authorAnchor.innerText || authorAnchor.textContent || '').trim())
                  || '';
                const author = (authorText.split('\\n')[0] || '').trim();
                const metricText = lines.length ? lines[lines.length - 1] : '';
                const dateText = lines.length >= 2 ? lines[lines.length - 2] : '';
                out.push({
                  href,
                  title,
                  author,
                  metricText,
                  dateText,
                  text: lines.join('\\n'),
                  lines,
                });
                if (out.length >= limit) break;
              }
              return out;
            }
            """,
            max_per_keyword,
        )
        return self._cards_to_raw_items(cards, keyword=keyword)

    def _extract_state_items(self, page, max_per_keyword: int):
        return page.evaluate(
            """
            (limit) => {
              const state = window.__INITIAL_STATE__ || {};
              const search = state.search || {};
              const feedsContainer = search.feeds || {};
              const feeds = feedsContainer._rawValue || feedsContainer._value || [];
              const out = [];
              for (const item of feeds) {
                if (!item || !item.noteCard || !item.id) continue;
                const noteCard = item.noteCard || {};
                const user = noteCard.user || {};
                const interactInfo = noteCard.interactInfo || {};
                const cornerTags = Array.isArray(noteCard.cornerTagInfo) ? noteCard.cornerTagInfo : [];
                const publishTag = cornerTags.find(x => x && x.type === 'publish_time');
                out.push({
                  noteId: String(item.id || ''),
                  xsecToken: String(item.xsecToken || ''),
                  title: String(noteCard.displayTitle || '').trim(),
                  user: {
                    userId: String(user.userId || ''),
                    nickname: String(user.nickname || user.nickName || '').trim(),
                    avatar: String(user.avatar || '').trim(),
                    xsecToken: String(user.xsecToken || '').trim(),
                  },
                  interactInfo: {
                    likedCount: String(interactInfo.likedCount || ''),
                    collectedCount: String(interactInfo.collectedCount || ''),
                    commentCount: String(interactInfo.commentCount || ''),
                    shareCount: String(interactInfo.shareCount || interactInfo.sharedCount || ''),
                    viewCount: String(interactInfo.viewCount || interactInfo.readCount || interactInfo.browseCount || ''),
                  },
                  publishTimeText: publishTag ? String(publishTag.text || '').trim() : '',
                  type: String(noteCard.type || ''),
                });
                if (out.length >= limit) break;
              }
              return out;
            }
            """,
            max_per_keyword,
        )

    def _state_items_to_raw_items(self, state_items, keyword: str) -> list[RawItem]:
        items: list[RawItem] = []
        seen_note_ids: set[str] = set()
        collected_at = now_utc()
        for entry in state_items or []:
            if not isinstance(entry, dict):
                continue
            note_id = str(entry.get("noteId") or "").strip()
            if not note_id or note_id in seen_note_ids:
                continue
            seen_note_ids.add(note_id)
            title = str(entry.get("title") or "").strip()
            if not title:
                continue

            user = entry.get("user") or {}
            user_id = str(user.get("userId") or "").strip()
            user_xsec = str(user.get("xsecToken") or "").strip()
            note_xsec = str(entry.get("xsecToken") or "").strip()
            note_url = f"https://www.xiaohongshu.com/explore/{note_id}"
            if note_xsec:
                note_url += f"?xsec_token={note_xsec}&xsec_source=pc_search"

            profile_url = f"https://www.xiaohongshu.com/user/profile/{user_id}" if user_id else ""
            if profile_url and user_xsec:
                profile_url += f"?xsec_token={user_xsec}&xsec_source=pc_search"

            interact = entry.get("interactInfo") or {}
            likes = self._parse_count_text(str(interact.get("likedCount") or ""))
            favorites = self._parse_count_text(str(interact.get("collectedCount") or ""))
            comments = self._parse_count_text(str(interact.get("commentCount") or ""))
            shares = self._parse_count_text(str(interact.get("shareCount") or ""))
            views = self._parse_count_text(str(interact.get("viewCount") or ""))
            publish_time_text = str(entry.get("publishTimeText") or "").strip()
            published_at = self._parse_publish_time(publish_time_text)

            author_name = str(user.get("nickname") or "").strip()
            author_avatar = str(user.get("avatar") or "").strip()
            items.append(
                RawItem(
                    platform=self.platform,
                    source_id=self.source_id,
                    query=keyword,
                    platform_post_id=note_id,
                    url=note_url,
                    title=title[:200],
                    text=title[:1000],
                    author=author_name[:100],
                    published_at=published_at,
                    metrics={
                        "views": views,
                        "likes": likes,
                        "favorites": favorites,
                        "comments": comments,
                        "shares": shares,
                    },
                    language="zh",
                    raw_payload={
                        "source": "xiaohongshu_initial_state_search",
                        "publish_time_text": publish_time_text,
                        "note_type": str(entry.get("type") or ""),
                        "author_id": user_id,
                        "author_name": author_name,
                        "author_avatar": author_avatar,
                        "author_xsec_token": user_xsec,
                        "note_xsec_token": note_xsec,
                        "author_profile_url": profile_url,
                        "author_profile": {},
                    },
                    collected_at=collected_at,
                )
            )
        return items

    def _cards_to_raw_items(self, cards, keyword: str) -> list[RawItem]:
        items: list[RawItem] = []
        seen_urls: set[str] = set()
        collected_at = now_utc()
        for card in cards or []:
            if not isinstance(card, dict):
                continue
            url = str(card.get("href") or "").strip()
            if not url or "/explore/" not in url or url in seen_urls:
                continue
            seen_urls.add(url)

            title = str(card.get("title") or "").strip()
            body_text = str(card.get("text") or "").strip()
            # 过滤“大家都在搜”等非笔记块，以及无有效标题的卡片
            if not title or title in {"大家都在搜"}:
                continue
            if "大家都在搜" in body_text and "/explore/" not in url:
                continue

            author = str(card.get("author") or "").strip()
            metric_text = str(card.get("metricText") or "").strip()
            date_text = str(card.get("dateText") or "").strip()
            likes = self._parse_count_text(metric_text)

            platform_post_id = self._extract_explore_id(url)
            items.append(
                RawItem(
                    platform=self.platform,
                    source_id=self.source_id,
                    query=keyword,
                    platform_post_id=platform_post_id,
                    url=url,
                    title=title[:200],
                    text=body_text[:1000],
                    author=author[:100],
                    published_at=None,
                    metrics={"likes": likes, "comments": 0, "shares": 0},
                    language="zh",
                    raw_payload={
                        "source": "xiaohongshu_note_item",
                        "metric_text": metric_text,
                        "date_text": date_text,
                        "lines": card.get("lines") or [],
                        "publish_time_text": date_text,
                        "author_name": author,
                        "author_avatar": "",
                        "author_profile": {},
                    },
                    collected_at=collected_at,
                )
            )
        return items

    def _enrich_author_profiles(self, page, items: list[RawItem]) -> None:
        if not items:
            return
        try:
            max_profiles = int((self.env.get("XHS_PROFILE_ENRICH_LIMIT") or "20").strip())
        except ValueError:
            max_profiles = 20
        if max_profiles <= 0:
            return

        author_targets: dict[str, dict[str, str]] = {}
        for item in items:
            payload = item.raw_payload or {}
            user_id = str(payload.get("author_id") or "").strip()
            if not user_id:
                continue
            if user_id in author_targets:
                continue
            author_targets[user_id] = {
                "xsec_token": str(payload.get("author_xsec_token") or "").strip(),
            }

        if not author_targets:
            return

        profile_data: dict[str, dict[str, object]] = {}
        detail_page = page.context.new_page()
        try:
            for idx, (user_id, meta) in enumerate(author_targets.items()):
                if idx >= max_profiles:
                    break
                info = self._fetch_profile_info(
                    detail_page,
                    user_id=user_id,
                    user_xsec=meta.get("xsec_token", ""),
                )
                if info:
                    profile_data[user_id] = info
        finally:
            detail_page.close()

        for item in items:
            payload = item.raw_payload or {}
            user_id = str(payload.get("author_id") or "").strip()
            if not user_id:
                continue
            info = profile_data.get(user_id)
            if not info:
                continue
            payload["author_profile"] = info
            if not payload.get("author_avatar"):
                payload["author_avatar"] = str(info.get("avatar") or "")
            if not payload.get("author_name"):
                payload["author_name"] = str(info.get("nickname") or "")
            if not item.author and info.get("nickname"):
                item.author = str(info["nickname"])[:100]
            item.raw_payload = payload

    def _fetch_profile_info(self, page, *, user_id: str, user_xsec: str = "") -> dict[str, object] | None:
        if not user_id:
            return None
        url = f"https://www.xiaohongshu.com/user/profile/{user_id}"
        if user_xsec:
            url += f"?xsec_token={user_xsec}&xsec_source=pc_search"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1200)
            data = page.evaluate(
                """
                () => {
                  const st = window.__INITIAL_STATE__ || {};
                  const userStore = st.user || {};
                  const pageData = (userStore.userPageData && (userStore.userPageData._rawValue || userStore.userPageData._value)) || {};
                  const basic = pageData.basicInfo || {};
                  const interactions = Array.isArray(pageData.interactions) ? pageData.interactions : [];
                  const interactionMap = {};
                  for (const x of interactions) {
                    if (!x || !x.type) continue;
                    interactionMap[String(x.type)] = String(x.count || '');
                  }
                  return {
                    nickname: String(basic.nickname || ''),
                    avatar: String(basic.imageb || basic.images || ''),
                    bio: String(basic.desc || ''),
                    follows_count: String(interactionMap.follows || ''),
                    fans_count: String(interactionMap.fans || ''),
                    likes_and_collects_count: String(interactionMap.interaction || ''),
                    ip_location: String(basic.ipLocation || ''),
                    red_id: String(basic.redId || ''),
                  };
                }
                """
            )
        except Exception:
            return None
        return {
            "nickname": str(data.get("nickname") or ""),
            "avatar": str(data.get("avatar") or ""),
            "bio": str(data.get("bio") or ""),
            "follows_count": self._parse_count_text(str(data.get("follows_count") or "")),
            "fans_count": self._parse_count_text(str(data.get("fans_count") or "")),
            "likes_and_collects_count": self._parse_count_text(
                str(data.get("likes_and_collects_count") or "")
            ),
            "ip_location": str(data.get("ip_location") or ""),
            "red_id": str(data.get("red_id") or ""),
        }

    @staticmethod
    def _extract_explore_id(url: str) -> str:
        m = re.search(r"/explore/([A-Za-z0-9]+)", url)
        if m:
            return m.group(1)
        return url

    @staticmethod
    def _parse_count_text(text: str) -> int:
        text = (text or "").strip().lower().replace(",", "")
        if not text:
            return 0
        # 过滤日期/相对时间
        if re.search(r"(天前|小时前|分钟前|月前|年前)$", text):
            return 0
        if re.match(r"^\d{4}-\d{2}-\d{2}$", text) or re.match(r"^\d{2}-\d{2}$", text):
            return 0
        m = re.match(r"^(\d+(?:\.\d+)?)\s*(万|w)?$", text)
        if not m:
            return 0
        base = float(m.group(1))
        unit = m.group(2)
        if unit in {"万", "w"}:
            base *= 10000
        return int(base)

    @staticmethod
    def _parse_publish_time(text: str) -> datetime | None:
        text = (text or "").strip()
        if not text:
            return None
        now = now_utc()

        m = re.match(r"^(\d+)天前$", text)
        if m:
            return now - timedelta(days=int(m.group(1)))
        m = re.match(r"^(\d+)小时前$", text)
        if m:
            return now - timedelta(hours=int(m.group(1)))
        m = re.match(r"^(\d+)分钟前$", text)
        if m:
            return now - timedelta(minutes=int(m.group(1)))

        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", text)
        if m:
            year, month, day = map(int, m.groups())
            try:
                return datetime(year, month, day, tzinfo=timezone.utc)
            except ValueError:
                return None

        m = re.match(r"^(\d{2})-(\d{2})$", text)
        if m:
            month, day = map(int, m.groups())
            year = now.year
            try:
                dt = datetime(year, month, day, tzinfo=timezone.utc)
            except ValueError:
                return None
            # 若出现未来日期，按上一年处理
            if dt > now + timedelta(days=1):
                try:
                    dt = datetime(year - 1, month, day, tzinfo=timezone.utc)
                except ValueError:
                    return None
            return dt
        return None
