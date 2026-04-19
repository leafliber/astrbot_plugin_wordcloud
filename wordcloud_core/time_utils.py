import re
from datetime import datetime, timedelta
from typing import Optional

_TIME_KEYWORDS = {
    "今日": "today",
    "今天": "today",
    "昨日": "yesterday",
    "昨天": "yesterday",
    "本周": "this_week",
    "这周": "this_week",
    "上周": "last_week",
    "本月": "this_month",
    "这个月": "this_month",
    "上月": "last_month",
    "上个月": "last_month",
    "今年": "this_year",
    "年度": "this_year",
}


def parse_time_keyword(text: str) -> Optional[str]:
    if not text:
        return None
    text = text.strip()
    for cn, key in _TIME_KEYWORDS.items():
        if cn in text:
            return key
    return None


def get_time_range(keyword: str) -> tuple[int, int]:
    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if keyword == "today":
        start = today
        end = now
    elif keyword == "yesterday":
        start = today - timedelta(days=1)
        end = today
    elif keyword == "this_week":
        start = today - timedelta(days=today.weekday())
        end = now
    elif keyword == "last_week":
        start = today - timedelta(days=today.weekday() + 7)
        end = today - timedelta(days=today.weekday())
    elif keyword == "this_month":
        start = today.replace(day=1)
        end = now
    elif keyword == "last_month":
        first_this = today.replace(day=1)
        end = first_this
        last_day_prev = first_this - timedelta(days=1)
        start = last_day_prev.replace(day=1)
    elif keyword == "this_year":
        start = today.replace(month=1, day=1)
        end = now
    else:
        start = today
        end = now

    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def format_period_name(keyword: str) -> str:
    names = {
        "today": "今日",
        "yesterday": "昨日",
        "this_week": "本周",
        "last_week": "上周",
        "this_month": "本月",
        "last_month": "上月",
        "this_year": "今年",
    }
    return names.get(keyword, keyword)
