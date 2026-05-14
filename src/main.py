"""FreshRSS Article Limiter CLI entry point."""
import argparse
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from freshrss_api import FreshRSSAPI
from langchain_openai import ChatOpenAI

from src.limiter import (
    add_rating,
    fetch_unread_articles,
    load_cache,
    mark_articles_as_read,
    organize_articles,
    partition_articles,
    rate_article,
    save_cache,
    sort_by_rating,
    RatingSchema,
    RatedArticle,
)
import json


def rated_articles_to_json(articles: list[RatedArticle]) -> list[dict]:
    return [
        {
            "id": a.id,
            "title": a.title,
            "author": a.author,
            "url": a.url,
            "feed_id": a.feed_id,
            "rating": a.rating,
            "content": a.content,
        }
        for a in articles
    ]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def load_system_prompt(filename: str) -> str:
    logger.info("Loading system prompt from %s", filename)
    path = Path(filename)
    if not path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {filename}")
    prompt = path.read_text(encoding="utf-8").strip()
    logger.info("Loaded prompt (%s characters)", len(prompt))
    return prompt


def main() -> None:
    parser = argparse.ArgumentParser(description="Limit the number of unread articles in FreshRSS.")
    parser.add_argument("--dry-run", action="store_true", help="Do not actually mark articles as read")
    parser.add_argument("--verbose", action="store_true", help="Show LLM prompts, responses, and JSON dumps")
    parser.add_argument("--rate-limiter", type=float, default=None, help="Override RATE_LIMITER_DELAY between LLM calls")
    parser.add_argument("--nb-evaluated", type=int, default=5, help="Number of articles to evaluate in dry-run mode (default: 5)")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        for handler in logging.getLogger().handlers:
            handler.setLevel(logging.DEBUG)

    load_dotenv(override=True)
    logger.info("Loaded environment variables")

    host = os.environ["FRESHRSS_PYTHON_API_HOST"]
    username = os.environ["FRESHRSS_PYTHON_API_USERNAME"]
    password = os.environ["FRESHRSS_PYTHON_API_PASSWORD"]
    openai_base = os.environ["OPENAI_BASE_URL"]
    openai_key = os.environ["OPENAI_API_KEY"]
    inference_model = os.environ["INFERENCE_MODEL"]
    prompt_filename = os.environ["USER_PROMPT_FILENAME"]
    nb_articles_kept = int(os.environ["NB_ARTICLES_KEEPT"])
    rate_limiter_delay = args.rate_limiter if args.rate_limiter is not None else 0.0
    enable_thinking = os.environ.get("ENABLE_THINKING", "false").lower() in ("true", "1", "yes")
    reasoning_effort = os.environ.get("REASONING_EFFORT", "medium") if enable_thinking else None
    cache_filename = os.environ.get("CACHE_FILENAME", "scores_cache.json")
    logger.info("FreshRSS host: %s", host)
    logger.info("LLM model: %s", inference_model)
    logger.info("NB_ARTICLES_KEEPT=%s", nb_articles_kept)
    logger.info("RATE_LIMITER_DELAY=%.2f seconds", rate_limiter_delay)
    logger.info("Cache file: %s", cache_filename)
    logger.info("Thinking enabled: %s", enable_thinking)
    if enable_thinking:
        logger.info("Reasoning effort: %s", reasoning_effort)

    client = FreshRSSAPI(host=host, username=username, password=password)
    logger.info("FreshRSS API client initialized")

    llm_kwargs = {
        "base_url": openai_base,
        "api_key": openai_key,
        "model": inference_model,
        "temperature": 0.0,
    }
    if enable_thinking:
        llm_kwargs["reasoning_effort"] = reasoning_effort

    base_llm = ChatOpenAI(**llm_kwargs)
    structured_llm = base_llm.with_structured_output(RatingSchema)
    logger.info("LLM client initialized with structured output and plain-text fallback")

    system_prompt = load_system_prompt(prompt_filename)
    cache = load_cache(cache_filename)
    logger.info("Loaded %s cached ratings", len(cache))

    dry_run = args.dry_run
    max_articles = args.nb_evaluated if dry_run else None
    if dry_run:
        logger.info("DRY-RUN mode active: limiting to %s articles", max_articles)
    else:
        logger.info("LIVE mode: processing all unread articles")

    raw_items = fetch_unread_articles(client, max_articles=max_articles)
    logger.info("Fetched %s unread articles", len(raw_items))

    if not raw_items:
        logger.info("No unread articles found. Exiting.")
        return

    articles = organize_articles(raw_items)
    rated_articles = []
    for idx, article in enumerate(articles, start=1):
        logger.info(
            "Rating article %s/%s: id=%s title=%s",
            idx,
            len(articles),
            article.id,
            article.title[:50],
        )
        if rate_limiter_delay > 0 and idx > 1:
            logger.info("Rate limiter: sleeping %.2f seconds", rate_limiter_delay)
            time.sleep(rate_limiter_delay)
        
        # Check cache first
        cache_key = str(article.id)
        if cache_key in cache:
            logger.info("Using cached rating %.2f for article %s", cache[cache_key], article.id)
            rating = cache[cache_key]
        else:
            rating = rate_article(
                article, structured_llm, base_llm, system_prompt, verbose=args.verbose
            )
        rated_articles.append(add_rating(article, rating))
        logger.info("Rated article %s: %.2f", article.id, rating)

    if args.verbose:
        logger.debug(
            "[Rated articles JSON before sorting] %s",
            json.dumps(
                [
                    {
                        "id": a.id,
                        "title": a.title,
                        "author": a.author,
                        "url": a.url,
                        "feed_id": a.feed_id,
                        "rating": a.rating,
                    }
                    for a in rated_articles
                ],
                ensure_ascii=False,
                indent=2,
            ),
        )

    sorted_articles = sort_by_rating(rated_articles)
    logger.info("Sorted %s articles by rating", len(sorted_articles))

    kept, to_mark = partition_articles(sorted_articles, nb_articles_kept)
    logger.info("Partition complete: keeping %s, marking %s as read", len(kept), len(to_mark))

    mark_articles_as_read(client, to_mark, dry_run=dry_run)
    
    # Save ratings to cache for future runs (all processed articles)
    for article in rated_articles:
        cache[str(article.id)] = article.rating
    save_cache(cache_filename, cache)
    logger.info("Done!")


if __name__ == "__main__":
    main()
