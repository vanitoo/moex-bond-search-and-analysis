from unittest.mock import Mock, patch

import requests

from moex_bond_search_and_analysis import news_sources


def _response():
    response = Mock()
    response.content = (
        b"<?xml version='1.0' encoding='UTF-8'?>"
        b"<rss version='2.0'><channel><title>Google News</title></channel></rss>"
    )
    response.raise_for_status.return_value = None
    return response


def test_google_news_retries_transient_ssl_error():
    session = Mock()
    session.get.side_effect = [requests.exceptions.SSLError("temporary"), _response()]
    with (
        patch.object(news_sources, "browser_session", return_value=session),
        patch.object(news_sources.time, "sleep") as sleep,
    ):
        result = news_sources.google_news("Тест")
    assert result == []
    assert session.get.call_count == 2
    sleep.assert_called_once_with(news_sources.DEFAULT_RETRY_DELAY)


def test_google_news_raises_after_all_attempts():
    session = Mock()
    session.get.side_effect = requests.exceptions.SSLError("temporary")
    with (
        patch.object(news_sources, "browser_session", return_value=session),
        patch.object(news_sources.time, "sleep") as sleep,
    ):
        try:
            news_sources.google_news("Тест")
        except requests.exceptions.SSLError:
            pass
        else:
            raise AssertionError("SSLError was not raised")
    assert session.get.call_count == news_sources.DEFAULT_ATTEMPTS
    assert sleep.call_count == news_sources.DEFAULT_ATTEMPTS - 1
