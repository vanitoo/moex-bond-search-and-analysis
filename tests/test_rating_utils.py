from app.core.rating_utils import (
    RATING_ORDER,
    normalize_rating,
    rating_direction,
    rating_drop,
    rating_index,
)


def test_normalize_rating_handles_ru_suffix_and_noise():
    assert normalize_rating("AA+(RU)") == "AA+"
    assert normalize_rating("Рейтинг: BBB-(RU)") == "BBB-"
    assert normalize_rating("—") == ""
    assert normalize_rating(None) == ""


def test_rating_direction_uses_one_shared_scale():
    assert rating_direction("AA", "A+") > 0
    assert rating_direction("BBB", "A-") < 0
    assert rating_direction("", "A") == 0


def test_rating_drop_counts_only_downgrades():
    assert rating_drop("A", "BBB+") == RATING_ORDER.index("A") - RATING_ORDER.index("BBB+")
    assert rating_drop("BBB+", "A") == 0
    assert rating_index("AAA(RU)") == RATING_ORDER.index("AAA")
