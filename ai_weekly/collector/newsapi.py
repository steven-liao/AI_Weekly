"""GNews collector — Google News aggregation API.

Uses the free tier (100 req/day). Falls back gracefully if no API key.
"""

import logging
import os
from datetime import datetime, timezone, timedelta

from ai_weekly.db import Article, Database
from .base import BaseCollector, is_ai_related

logger = logging.getLogger(__name__)

GNEWS_BASE = "https://gnews.io/api/v4/search"


class GNewsCollector(BaseCollector):
    source_name = "gnews"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_items = self.config.get("max_items", 20)

    def collect(self, db: Database, lookback_days: int = 7) -> list[int]:
        api_key = os.environ.get("GNEWS_API_KEY")
        if not api_key:
            logger.warning("GNews: GNEWS_API_KEY not set, skipping")
            return []

        new_ids = []
        from_date = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%dT%H:%M:%SZ")

        params = {
            "q": "AI OR artificial intelligence OR machine learning OR large language model",
            "lang": "en",
            "from": from_date,
            "max": min(self.max_items, 20),
            "sortby": "publishedAt",
            "apikey": api_key,
        }

        resp = self.client.get(GNEWS_BASE, params=params)
        resp.raise_for_status()
        data = resp.json()

        for entry in data.get("articles", []):
            title = entry.get("title", "")
            description = entry.get("description", "")

            if not is_ai_related(title, description):
                continue

            article = Article(
                title=title,
                url=entry.get("url", ""),
                source=f"{self.source_name}/{entry.get('source', {}).get('name', 'unknown')}",
                summary_raw=description or entry.get("content", ""),
                points=0,
                comments=0,
                published_at=entry.get("publishedAt"),
            )

            aid = db.upsert_article(article)
            if aid:
                new_ids.append(aid)
                logger.debug(f"GNews: {title[:60]}")

        logger.info(f"GNews: collected {len(new_ids)} new articles")
        return new_ids
