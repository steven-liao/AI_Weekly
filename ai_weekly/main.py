"""AI Weekly Top 10 — Pipeline Orchestrator.

Usage:
  python -m ai_weekly.main --run                     # Full pipeline
  python -m ai_weekly.main --dry-run                 # Preview: collect + rank + summarize only
  python -m ai_weekly.main --run --skip-images       # No image generation
  python -m ai_weekly.main --run --from 2026-05-11 --to 2026-05-18
  python -m ai_weekly.main --stage collect           # Single stage
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta

from ai_weekly.config import load_config
from ai_weekly.db import Database
from ai_weekly.collector import (
    HackerNewsCollector,
    RedditCollector,
    RSSCollector,
    ArxivCollector,
    GNewsCollector,
)
from ai_weekly.ranker import Ranker
from ai_weekly.summarizer import Summarizer
from ai_weekly.image_gen import create_image_generator
from ai_weekly.composer import compose_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("ai-weekly")


def main():
    parser = argparse.ArgumentParser(description="AI Weekly Top 10 Pipeline")
    parser.add_argument("--run", action="store_true", help="Execute full pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Preview: collect + rank + summarize only")
    parser.add_argument("--skip-images", action="store_true", help="Skip image generation")
    parser.add_argument("--stage", choices=["collect", "rank", "summarize", "images", "compose"])
    parser.add_argument("--from", dest="date_from", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to", dest="date_to", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--output-dir", type=str, default="output", help="Output directory")
    args = parser.parse_args()

    config = load_config()

    if args.run or args.dry_run:
        run_pipeline(
            config,
            dry_run=args.dry_run,
            skip_images=args.skip_images,
            date_from=args.date_from,
            date_to=args.date_to,
            output_base=args.output_dir,
        )
    elif args.stage:
        run_single_stage(config, args.stage)
    else:
        parser.print_help()


def run_pipeline(config, dry_run=False, skip_images=False,
                 date_from=None, date_to=None, output_base="output"):
    logger.info("=" * 50)
    logger.info("AI Weekly Pipeline Started")
    logger.info("=" * 50)

    # Resolve date range
    if date_to:
        end_date = datetime.fromisoformat(date_to)
    else:
        end_date = datetime.now()

    if date_from:
        start_date = datetime.fromisoformat(date_from)
        lookback = (end_date - start_date).days
    else:
        lookback = config.schedule.get("lookback_days", 7)
        start_date = end_date - timedelta(days=lookback)

    week_start_str = start_date.strftime("%Y-%m-%d")

    logger.info(f"Date range: {start_date.strftime('%Y-%m-%d')} → {end_date.strftime('%Y-%m-%d')} ({lookback}d)")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'FULL'}{' (no images)' if skip_images else ''}")

    db = Database()

    # ── Stage 1: Collect ──────────────────────────────────
    logger.info("Stage 1: Collecting articles...")
    try:
        _run_collectors(config, db, lookback)
    except Exception as e:
        logger.error(f"Collect stage failed: {e}", exc_info=True)
        db.close()
        sys.exit(1)

    # ── Stage 2: Rank ─────────────────────────────────────
    logger.info("Stage 2: Ranking with 3 algorithms...")
    try:
        ranker = Ranker(config._raw)
        results = ranker.run(db, lookback)
        ranker.save_results(db, week_start_str, results)
    except Exception as e:
        logger.error(f"Rank stage failed: {e}", exc_info=True)
        db.close()
        sys.exit(1)

    # ── Stage 3: Summarize ────────────────────────────────
    logger.info("Stage 3: Generating summaries...")
    try:
        summarizer = Summarizer(config)
        # Collect all unique articles across all 3 algorithms
        seen_ids = set()
        all_articles: list[dict] = []
        for alg_name in ["hotness", "impact", "freshness"]:
            for art in results.get(alg_name, []):
                if art["id"] not in seen_ids:
                    seen_ids.add(art["id"])
                    # Fetch full article data from DB
                    full = db.get_article_by_id(art["id"])
                    if full:
                        full["score"] = art["score"]
                        full["algorithm"] = alg_name
                        all_articles.append(full)

        logger.info(f"Unique articles to process: {len(all_articles)}")
        generated = summarizer.generate(db, all_articles)

        # Map generated content back to results
        gen_map = {g.article_id: g for g in generated}
        for alg_name in ["hotness", "impact", "freshness"]:
            for art in results.get(alg_name, []):
                g = gen_map.get(art["id"])
                if g:
                    art["summary_cn"] = g.summary_cn
                    art["image_prompt"] = g.image_prompt
    except Exception as e:
        logger.error(f"Summarize stage failed: {e}", exc_info=True)
        db.close()
        sys.exit(1)

    if dry_run:
        logger.info("DRY RUN complete — skipping image generation and composition.")
        _print_dry_run(results)
        db.close()
        return

    # ── Stage 4: Generate Images ───────────────────────────
    img_enabled = not skip_images and config.images.provider != "disabled"
    if img_enabled:
        logger.info(f"Stage 4: Generating images (provider={config.images.provider})...")
        try:
            img_gen = create_image_generator(config)
            for alg_name in ["hotness", "impact", "freshness"]:
                arts = results.get(alg_name, [])
                if arts:
                    out_dir = f"{output_base}/{week_start_str}/{alg_name}"
                    img_gen.generate_all(arts, out_dir)
        except Exception as e:
            logger.error(f"Image generation failed: {e}", exc_info=True)
    elif skip_images:
        logger.info("Stage 4: Images skipped (--skip-images)")
    else:
        logger.info("Stage 4: Images disabled (provider=disabled in config)")

    # ── Stage 5: Compose ───────────────────────────────────
    logger.info("Stage 5: Composing newsletters...")
    try:
        output_dir = f"{output_base}/{week_start_str}"
        compose_all(results, output_dir, week_start_str)
        logger.info(f"Output written to {output_dir}/")
    except Exception as e:
        logger.error(f"Compose stage failed: {e}", exc_info=True)
        db.close()
        sys.exit(1)

    db.close()
    logger.info("=" * 50)
    logger.info("Pipeline Complete!")
    logger.info(f"Output: {output_dir}/")
    logger.info("=" * 50)


def _run_collectors(config, db: Database, lookback_days: int):
    """Run all enabled collectors."""
    src = config.sources
    proxy = config.proxy

    collectors = [
        (src.get("hackernews"), HackerNewsCollector),
        (src.get("reddit"), RedditCollector),
        (src.get("rss"), RSSCollector),
        (src.get("arxiv"), ArxivCollector),
        (src.get("gnews"), GNewsCollector),
    ]

    total = 0
    for source_cfg, cls in collectors:
        if source_cfg and source_cfg.enabled:
            c = cls(source_cfg.config, proxy_config=proxy)
            try:
                new = c.collect(db, lookback_days)
                total += len(new)
            finally:
                c.close()

    logger.info(f"Total new articles collected: {total}")


def _print_dry_run(results: dict[str, list[dict]]):
    """Print a quick preview of the rankings."""
    labels = {"hotness": "热度优先", "impact": "影响力优先", "freshness": "新鲜度优先"}
    for alg, articles in results.items():
        label = labels.get(alg, alg)
        print(f"\n{'─' * 60}")
        print(f"  {label} ({alg})")
        print(f"{'─' * 60}")
        for i, art in enumerate(articles[:10], 1):
            title = art.get("title", "")
            score = art.get("score", 0)
            summary = (art.get("summary_cn") or "")[:80]
            print(f"  {i:2d}. [{score:.4f}] {title[:70]}")
            if summary:
                print(f"      {summary}")


def run_single_stage(config, stage_name: str):
    """Execute a single stage (for debugging)."""
    db = Database()
    proxy = config.proxy

    if stage_name == "collect":
        _run_collectors(config, db, config.schedule.get("lookback_days", 7))
    elif stage_name == "rank":
        ranker = Ranker(config._raw)
        results = ranker.run(db, config.schedule.get("lookback_days", 7))
        for alg, arts in results.items():
            print(f"\n{alg}:")
            for a in arts[:5]:
                print(f"  {a['score']:.4f} {a['title'][:60]}")
    elif stage_name == "summarize":
        db_arts = db.get_recent_articles(7)
        if db_arts:
            summarizer = Summarizer(config)
            g = summarizer.generate(db, db_arts[:1])
            if g:
                print(f"Summary: {g[0].summary_cn}")
                print(f"Prompt: {g[0].image_prompt}")
    elif stage_name == "images":
        print("Use --run --skip-images to run without generating images")
    elif stage_name == "compose":
        print("Use --run to compose output")
    else:
        print(f"Unknown stage: {stage_name}")

    db.close()


if __name__ == "__main__":
    main()
