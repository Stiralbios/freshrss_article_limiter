"""Unit tests for the FreshRSS Article Limiter."""
import unittest
from unittest.mock import MagicMock, patch

from src import limiter
from src.limiter import (
    DEFAULT_RATING,
    Article,
    RatedArticle,
    RatingSchema,
    add_rating,
    fetch_unread_articles,
    mark_articles_as_read,
    organize_articles,
    partition_articles,
    rate_article,
    sort_by_rating,
)


def reset_structured_flag():
    """Reset the global flag so tests don't pollute each other."""
    limiter._structured_output_available = True


class TestFetchUnreadArticles(unittest.TestCase):
    def test_returns_raw_items(self):
        client = MagicMock()
        mock_items = [
            MagicMock(id=1, title="a", author="x", html="<p>hi</p>", url="u1", is_saved=False, is_read=False, created_on_time=1),
            MagicMock(id=2, title="b", author="y", html="<p>hello</p>", url="u2", is_saved=False, is_read=False, created_on_time=2),
        ]
        client.get_unreads.return_value = mock_items

        result = fetch_unread_articles(client)
        self.assertEqual(result, mock_items)
        client.get_unreads.assert_called_once()

    def test_limits_to_max_articles(self):
        client = MagicMock()
        mock_items = list(range(15))
        client.get_unreads.return_value = mock_items

        result = fetch_unread_articles(client, max_articles=10)
        self.assertEqual(result, list(range(10)))


class TestOrganizeArticles(unittest.TestCase):
    def test_organizes_raw_items(self):
        mock_items = [
            MagicMock(id=101, title="T1", author="A1", html="<p>D1</p>", url="U1", readable="D1", is_saved=False, is_read=False, created_on_time=1),
            MagicMock(id=202, title="T2", author="A2", html="<p>D2</p>", url="U2", readable="D2", is_saved=True, is_read=True, created_on_time=2),
        ]

        articles = organize_articles(mock_items)
        self.assertEqual(len(articles), 2)

        self.assertEqual(articles[0].id, 101)
        self.assertEqual(articles[0].title, "T1")
        self.assertEqual(articles[0].author, "A1")
        self.assertEqual(articles[0].content, "D1")
        self.assertEqual(articles[0].url, "U1")

        self.assertEqual(articles[1].id, 202)
        self.assertEqual(articles[1].title, "T2")
        self.assertEqual(articles[1].content, "D2")

    def test_returns_empty_list_for_empty_input(self):
        self.assertEqual(organize_articles([]), [])


class TestRateArticle(unittest.TestCase):
    def setUp(self):
        reset_structured_flag()

    def test_returns_rating_from_structured_output(self):
        article = Article(id=1, title="Test", author="A", content="Body", url="url", feed_id=10)

        mock_structured_llm = MagicMock()
        mock_structured_llm.invoke.return_value = RatingSchema(score=7.5)
        mock_base_llm = MagicMock()

        rating = rate_article(article, mock_structured_llm, mock_base_llm, "system prompt")
        self.assertEqual(rating, 7.5)
        mock_structured_llm.invoke.assert_called_once()
        mock_base_llm.invoke.assert_not_called()

    def test_clamps_out_of_range_high(self):
        article = Article(id=1, title="Test", author="A", content="Body", url="url", feed_id=10)
        mock_structured_llm = MagicMock()
        mock_structured_llm.invoke.return_value = type("FakeRating", (), {"score": 150.0})()
        mock_base_llm = MagicMock()

        rating = rate_article(article, mock_structured_llm, mock_base_llm, "system prompt")
        self.assertEqual(rating, 100.0)

    def test_clamps_out_of_range_low(self):
        article = Article(id=1, title="Test", author="A", content="Body", url="url", feed_id=10)
        mock_structured_llm = MagicMock()
        mock_structured_llm.invoke.return_value = type("FakeRating", (), {"score": -3.0})()
        mock_base_llm = MagicMock()

        rating = rate_article(article, mock_structured_llm, mock_base_llm, "system prompt")
        self.assertEqual(rating, 0.0)

    def test_fallback_to_plain_text(self):
        article = Article(id=1, title="Test", author="A", content="Body", url="url", feed_id=10)

        mock_structured_llm = MagicMock()
        mock_structured_llm.invoke.side_effect = Exception("structured output fails")

        mock_response = MagicMock()
        mock_response.content = "The rating is 8.5"
        mock_base_llm = MagicMock()
        mock_base_llm.invoke.return_value = mock_response

        rating = rate_article(article, mock_structured_llm, mock_base_llm, "system prompt")
        self.assertEqual(rating, 8.5)
        mock_base_llm.invoke.assert_called_once()

    def test_fallback_default_when_no_number(self):
        article = Article(id=1, title="Test", author="A", content="Body", url="url", feed_id=10)

        mock_structured_llm = MagicMock()
        mock_structured_llm.invoke.side_effect = Exception("structured output fails")

        mock_response = MagicMock()
        mock_response.content = "No idea"
        mock_base_llm = MagicMock()
        mock_base_llm.invoke.return_value = mock_response

        rating = rate_article(article, mock_structured_llm, mock_base_llm, "system prompt")
        self.assertEqual(rating, DEFAULT_RATING)

    def test_fallback_default_when_both_fail(self):
        article = Article(id=1, title="Test", author="A", content="Body", url="url", feed_id=10)

        mock_structured_llm = MagicMock()
        mock_structured_llm.invoke.side_effect = Exception("structured output fails")
        mock_base_llm = MagicMock()
        mock_base_llm.invoke.side_effect = Exception("fallback fails")

        rating = rate_article(article, mock_structured_llm, mock_base_llm, "system prompt")
        self.assertEqual(rating, DEFAULT_RATING)

    def test_permanently_disables_structured_after_first_failure(self):
        """Once structured output fails, subsequent articles skip it entirely."""
        article = Article(id=1, title="Test", author="A", content="Body", url="url", feed_id=10)

        mock_structured_llm = MagicMock()
        mock_structured_llm.invoke.side_effect = Exception("structured output fails")

        mock_response = MagicMock()
        mock_response.content = "7"
        mock_base_llm = MagicMock()
        mock_base_llm.invoke.return_value = mock_response

        # First call disables structured output
        rate_article(article, mock_structured_llm, mock_base_llm, "system prompt")

        # Second article should go straight to fallback
        mock_structured_llm.reset_mock()
        mock_base_llm.reset_mock()

        article2 = Article(id=2, title="Test2", author="B", content="Body2", url="url2", feed_id=11)
        rating = rate_article(article2, mock_structured_llm, mock_base_llm, "system prompt")
        self.assertEqual(rating, 7.0)
        mock_structured_llm.invoke.assert_not_called()
        mock_base_llm.invoke.assert_called_once()


