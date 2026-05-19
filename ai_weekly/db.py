"""SQLite database layer — schema creation & CRUD for articles."""

import json
import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


DB_PATH = Path(__file__).resolve().parent.parent / "data" / "ai_weekly.db"


@dataclass
class Article:
    id: Optional[int] = None
    content_hash: str = ""
    title: str = ""
    url: str = ""
    source: str = ""
    summary_raw: Optional[str] = None
    points: int = 0
    comments: int = 0
    top_comments: Optional[str] = None   # JSON array of {body, score, author}
    published_at: Optional[str] = None
    collected_at: Optional[str] = None

    @staticmethod
    def compute_hash(url: str, title: str) -> str:
        return hashlib.sha256(f"{url}\0{title}".encode()).hexdigest()


@dataclass
class WeeklyTop10:
    id: Optional[int] = None
    week_start: str = ""
    rank: int = 0
    article_id: int = 0
    score: float = 0.0
    algorithm: str = ""          # "hotness" | "impact" | "freshness"
    summary_cn: Optional[str] = None
    image_prompt: Optional[str] = None
    image_path: Optional[str] = None
    image_url: Optional[str] = None
    created_at: Optional[str] = None


@dataclass
class PublishLog:
    id: Optional[int] = None
    week_start: str = ""
    platform: str = "xiaohongshu"
    status: str = ""
    note_url: Optional[str] = None
    published_at: Optional[str] = None
    error_message: Optional[str] = None


class Database:
    def __init__(self, path: Optional[str] = None):
        self.path = path or str(DB_PATH)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_hash TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                source TEXT NOT NULL,
                summary_raw TEXT,
                points INTEGER DEFAULT 0,
                comments INTEGER DEFAULT 0,
                top_comments TEXT,
                published_at TEXT,
                collected_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS weekly_top10 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start TEXT NOT NULL,
                rank INTEGER NOT NULL,
                article_id INTEGER REFERENCES articles(id),
                score REAL NOT NULL,
                algorithm TEXT NOT NULL DEFAULT '',
                summary_cn TEXT,
                image_prompt TEXT,
                image_path TEXT,
                image_url TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS publish_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start TEXT NOT NULL,
                platform TEXT DEFAULT 'xiaohongshu',
                status TEXT,
                note_url TEXT,
                published_at TEXT DEFAULT (datetime('now')),
                error_message TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_articles_hash ON articles(content_hash);
            CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source);
            CREATE INDEX IF NOT EXISTS idx_articles_collected ON articles(collected_at);
            CREATE INDEX IF NOT EXISTS idx_top10_week ON weekly_top10(week_start);
            CREATE INDEX IF NOT EXISTS idx_top10_algorithm ON weekly_top10(algorithm);
        """)
        self.conn.commit()

    # ── Articles CRUD ──────────────────────────────────────

    def upsert_article(self, article: Article) -> Optional[int]:
        """Insert or skip if content_hash already exists. Returns the article id."""
        article.content_hash = Article.compute_hash(article.url, article.title)
        try:
            cur = self.conn.execute("""
                INSERT INTO articles
                    (content_hash, title, url, source, summary_raw,
                     points, comments, top_comments, published_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                article.content_hash, article.title, article.url, article.source,
                article.summary_raw, article.points, article.comments,
                article.top_comments, article.published_at,
            ))
            self.conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            # Duplicate — skip
            return None

    def get_recent_articles(self, lookback_days: int = 7) -> list[dict]:
        """Get all articles collected in the past N days."""
        rows = self.conn.execute("""
            SELECT * FROM articles
            WHERE collected_at >= datetime('now', ? || ' days')
            ORDER BY collected_at DESC
        """, (f"-{lookback_days}",)).fetchall()
        return [dict(r) for r in rows]

    def get_article_by_id(self, article_id: int) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        return dict(row) if row else None

    # ── Weekly Top 10 ──────────────────────────────────────

    def clear_weekly_top10(self, week_start: str, algorithm: str):
        self.conn.execute(
            "DELETE FROM weekly_top10 WHERE week_start = ? AND algorithm = ?",
            (week_start, algorithm),
        )
        self.conn.commit()

    def insert_top10_entry(self, record: WeeklyTop10):
        self.conn.execute("""
            INSERT INTO weekly_top10
                (week_start, rank, article_id, score, algorithm,
                 summary_cn, image_prompt, image_path, image_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.week_start, record.rank, record.article_id, record.score,
            record.algorithm, record.summary_cn, record.image_prompt,
            record.image_path, record.image_url,
        ))
        self.conn.commit()

    def get_weekly_top10(self, week_start: str, algorithm: str) -> list[dict]:
        rows = self.conn.execute("""
            SELECT * FROM weekly_top10
            WHERE week_start = ? AND algorithm = ?
            ORDER BY rank
        """, (week_start, algorithm)).fetchall()
        return [dict(r) for r in rows]

    # ── Publish Log ────────────────────────────────────────

    def log_publish(self, record: PublishLog):
        self.conn.execute("""
            INSERT INTO publish_log (week_start, platform, status, note_url, error_message)
            VALUES (?, ?, ?, ?, ?)
        """, (record.week_start, record.platform, record.status,
              record.note_url, record.error_message))
        self.conn.commit()

    def close(self):
        self.conn.close()
