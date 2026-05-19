"""Reddit collector — OAuth2 API."""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx
from ai_weekly.db import Article, Database
from .base import BaseCollector, RateLimiter, is_ai_related

logger = logging.getLogger(__name__)

REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_OAUTH_BASE = "https://oauth.reddit.com"


class RedditCollector(BaseCollector):
    source_name = "reddit"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.subreddits = self.config.get("subreddits", ["MachineLearning", "artificial"])
        self.max_per = self.config.get("max_per_subreddit", 25)
        self._access_token: Optional[str] = None

    def collect(self, db: Database, lookback_days: int = 7) -> list[int]:
        new_ids = []
        self._authenticate()

        for sub in self.subreddits:
            try:
                ids = self._collect_subreddit(sub, db, lookback_days)
                new_ids.extend(ids)
            except Exception as e:
                logger.error(f"Reddit/{sub}: {e}")

        logger.info(f"Reddit: collected {len(new_ids)} new articles")
        return new_ids

    def _authenticate(self):
        client_id = os.environ.get("REDDIT_CLIENT_ID")
        client_secret = os.environ.get("REDDIT_CLIENT_SECRET")

        if not client_id or not client_secret:
            logger.warning("Reddit: REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not set, skipping")
            self._access_token = None
            return

        resp = self.client.post(
            REDDIT_TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
            headers={"User-Agent": "AI-Weekly-Bot/0.1 (by /u/yourbotuser)"},
        )
        resp.raise_for_status()
        self._access_token = resp.json()["access_token"]

    def _collect_subreddit(self, sub: str, db: Database, lookback_days: int) -> list[int]:
        if not self._access_token:
            return []

        new_ids = []
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "User-Agent": "AI-Weekly-Bot/0.1",
        }
        url = f"{REDDIT_OAUTH_BASE}/r/{sub}/hot"
        params = {"limit": min(self.max_per, 100)}

        resp = self.client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        posts = resp.json().get("data", {}).get("children", [])

        for child in posts:
            data = child["data"]
            title = data.get("title", "")
            selftext = data.get("selftext", "")

            if not is_ai_related(title, selftext):
                continue

            post_id = data["name"]  # t3_xxxx
            top_comments = self._fetch_top_comments(post_id, headers)

            article = Article(
                title=title,
                url=f"https://reddit.com{data.get('permalink', '')}",
                source=f"{self.source_name}/{sub}",
                summary_raw=selftext[:2000] if selftext else None,
                points=data.get("score", 0),
                comments=data.get("num_comments", 0),
                top_comments=json.dumps(top_comments, ensure_ascii=False) if top_comments else None,
                published_at=datetime.fromtimestamp(
                    data["created_utc"], tz=timezone.utc
                ).isoformat(),
            )

            aid = db.upsert_article(article)
            if aid:
                new_ids.append(aid)
                logger.debug(f"Reddit/{sub}: [{article.points}pts] {article.title[:60]}")

        return new_ids

    def _fetch_top_comments(self, post_id: str, headers: dict, max_comments: int = 3) -> list[dict]:
        """Fetch top comments for a Reddit post."""
        base = post_id.replace("t3_", "")
        url = f"{REDDIT_OAUTH_BASE}/comments/{base}"
        params = {"limit": 10, "depth": 2, "sort": "top"}

        try:
            resp = self.client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            # resp.json() returns [post_data, comment_tree]
            data = resp.json()
            if len(data) < 2:
                return []

            comments = []
            for child in data[1].get("data", {}).get("children", []):
                cdata = child.get("data", {})
                if cdata.get("stickied"):
                    continue  # Skip stickied auto-mod comments
                comments.append({
                    "body": cdata.get("body", ""),
                    "score": cdata.get("score", 0),
                    "author": cdata.get("author", "unknown"),
                })

            return sorted(comments, key=lambda c: c["score"], reverse=True)[:max_comments]
        except Exception as e:
            logger.debug(f"Failed to fetch comments for {post_id}: {e}")
            return []
