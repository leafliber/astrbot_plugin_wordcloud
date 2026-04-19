import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .data_source import SegEngine, _pre_process, _CHINESE_PATTERN
from .config import Config


@dataclass
class GroupProfile:
    group_name: str
    period: str
    total_messages: int
    active_members: int
    avg_message_length: float
    vocabulary_richness: float
    top_words: list[tuple[str, int]]
    pos_distribution: dict[str, float]
    language_type: str
    peak_hour: int


@dataclass
class PersonalStyle:
    sender_name: str
    period: str
    message_count: int
    avg_message_length: float
    vocabulary_richness: float
    pos_preference: dict[str, float]
    top_words: list[tuple[str, int]]
    style_tags: list[str]


def build_group_profile(
    messages: list,
    seg_engine: SegEngine,
    config: Config,
    group_key: Optional[str] = None,
    period_name: str = "",
) -> Optional[GroupProfile]:
    if not messages:
        return None

    total = len(messages)
    senders: set[str] = set()
    lengths: list[int] = []
    hour_counter: Counter = Counter()
    word_counter: Counter = Counter()
    pos_counter: Counter = Counter()
    total_words = 0
    unique_words: set[str] = set()
    min_len = config.min_word_length
    stopwords = seg_engine._stopwords

    for msg in messages:
        sender_id = msg.sender_id if hasattr(msg, "sender_id") else ""
        if sender_id:
            senders.add(sender_id)

        text = msg.message_str if hasattr(msg, "message_str") else str(msg)
        if not text:
            continue
        lengths.append(len(text))

        ts = msg.timestamp if hasattr(msg, "timestamp") else 0
        if ts:
            try:
                if ts > 1e12:
                    ts = ts / 1000
                dt = datetime.fromtimestamp(ts)
                hour_counter[dt.hour] += 1
            except (OSError, ValueError):
                pass

        text = _pre_process(text)
        if not text:
            continue

        words_with_pos = seg_engine.cut(text, group_key)
        for word, pos in words_with_pos:
            if len(word) < min_len or word in stopwords:
                continue
            if not _CHINESE_PATTERN.search(word) and len(word) < min_len:
                continue
            word_counter[word] += 1
            pos_counter[pos] += 1
            unique_words.add(word)
            total_words += 1

    avg_len = sum(lengths) / len(lengths) if lengths else 0
    richness = len(unique_words) / total_words if total_words > 0 else 0

    total_pos = sum(pos_counter.values())
    pos_dist = {pos: count / total_pos for pos, count in pos_counter.most_common()} if total_pos > 0 else {}

    noun_pct = sum(v for k, v in pos_dist.items() if k.startswith("n"))
    verb_pct = sum(v for k, v in pos_dist.items() if k.startswith("v"))
    adj_pct = sum(v for k, v in pos_dist.items() if k.startswith("a"))

    scores = {"信息分享型": noun_pct, "行动讨论型": verb_pct, "评价表达型": adj_pct}
    best = max(scores, key=scores.get)
    lang_type = best if scores[best] >= 0.25 else "综合交流型"

    peak_hour = hour_counter.most_common(1)[0][0] if hour_counter else 0
    top_words = word_counter.most_common(config.profile_top_words)

    return GroupProfile(
        group_name="",
        period=period_name,
        total_messages=total,
        active_members=len(senders),
        avg_message_length=round(avg_len, 1),
        vocabulary_richness=round(richness, 3),
        top_words=top_words,
        pos_distribution=pos_dist,
        language_type=lang_type,
        peak_hour=peak_hour,
    )


