"""Ranker — three scoring algorithms producing three independent Top 10 lists.

Algorithm A: Hotness (热度优先) — upvotes, comments, community engagement
Algorithm B: Impact (影响力优先) — source authority, technical signals
Algorithm C: Freshness (新鲜度优先) — recency, novelty, surprise
"""

import json
import logging
import math
import re
from datetime import datetime, timezone
from typing import Any

from rapidfuzz import fuzz

from ai_weekly.db import Database, WeeklyTop10

logger = logging.getLogger(__name__)

# Keywords that signal a major breakthrough / impactful news
IMPACT_KEYWORDS = [
    "breakthrough", "state-of-the-art", "release", "open-source", "github",
    "paper", "publish", "benchmark", "beat", "surpass", "scale",
    "突破", "发布", "开源", "论文", "首次", "最大", "最强",
]


class Ranker:
    """Three-algorithm ranker. All use the same dedup'd pool."""

    def __init__(self, config: dict):
        self.config = config

    def run(self, db: Database, lookback_days: int = 7) -> dict[str, list[dict]]:
        """Run all three algorithms, return {alg_name: [ranked_articles]}."""
        raw = db.get_recent_articles(lookback_days)
        if not raw:
            logger.warning("No articles found for ranking")
            return {"hotness": [], "impact": [], "freshness": []}

        logger.info(f"Ranking {len(raw)} articles with 3 algorithms...")
        deduped = self._dedup(raw)
        logger.info(f"After dedup: {len(deduped)} articles")

        now = datetime.now(timezone.utc)

        results = {
            "hotness": self._rank_hotness(deduped, now),
            "impact": self._rank_impact(deduped, now),
            "freshness": self._rank_freshness(deduped, now),
        }

        for name, ranked in results.items():
            logger.info(f"  {name}: top={ranked[0]['title'][:50] if ranked else 'empty'} ({len(ranked)} items)")

        return results

    def save_results(self, db: Database, week_start: str, results: dict[str, list[dict]]):
        """Persist ranking results to DB."""
        for algo_name, ranked in results.items():
            db.clear_weekly_top10(week_start, algo_name)
            for i, item in enumerate(ranked):
                db.insert_top10_entry(WeeklyTop10(
                    week_start=week_start,
                    rank=i + 1,
                    article_id=item["id"],
                    score=item["score"],
                    algorithm=algo_name,
                ))

    # ── Dedup ─────────────────────────────────────────────

    def _dedup(self, articles: list[dict]) -> list[dict]:
        """Title similarity dedup using rapidfuzz. Keep the higher-scored one."""
        if not articles:
            return []

        # Pre-sort by points desc so we keep the best version
        sorted_arts = sorted(articles, key=lambda a: a.get("points", 0), reverse=True)
        keep = []

        for art in sorted_arts:
            title = art.get("title", "")
            is_dup = False
            for k in keep:
                if fuzz.ratio(title, k.get("title", "")) > 78:
                    is_dup = True
                    break
                if fuzz.partial_ratio(title, k.get("title", "")) > 88:
                    is_dup = True
                    break
            if not is_dup:
                keep.append(art)

        return keep

    # ── Algorithm A: Hotness ──────────────────────────────

    def _rank_hotness(self, articles: list[dict], now: datetime) -> list[dict]:
        cfg = self.config.get("scoring", {}).get("algorithms", {}).get("hotness", {})
        w_upvote = cfg.get("upvote_weight", 0.5)
        w_comment = cfg.get("comment_weight", 0.3)
        pop_ratio = cfg.get("popularity_ratio", 0.7)
        halflife = cfg.get("recency_halflife_hours", 24)
        src_weights = cfg.get("source_weights", {})

        scored = []
        for art in articles:
            points = art.get("points", 0) or 0
            comments = art.get("comments", 0) or 0
            source = art.get("source", "")

            popularity = math.log10(points + 1) * w_upvote + math.log10(comments + 1) * w_comment
            age_hours = self._age_hours(art.get("published_at"), now)
            recency = 0.5 ** (age_hours / max(halflife, 1))
            src_boost = self._source_boost(source, src_weights)

            score = (popularity * pop_ratio + recency * (1 - pop_ratio)) * src_boost
            scored.append({**art, "score": round(score, 4)})

        scored.sort(key=lambda a: a["score"], reverse=True)
        return scored[:10]

    # ── Algorithm B: Impact ───────────────────────────────

    def _rank_impact(self, articles: list[dict], now: datetime) -> list[dict]:
        cfg = self.config.get("scoring", {}).get("algorithms", {}).get("impact", {})
        auth_ratio = cfg.get("authority_ratio", 0.65)
        halflife = cfg.get("recency_halflife_hours", 48)
        kw_boost = cfg.get("keyword_boost", 0.2)
        credibility = cfg.get("source_credibility", {})

        scored = []
        for art in articles:
            source = art.get("source", "")
            authority = self._source_boost(source, credibility)
            age_hours = self._age_hours(art.get("published_at"), now)
            recency = 0.5 ** (age_hours / max(halflife, 1))

            # Keyword boost for breakthrough signals
            title = art.get("title", "")
            summary = art.get("summary_raw") or ""
            has_impact_words = any(kw in (title + summary).lower() for kw in IMPACT_KEYWORDS)
            boost = 1.0 + (kw_boost if has_impact_words else 0)

            score = (authority * auth_ratio + recency * (1 - auth_ratio)) * boost
            scored.append({**art, "score": round(score, 4)})

        scored.sort(key=lambda a: a["score"], reverse=True)
        return scored[:10]

    # ── Algorithm C: Freshness ─────────────────────────────

    def _rank_freshness(self, articles: list[dict], now: datetime) -> list[dict]:
        cfg = self.config.get("scoring", {}).get("algorithms", {}).get("freshness", {})
        decay = cfg.get("freshness_decay", 0.8)
        w_fresh = cfg.get("recency_ratio", 0.65)
        w_surprise = cfg.get("surprise_ratio", 0.2)
        w_social = cfg.get("social_ratio", 0.15)

        # Build corpus for TF-IDF-based surprise computation
        all_titles = [art.get("title", "") for art in articles]

        scored = []
        for art in articles:
            points = art.get("points", 0) or 0
            comments = art.get("comments", 0) or 0
            age_hours = self._age_hours(art.get("published_at"), now)

            freshness = 1.0 / ((age_hours + 1) ** decay)
            surprise = self._title_novelty(art.get("title", ""), all_titles) * 0.3
            social = math.log10(points + comments + 2) * 0.15

            score = freshness * w_fresh + surprise * w_surprise + social * w_social
            scored.append({**art, "score": round(score, 4)})

        scored.sort(key=lambda a: a["score"], reverse=True)
        return scored[:10]

    # ── Helpers ───────────────────────────────────────────

    def _age_hours(self, published_at, now: datetime) -> float:
        if not published_at:
            return 72  # Default: 3 days old
        try:
            if isinstance(published_at, str):
                published_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            delta = now - published_at.replace(tzinfo=timezone.utc) if published_at.tzinfo is None else now - published_at
            return max(0, delta.total_seconds() / 3600)
        except Exception:
            return 72

    def _source_boost(self, source: str, weights: dict) -> float:
        """Match source string against weight map using partial matching."""
        if not weights:
            return 1.0
        source_lower = source.lower()
        for key, weight in weights.items():
            if key in source_lower:
                return float(weight)
        return 0.7  # Default for unknown sources

    def _title_novelty(self, title: str, all_titles: list[str]) -> float:
        """Simple bag-of-words cosine distance from the average title vector.
        Higher = more unique/surprising.
        """
        if len(all_titles) <= 1:
            return 0.5

        def tokenize(t: str) -> set[str]:
            return set(re.findall(r"[a-zA-Z]+", t.lower()))

        target_tokens = tokenize(title)
        if not target_tokens:
            return 0.5

        # Average overlap with all other titles
        overlaps = []
        for other in all_titles:
            other_tokens = tokenize(other)
            if not other_tokens:
                continue
            # Jaccard-like: intersection / union
            intersect = len(target_tokens & other_tokens)
            union = len(target_tokens | other_tokens)
            if union > 0:
                overlaps.append(intersect / union)

        if not overlaps:
            return 0.5

        avg_overlap = sum(overlaps) / len(overlaps)
        return 1.0 - avg_overlap  # 1 = completely unique
