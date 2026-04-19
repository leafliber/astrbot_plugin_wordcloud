import re
from collections import Counter
from dataclasses import dataclass
from typing import Optional

from .data_source import SegEngine, _pre_process, _CHINESE_PATTERN
from .config import Config


_POS_LABELS = {
    "n": "名词", "nr": "人名", "ns": "地名", "nt": "机构名", "nz": "其他专名",
    "v": "动词", "vd": "副动词", "vn": "名动词",
    "a": "形容词", "ad": "副形词", "an": "名形词",
    "d": "副词",
    "m": "数词", "q": "量词",
    "r": "代词", "p": "介词", "c": "连词", "u": "助词",
    "t": "时间词", "s": "处所词", "f": "方位词",
    "i": "成语", "l": "习语",
}


@dataclass
class POSDistribution:
    distribution: dict[str, float]
    language_type: str


def analyze_pos_distribution(
    messages: list,
    seg_engine: SegEngine,
    config: Config,
    group_key: Optional[str] = None,
) -> POSDistribution:
    pos_counter: Counter = Counter()
    total = 0
    min_len = config.min_word_length
    stopwords = seg_engine._stopwords

    for msg in messages:
        text = msg.message_str if hasattr(msg, "message_str") else str(msg)
        if not text:
            continue
        text = _pre_process(text)
        if not text:
            continue

        words_with_pos = seg_engine.cut(text, group_key)
        for word, pos in words_with_pos:
            if len(word) < min_len:
                continue
            if word in stopwords:
                continue
            if not _CHINESE_PATTERN.search(word) and len(word) < min_len:
                continue
            pos_counter[pos] += 1
            total += 1

    if total == 0:
        return POSDistribution(distribution={}, language_type="暂无数据")

    dist = {pos: count / total for pos, count in pos_counter.most_common()}
    lang_type = _determine_language_type(dist)
    return POSDistribution(distribution=dist, language_type=lang_type)


def _determine_language_type(dist: dict[str, float]) -> str:
    noun_pct = sum(v for k, v in dist.items() if k.startswith("n"))
    verb_pct = sum(v for k, v in dist.items() if k.startswith("v"))
    adj_pct = sum(v for k, v in dist.items() if k.startswith("a"))

    scores = {
        "信息分享型": noun_pct,
        "行动讨论型": verb_pct,
        "评价表达型": adj_pct,
    }
    best = max(scores, key=scores.get)
    if scores[best] < 0.25:
        return "综合交流型"
    return best


def format_pos_report(pos_dist: POSDistribution, period_name: str) -> str:
    if not pos_dist.distribution:
        return f"{period_name}暂无词性分析数据"

    lines = [f"📝 {period_name}词性分布分析", ""]

    for pos, pct in list(pos_dist.distribution.items())[:10]:
        label = _POS_LABELS.get(pos, pos)
        bar_len = int(pct * 30)
        bar = "█" * bar_len + "░" * (30 - bar_len)
        lines.append(f"  {label}({pos}): {bar} {pct:.1%}")

    lines.append("")
    lines.append(f"  🏷️ 群聊语言类型: {pos_dist.language_type}")

    return "\n".join(lines)