def build_personal_style(
    messages: list,
    sender_id: str,
    seg_engine: SegEngine,
    config: Config,
    group_key: Optional[str] = None,
    period_name: str = "",
) -> Optional[PersonalStyle]:
    filtered = []
    sender_name = None
    for msg in messages:
        sid = msg.sender_id if hasattr(msg, "sender_id") else ""
        if sid == sender_id:
            filtered.append(msg)
            sn = msg.sender_name if hasattr(msg, "sender_name") else None
            if sn:
                sender_name = sn

    if not filtered:
        return None

    lengths: list[int] = []
    word_counter: Counter = Counter()
    pos_counter: Counter = Counter()
    total_words = 0
    unique_words: set[str] = set()
    min_len = config.min_word_length
    stopwords = seg_engine._stopwords

    for msg in filtered:
        text = msg.message_str if hasattr(msg, "message_str") else str(msg)
        if not text:
            continue
        lengths.append(len(text))
        text = _pre_process(text)
        if not text:
            continue

        words_with_pos = seg_engine.cut(text, group_key)
        for word, pos in words_with_pos:
            if len(word) < min_len or word in stopwords:
                continue
            if not _CHINESE_PATTERN.search(word) and len(word) < min_len:
                continue
            word_counter[word] += 1
            pos_counter[pos] += 1
            unique_words.add(word)
            total_words += 1

    avg_len = sum(lengths) / len(lengths) if lengths else 0
    richness = len(unique_words) / total_words if total_words > 0 else 0

    total_pos = sum(pos_counter.values())
    pos_pref = {pos: count / total_pos for pos, count in pos_counter.most_common()} if total_pos > 0 else {}

    style_tags = _determine_style_tags(pos_pref, richness, avg_len, config)
    top_words = word_counter.most_common(5)

    return PersonalStyle(
        sender_name=sender_name or sender_id,
        period=period_name,
        message_count=len(filtered),
        avg_message_length=round(avg_len, 1),
        vocabulary_richness=round(richness, 3),
        pos_preference=pos_pref,
        top_words=top_words,
        style_tags=style_tags,
    )


def _determine_style_tags(
    pos_pref: dict[str, float],
    richness: float,
    avg_len: float,
    config: Config,
) -> list[str]:
    tags = []

    adj_pct = sum(v for k, v in pos_pref.items() if k.startswith("a"))
    verb_pct = sum(v for k, v in pos_pref.items() if k.startswith("v"))
    noun_pct = sum(v for k, v in pos_pref.items() if k.startswith("n"))

    if adj_pct > config.style_adj_threshold:
        tags.append("感性表达者")
    if verb_pct > config.style_verb_threshold:
        tags.append("行动派")
    if noun_pct > config.style_noun_threshold:
        tags.append("知识分享者")
    if richness > 0.6:
        tags.append("词汇大师")
    if avg_len > 30:
        tags.append("长文输出者")
    elif avg_len < 8:
        tags.append("简洁达人")

    if not tags:
        tags.append("均衡型")

    return tags


def format_group_profile(profile: GroupProfile) -> str:
    lines = [
        f"🎨 群聊语言画像 — {profile.period}",
        "",
        f"  📨 消息总量: {profile.total_messages}",
        f"  👥 活跃成员: {profile.active_members}",
        f"  📏 平均消息长度: {profile.avg_message_length} 字",
        f"  📚 词汇丰富度: {profile.vocabulary_richness:.1%}",
        f"  🏷️ 语言类型: {profile.language_type}",
        f"  ⏰ 最活跃时段: {profile.peak_hour}:00",
    ]

    if profile.top_words:
        lines.append("  🔤 高频词:")
        for word, count in profile.top_words:
            lines.append(f"    • {word} ({count} 次)")

    return "\n".join(lines)


def format_personal_style(style: PersonalStyle) -> str:
    lines = [
        f"👤 个人语言风格 — {style.sender_name} ({style.period})",
        "",
        f"  📨 发言数: {style.message_count}",
        f"  📏 平均消息长度: {style.avg_message_length} 字",
        f"  📚 词汇丰富度: {style.vocabulary_richness:.1%}",
        f"  🏷️ 风格标签: {' | '.join(style.style_tags)}",
    ]

    if style.top_words:
        lines.append("  🔤 个人高频词:")
        for word, count in style.top_words:
            lines.append(f"    • {word} ({count} 次)")

    return "\n".join(lines)
