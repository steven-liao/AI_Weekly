from .base import BaseCollector
from .hackernews import HackerNewsCollector
from .reddit import RedditCollector
from .rss import RSSCollector
from .arxiv import ArxivCollector
from .newsapi import GNewsCollector

__all__ = [
    "BaseCollector",
    "HackerNewsCollector",
    "RedditCollector",
    "RSSCollector",
    "ArxivCollector",
    "GNewsCollector",
]
