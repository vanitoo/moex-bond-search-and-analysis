from unittest.mock import Mock, patch

import requests

from moex_bond_search_and_analysis import news


def test_google_search_retries_transient_ssl_error():
    good_response = Mock()
    good_response.content = (
        b"<?xml version='1.0' encoding='UTF-8'?>"
        b"<rss version='2.0'><channel><title>Google News</title></channel></rss>"
    )
    good_response.ok = True
    good_response.raise_for_status.return_value = None

    logger = Mock()
    with (
        patch.object(
            news.requests,
            "get",
            side_effect=[requests.exceptions.SSLError("temporary"), good_response],
        ) as request,
        patch.object(news.time, "sleep") as sleep,
    ):
        result = news.google_search("Тест", logger)

    assert result == []
    assert request.call_count == 2
    sleep.assert_called_once_with(news.GOOGLE_NEWS_RETRY_DELAY)


def test_google_search_raises_after_all_attempts():
    logger = Mock()
    error = requests.exceptions.SSLError("temporary")

    with (
        patch.object(news.requests, "get", side_effect=error) as request,
        patch.object(news.time, "sleep") as sleep,
    ):
        try:
            news.google_search("Тест", logger)
        except RuntimeError as exc:
            assert "после 3 попыток" in str(exc)
        else:
            raise AssertionError("RuntimeError was not raised")

    assert request.call_count == news.GOOGLE_NEWS_ATTEMPTS
    assert sleep.call_count == news.GOOGLE_NEWS_ATTEMPTS - 1
