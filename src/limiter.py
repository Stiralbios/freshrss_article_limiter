"""FreshRSS Article Limiter functions."""
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

DEFAULT_RATING = 50.0
MAX_RETRIES = 2

# True until the first structured-output failure, then permanently False
# so we don't waste retries on every article when the model doesn't support it.
_structured_output_available: bool = True


@dataclass(frozen=True)
class Article:
    id: int
    title: str
    author: str
    content: str
    url: str
    feed_id: int


@dataclass(frozen=True)
class RatedArticle:
    id: int
    title: str
    author: str
    content: str
    url: str
    feed_id: int
    rating: float


class RatingSchema(BaseModel):
    """Structured output schema for the LLM rating."""
    score: float = Field(..., ge=0.0, le=100.0, description="Rating from 0.0 to 100.0")


def fetch_unread_articles(client, max_articles: int | None = None) -> list[Any]:
    """Fetch unread articles from FreshRSS.

    Args:
        client: FreshRSSAPI client instance.
        max_articles: If provided, limit the number of articles returned.

    Returns:
        List of raw item objects from the FreshRSS API.
    """
    logger.info("Fetching unread articles from FreshRSS...")
    items = client.get_unreads()
    logger.info("Fetched %s unread articles", len(items))
    if max_articles is not None:
        logger.info("Limiting to %s articles (dry-run mode)", max_articles)
        items = items[:max_articles]
    return items


def organize_articles(raw_items: list[Any]) -> list[Article]:
    """Normalize FreshRSS item objects into typed Article dataclasses.

    Args:
        raw_items: List of FreshRSS Item objects from the API.

    Returns:
        List of Article dataclasses.
    """
    logger.info("Organizing %s raw items into structured articles", len(raw_items))
    articles = []
    for item in raw_items:
        articles.append(
            Article(
                id=item.id,
                title=item.title or "",
                author=item.author or "",
                content=item.readable or "",
                url=item.url or "",
                feed_id=item.feed_id,
            )
        )
    logger.info("Finished organizing %s articles", len(articles))
    return articles


def rate_article(
    article: Article,
    structured_llm,
    base_llm,
    system_prompt: str,
    verbose: bool = False,
) -> float:
    """Send a single article to an LLM and return a float rating (0–100).

    Tries ``structured_llm`` first (with ``.with_structured_output(RatingSchema)``).
    If that fails on the *first* article, we record that the model doesn't support
    structured output and go straight to the plain-text fallback for all subsequent
    articles.  If both attempts fail, returns DEFAULT_RATING.

    Args:
        article: The Article to rate.
        structured_llm: LangChain runnable with structured output bound.
        base_llm: Fallback LangChain runnable *without* structured output.
        system_prompt: System prompt text to guide the LLM.
        verbose: Whether to dump the full prompt and raw LLM response.

    Returns:
        Rating clamped to the inclusive range [0.0, 100.0].
    """
    global _structured_output_available

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": f"Title: {article.title}\nAuthor: {article.author}\nContent: {article.content}",
        },
    ]

    # --- 1) Try structured output only if we believe it still works ---
    if _structured_output_available:
        if verbose:
            for msg in messages:
                logger.debug(
                    "[LLM prompt (structured)] role=%s content=%s",
                    msg["role"],
                    msg["content"][:500],
                )

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result: RatingSchema = structured_llm.invoke(messages)
                if verbose:
                    logger.debug(
                        "[LLM raw response (structured)] %s", result.model_dump_json()
                    )
                return max(0.0, min(100.0, result.score))
            except Exception as exc:
                logger.warning(
                    "Structured LLM rating failed for article %s (attempt %s/%s): %s",
                    article.id,
                    attempt,
                    MAX_RETRIES,
                    exc,
                )
                time.sleep(2 * attempt)

        # After retries exhausted on one article → model doesn't support structured output
        logger.info(
            "Structured output permanently disabled for this model after failure on article %s",
            article.id,
        )
        _structured_output_available = False

    # --- 2) Fallback to plain-text parsing ---
    fallback_messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                f"Title: {article.title}\nAuthor: {article.author}\n"
                f"Content: {article.content}\n\n"
                "Return ONLY a single number between 0 and 100."
            ),
        },
    ]
    if verbose:
        for msg in fallback_messages:
            logger.debug(
                "[LLM prompt (fallback)] role=%s content=%s",
                msg["role"],
                msg["content"][:500],
            )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            raw_response = base_llm.invoke(fallback_messages)
            text = (
                raw_response.content
                if hasattr(raw_response, "content")
                else str(raw_response)
            )
            if verbose:
                logger.debug("[LLM raw response (fallback)] %s", text[:500])

            match = re.search(r"(\d+(?:\.\d+)?)", text)
            if match:
                rating = float(match.group(1))
                logger.info(
                    "Parsed fallback rating %.2f for article %s", rating, article.id
                )
                return max(0.0, min(100.0, rating))
            else:
                raise ValueError(
                    f"No numeric rating found in response: {text[:200]}"
                )
        except Exception as exc:
            logger.warning(
                "Fallback LLM rating failed for article %s (attempt %s/%s): %s",
                article.id,
                attempt,
                MAX_RETRIES,
                exc,
            )
            time.sleep(2 * attempt)

    logger.error(
        "All LLM attempts exhausted for article %s; falling back to default %.1f",
        article.id,
        DEFAULT_RATING,
    )
    return DEFAULT_RATING


def add_rating(article: Article, rating: float) -> RatedArticle:
    """Return a new RatedArticle with the rating attached.

    Args:
        article: The source Article.
        rating: The LLM-generated rating.

    Returns:
        RatedArticle containing all of the original fields plus ``rating``.
    """
    return RatedArticle(
        id=article.id,
        title=article.title,
        author=article.author,
        content=article.content,
        url=article.url,
        feed_id=article.feed_id,
        rating=rating,
    )


def sort_by_rating(articles: list[RatedArticle]) -> list[RatedArticle]:
    """Sort articles by rating in descending order.

    Args:
        articles: List of RatedArticle objects.

    Returns:
        New list sorted from highest to lowest rating.
    """
    return sorted(articles, key=lambda a: a.rating, reverse=True)


def partition_articles(
    articles: list[RatedArticle], keep_count: int
) -> Tuple[list[RatedArticle], list[RatedArticle]]:
    """Split articles into those to keep and those to mark as read.

    Args:
        articles: Already sorted list of rated articles (descending).
        keep_count: Number of top-rated articles to keep unread.

    Returns:
        Tuple of (kept_articles, articles_to_mark_read).
    """
    if keep_count < 0:
        keep_count = 0
    kept = articles[:keep_count]
    rest = articles[keep_count:]
    return kept, rest


def mark_articles_as_read(
    client, articles: list[RatedArticle], dry_run: bool = False
) -> None:
    """Mark the provided articles as read via the FreshRSS API.

    Args:
        client: FreshRSSAPI client instance.
        articles: Articles to mark as read.
        dry_run: If True, print intentions without actually calling the API.
    """
    for article in articles:
        if dry_run:
            logger.info(
                "[DRY-RUN] Would mark article %s as read: %s",
                article.id,
                article.title,
            )
        else:
            logger.info("Marking article %s as read", article.id)
            client.set_mark(as_="read", id=article.id)
