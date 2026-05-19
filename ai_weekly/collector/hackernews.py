"""Hacker News collector — Firebase + Algolia APIs."""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from ai_weekly.db import Article, Database
from .base import BaseCollector, RateLimiter, is_ai_related

logger = logging.getLogger(__name__)

HN_TOP_STORIES = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM = "https://hacker-news.firebaseio.com/v0/item/{}.json"


class HackerNewsCollector(BaseCollector):
    source_name = "hackernews"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_items = self.config.get("max_items", 30)
        self.min_points = self.config.get("min_points", 10)

    def collect(self, db: Database, lookback_days: int = 7) -> list[int]:
        new_ids = []

        # 1. Fetch top story IDs
        resp = self.client.get(HN_TOP_STORIES)
        resp.raise_for_status()
        story_ids = resp.json()[:100]  # Top 100 stories

        # 2. Fetch each story
        count = 0
        item_limiter = RateLimiter(min_interval=0.1)  # 100ms between calls

        for sid in story_ids:
            if count >= self.max_items:
                break

            item_limiter.wait()
            item = self._fetch_item(sid)
            if not item:
                continue
            if item.get("type") != "story":
                continue
            if item.get("score", 0) < self.min_points:
                continue

            title = item.get("title", "")
            url = item.get("url") or f"https://news.ycombinator.com/item?id={sid}"

            if not is_ai_related(title, item.get("text", "")):
                continue

            # 3. Fetch top comments
            top_comments = self._fetch_top_comments(item.get("kids", []))

            article = Article(
                title=title,
                url=url,
                source=self.source_name,
                summary_raw=item.get("text"),
                points=item.get("score", 0),
                comments=item.get("descendants", 0),
                top_comments=json.dumps(top_comments, ensure_ascii=False) if top_comments else None,
                published_at=datetime.fromtimestamp(
                    item["time"], tz=timezone.utc
                ).isoformat() if item.get("time") else None,
            )

            aid = db.upsert_article(article)
            if aid:
                new_ids.append(aid)
                logger.debug(f"HN: [{article.points}pts] {article.title[:60]}")
            count += 1

        logger.info(f"HackerNews: collected {len(new_ids)} new articles")
        return new_ids

    def _fetch_item(self, item_id: int) -> Optional[dict]:
        """Fetch a single HN item."""
        resp = self.client.get(HN_ITEM.format(item_id))
        if resp.status_code != 200:
            return None
        return resp.json()

    def _fetch_top_comments(self, kids: list[int], min_score: int = 10, max_comments: int = 5) -> list[dict]:
        """Fetch top-scoring comments from the kids list. Kids are already sorted by HN rank."""
        results = []
        item_limiter = RateLimiter(min_interval=0.05)

        for kid_id in kids[:20]:  # Only check first 20 comments
            item_limiter.wait()
            item = self._fetch_item(kid_id)
            if not item or item.get("type") != "comment":
                continue
            if item.get("score", 0) >= min_score:
                results.append({
                    "body": item.get("text", ""),
                    "score": item["score"],
                    "author": item.get("by", "unknown"),
                })
            if len(results) >= max_comments:
                break

        return sorted(results, key=lambda c: c["score"], reverse=True)