class TestAddRating(unittest.TestCase):
    def test_adds_rating_field(self):
        article = Article(id=1, title="Test", author="A", content="Body", url="url", feed_id=10)
        rated = add_rating(article, 8.5)

        self.assertIsInstance(rated, RatedArticle)
        self.assertEqual(rated.id, 1)
        self.assertEqual(rated.title, "Test")
        self.assertEqual(rated.rating, 8.5)


class TestSortByRating(unittest.TestCase):
    def test_sorts_descending(self):
        articles = [
            RatedArticle(id=1, title="A", author="X", content="C", url="U", feed_id=0, rating=3.0),
            RatedArticle(id=2, title="B", author="Y", content="C", url="V", feed_id=0, rating=9.5),
            RatedArticle(id=3, title="C", author="Z", content="C", url="W", feed_id=0, rating=6.0),
        ]

        sorted_articles = sort_by_rating(articles)
        ratings = [a.rating for a in sorted_articles]
        self.assertEqual(ratings, [9.5, 6.0, 3.0])


class TestPartitionArticles(unittest.TestCase):
    def test_partitions_correctly(self):
        articles = [
            RatedArticle(id=1, title="A", author="X", content="C", url="U", feed_id=0, rating=9.0),
            RatedArticle(id=2, title="B", author="Y", content="C", url="V", feed_id=0, rating=8.0),
            RatedArticle(id=3, title="C", author="Z", content="C", url="W", feed_id=0, rating=7.0),
            RatedArticle(id=4, title="D", author="W", content="C", url="X", feed_id=0, rating=6.0),
        ]

        kept, to_mark = partition_articles(articles, keep_count=2)
        self.assertEqual(len(kept), 2)
        self.assertEqual(len(to_mark), 2)
        self.assertEqual([a.id for a in kept], [1, 2])
        self.assertEqual([a.id for a in to_mark], [3, 4])

    def test_keep_count_zero(self):
        articles = [
            RatedArticle(id=1, title="A", author="X", content="C", url="U", feed_id=0, rating=9.0),
        ]
        kept, to_mark = partition_articles(articles, keep_count=0)
        self.assertEqual(kept, [])
        self.assertEqual(len(to_mark), 1)

    def test_keep_count_exceeds_list(self):
        articles = [
            RatedArticle(id=1, title="A", author="X", content="C", url="U", feed_id=0, rating=9.0),
        ]
        kept, to_mark = partition_articles(articles, keep_count=5)
        self.assertEqual(len(kept), 1)
        self.assertEqual(to_mark, [])


class TestMarkArticlesAsRead(unittest.TestCase):
    def test_calls_set_mark_for_each_item(self):
        client = MagicMock()
        articles = [
            RatedArticle(id=10, title="A", author="X", content="C", url="U", feed_id=0, rating=1.0),
            RatedArticle(id=20, title="B", author="Y", content="C", url="V", feed_id=0, rating=2.0),
        ]

        mark_articles_as_read(client, articles, dry_run=False)
        self.assertEqual(client.set_mark.call_count, 2)
        client.set_mark.assert_any_call(as_="read", id=10)
        client.set_mark.assert_any_call(as_="read", id=20)

    def test_dry_run_does_not_call_api(self):
        client = MagicMock()
        articles = [
            RatedArticle(id=10, title="A", author="X", content="C", url="U", feed_id=0, rating=1.0),
        ]

        mark_articles_as_read(client, articles, dry_run=True)
        client.set_mark.assert_not_called()


if __name__ == "__main__":
    unittest.main()
