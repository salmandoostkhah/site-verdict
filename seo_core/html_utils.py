"""ابزار مشترک تجزیه HTML.

HTML یکسان در چند تحلیلگر خوانده می‌شود؛ این تابع آن را یک‌بار تجزیه و کش می‌کند.
نکته: هر بار یک کپی مستقل برمی‌گردد؛ تغییر آن روی کش اثر ندارد.
"""

from __future__ import annotations

import copy
from functools import lru_cache

from bs4 import BeautifulSoup


@lru_cache(maxsize=8)
def _parse_cached(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def parse_html(html: str | None) -> BeautifulSoup:
    """سوپ برای HTML داده‌شده؛ هر فراخوانی یک نسخهٔ مستقل برمی‌گرداند.

    تجزیه یک‌بار انجام و کش می‌شود، ولی کپی عمیق برگردانده می‌شود تا تغییر
    (decompose/extract) یک تحلیلگر روی تحلیلگر دیگر اثر نگذارد.
    """
    return copy.deepcopy(_parse_cached(html or ""))