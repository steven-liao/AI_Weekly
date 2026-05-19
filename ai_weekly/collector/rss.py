"""RSS collector — TechCrunch AI, VentureBeat AI, The Verge AI."""

import logging
from datetime import datetime, timezone
from typing import Optional

import feedparser

from ai_weekly.db import Article, Database
from .base import BaseCollector, is_ai_related, RateLimiter

logger = logging.getLogger(__name__)


class RSSCollector(BaseCollector):
    source_name = "rss"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.feeds = self.config.get("feeds", [])

    def collect(self, db: Database, lookback_days: int = 7) -> list[int]:
        new_ids = []

        for feed_url in self.feeds:
            try:
                ids = self._collect_feed(feed_url, db, lookback_days)
                new_ids.extend(ids)
            except Exception as e:
                logger.error(f"RSS {feed_url}: {e}")

        logger.info(f"RSS: collected {len(new_ids)} new articles")
        return new_ids

    def _collect_feed(self, feed_url: str, db: Database, lookback_days: int) -> list[int]:
        new_ids = []
        feed = feedparser.parse(feed_url)

        source_domain = self._extract_domain(feed_url)

        for entry in feed.entries[:30]:
            title = entry.get("title", "")
            link = entry.get("link", "")

            # Get summary (strip HTML)
            summary = entry.get("summary") or entry.get("description") or ""
            summary = _strip_html(summary)[:2000]

            if not is_ai_related(title, summary):
                continue

            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                published = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc).isoformat()

            article = Article(
                title=title,
                url=link,
                source=f"{self.source_name}/{source_domain}",
                summary_raw=summary,
                points=0,  # RSS has no votes
                comments=0,
                published_at=published,
            )

            aid = db.upsert_article(article)
            if aid:
                new_ids.append(aid)
                logger.debug(f"RSS: {title[:60]}")

        return new_ids

    def _extract_domain(self, url: str) -> str:
        from urllib.parse import urlparse
        return urlparse(url).netloc.replace("www.", "")


def _strip_html(text: str) -> str:
    """Quick HTML tag removal."""
    import re
    return re.sub(r"<[^>]+>", "", text)
