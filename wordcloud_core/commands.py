from dataclasses import dataclass
from typing import Optional


_TIME_KEYWORDS = {
    "今日": ("today", "今日"), "今天": ("today", "今日"), "今": ("today", "今日"),
    "昨日": ("yesterday", "昨日"), "昨天": ("yesterday", "昨日"), "昨": ("yesterday", "昨日"),
    "本周": ("this_week", "本周"), "这周": ("this_week", "本周"), "本星期": ("this_week", "本周"),
    "上周": ("last_week", "上周"), "上星期": ("last_week", "上周"),
    "本月": ("this_month", "本月"), "这个月": ("this_month", "本月"),
    "上月": ("last_month", "上月"), "上个月": ("last_month", "上月"),
    "今年": ("this_year", "今年"), "本年度": ("this_year", "今年"), "年度": ("this_year", "今年"),
}

_MR_TIME_MAP = {
    "today": "today",
    "yesterday": "yesterday",
    "this_week": "week",
    "last_week": None,
    "this_month": "month",
    "last_month": None,
    "this_year": None,
}

_POS_KEYWORDS = {
    "名词": ("n", "名词"), "名": ("n", "名词"),
    "动词": ("v", "动词"), "动": ("v", "动词"),
    "形容词": ("a", "形容词"), "形": ("a", "形容词"),
    "副词": ("d", "副词"), "副": ("d", "副词"),
}

_COLORMAP_MAP = {
    "n": "pos_noun_colormap",
    "v": "pos_verb_colormap",
    "a": "pos_adj_colormap",
    "d": "pos_adv_colormap",
}


@dataclass
class ParsedArgs:
    time_kw: str = "today"
    period_name: str = "今日"
    pos_filter: Optional[str] = None
    pos_name: Optional[str] = None


def parse_time_kw(text: str) -> tuple:
    for word in text.split():
        if word in _TIME_KEYWORDS:
            return _TIME_KEYWORDS[word]
    return ("today", "今日")


def parse_pos_kw(text: str) -> tuple:
    for word in text.split():
        if word in _POS_KEYWORDS:
            return _POS_KEYWORDS[word]
    return (None, None)


def parse_common_args(text: str) -> ParsedArgs:
    time_kw, period_name = parse_time_kw(text)
    pos_filter, pos_name = parse_pos_kw(text)
    return ParsedArgs(
        time_kw=time_kw,
        period_name=period_name,
        pos_filter=pos_filter,
        pos_name=pos_name,
    )
