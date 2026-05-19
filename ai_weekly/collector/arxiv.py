"""ArXiv collector — API for latest AI/ML/NLP papers."""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

from ai_weekly.db import Article, Database
from .base import BaseCollector, RateLimiter

logger = logging.getLogger(__name__)

ARXIV_API = "https://export.arxiv.org/api/query"


class ArxivCollector(BaseCollector):
    source_name = "arxiv"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.categories = self.config.get("categories", ["cs.AI", "cs.LG", "cs.CL"])
        self.max_results = self.config.get("max_results", 50)
        self._limiter = RateLimiter(min_interval=3.0)  # ArXiv requires 3s between calls

    def collect(self, db: Database, lookback_days: int = 7) -> list[int]:
        new_ids = []

        cat_query = "+OR+".join(f"cat:{cat}" for cat in self.categories)
        params = {
            "search_query": cat_query,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": self.max_results,
        }

        self._limiter.wait()
        url = f"{ARXIV_API}?{urlencode(params)}"
        resp = self.client.get(url)
        resp.raise_for_status()

        root = ET.fromstring(resp.text)
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "arxiv": "http://arxiv.org/schemas/atom",
        }

        cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

        for entry in root.findall("atom:entry", ns):
            title = entry.findtext("atom:title", "").strip()
            summary = entry.findtext("atom:summary", "").strip()
            link = entry.find("atom:link[@title='pdf']", ns)
            paper_url = link.attrib.get("href", "") if link is not None else ""

            published_str = entry.findtext("atom:published", "")
            try:
                published = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
            except Exception:
                published = datetime.now(timezone.utc)

            if published < cutoff:
                continue

            # Collect authors
            authors = [
                author.findtext("atom:name", "")
                for author in entry.findall("atom:author", ns)
            ]

            article = Article(
                title=title,
                url=paper_url,
                source=self.source_name,
                summary_raw=f"Authors: {', '.join(authors[:5])}\n\n{summary[:2000]}",
                points=0,
                comments=0,
                published_at=published.isoformat(),
            )

            aid = db.upsert_article(article)
            if aid:
                new_ids.append(aid)
                logger.debug(f"ArXiv: {title[:60]}")

        logger.info(f"ArXiv: collected {len(new_ids)} new articles")
        return new_ids
