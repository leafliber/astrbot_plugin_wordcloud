from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .data_source import SegEngine, _pre_process, _CHINESE_PATTERN
from .config import Config


@dataclass
class UserStats:
    sender_id: str
    sender_name: str
    message_count: int
    avg_message_length: float
    vocabulary_richness: float
    pos_preference: dict[str, float]
    top_words: list[tuple[str, int]]
    style_tags: list[str]
    hour_distribution: dict[int, int]
    peak_hours: list[int]
    unique_words: set[str]


@dataclass
class CompareResult:
    user1: UserStats
    user2: UserStats
    period: str
    similarity_score: float
    common_words: list[tuple[str, int, int]]
    unique_words_1: list[tuple[str, int]]
    unique_words_2: list[tuple[str, int]]
    pos_comparison: dict[str, tuple[float, float]]
    style_similarity: list[str]
    style_difference: list[str]


def build_user_stats(
    messages: list,
    sender_id: str,
    seg_engine: SegEngine,
    config: Config,
    group_key: Optional[str] = None,
) -> Optional[UserStats]:
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
    hour_counter: Counter = Counter()
    total_words = 0
    unique_words: set[str] = set()
    min_len = config.min_word_length
    stopwords = seg_engine._stopwords

    for msg in filtered:
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
    pos_pref = {pos: count / total_pos for pos, count in pos_counter.most_common()} if total_pos > 0 else {}

    style_tags = _determine_style_tags(pos_pref, richness, avg_len, config)
    top_words = word_counter.most_common(10)

    peak_hours = []
    if hour_counter:
        max_count = max(hour_counter.values())
        peak_hours = sorted([h for h, c in hour_counter.items() if c >= max_count * 0.8])

    return UserStats(
        sender_id=sender_id,
        sender_name=sender_name or sender_id,
        message_count=len(filtered),
        avg_message_length=round(avg_len, 1),
        vocabulary_richness=round(richness, 3),
        pos_preference=pos_pref,
        top_words=top_words,
        style_tags=style_tags,
        hour_distribution=dict(hour_counter),
        peak_hours=peak_hours,
        unique_words=unique_words,
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


def compare_users(
    messages: list,
    sender_id_1: str,
    sender_id_2: str,
    seg_engine: SegEngine,
    config: Config,
    group_key: Optional[str] = None,
    period_name: str = "",
) -> Optional[CompareResult]:
    user1_stats = build_user_stats(messages, sender_id_1, seg_engine, config, group_key)
    user2_stats = build_user_stats(messages, sender_id_2, seg_engine, config, group_key)

    if user1_stats is None or user2_stats is None:
        return None

    common_words_set = user1_stats.unique_words & user2_stats.unique_words
    common_words = []
    for word in common_words_set:
        count1 = next((c for w, c in user1_stats.top_words if w == word), 0)
        count2 = next((c for w, c in user2_stats.top_words if w == word), 0)
        if count1 > 0 or count2 > 0:
            common_words.append((word, count1, count2))
    common_words.sort(key=lambda x: x[1] + x[2], reverse=True)
    common_words = common_words[:10]

    unique_words_1 = [
        (w, c) for w, c in user1_stats.top_words
        if w not in user2_stats.unique_words
    ][:5]
    unique_words_2 = [
        (w, c) for w, c in user2_stats.top_words
        if w not in user1_stats.unique_words
    ][:5]

    pos_comparison = {}
    for pos in set(user1_stats.pos_preference.keys()) | set(user2_stats.pos_preference.keys()):
        p1 = user1_stats.pos_preference.get(pos, 0)
        p2 = user2_stats.pos_preference.get(pos, 0)
        if p1 > 0.02 or p2 > 0.02:
            pos_comparison[pos] = (round(p1, 3), round(p2, 3))

    style_similarity = list(set(user1_stats.style_tags) & set(user2_stats.style_tags))
    style_difference = list(
        (set(user1_stats.style_tags) - set(user2_stats.style_tags)) |
        (set(user2_stats.style_tags) - set(user1_stats.style_tags))
    )

    similarity_score = _calculate_similarity(user1_stats, user2_stats)

    return CompareResult(
        user1=user1_stats,
        user2=user2_stats,
        period=period_name,
        similarity_score=similarity_score,
        common_words=common_words,
        unique_words_1=unique_words_1,
        unique_words_2=unique_words_2,
        pos_comparison=pos_comparison,
        style_similarity=style_similarity,
        style_difference=style_difference,
    )


def _calculate_similarity(user1: UserStats, user2: UserStats) -> float:
    scores = []

    if user1.style_tags and user2.style_tags:
        common_tags = len(set(user1.style_tags) & set(user2.style_tags))
        total_tags = len(set(user1.style_tags) | set(user2.style_tags))
        style_sim = common_tags / total_tags if total_tags > 0 else 0
        scores.append(style_sim * 0.3)

    common_pos = set(user1.pos_preference.keys()) & set(user2.pos_preference.keys())
    if common_pos:
        pos_sim = sum(
            1 - abs(user1.pos_preference.get(p, 0) - user2.pos_preference.get(p, 0))
            for p in common_pos
        ) / len(common_pos)
        scores.append(pos_sim * 0.3)

    common_words = user1.unique_words & user2.unique_words
    total_words = user1.unique_words | user2.unique_words
    if total_words:
        word_sim = len(common_words) / len(total_words)
        scores.append(word_sim * 0.4)

    return round(sum(scores) * 100, 1)


def format_compare_result(result: CompareResult) -> str:
    n1 = result.user1.sender_name[:6]
    n2 = result.user2.sender_name[:6]
    lines = [
        f"📊 {result.period} 对比分析",
        "",
        f"👤 {result.user1.sender_name} ⚔️ {result.user2.sender_name}",
        f"🎯 相似度: {result.similarity_score}%",
        "",
        "📋 基础数据",
        f"  发言数: {result.user1.message_count} vs {result.user2.message_count}",
        f"  平均长度: {result.user1.avg_message_length}字 vs {result.user2.avg_message_length}字",
        f"  词汇丰富度: {result.user1.vocabulary_richness:.0%} vs {result.user2.vocabulary_richness:.0%}",
    ]

    if result.user1.peak_hours or result.user2.peak_hours:
        peak1 = "、".join(f"{h}点" for h in result.user1.peak_hours[:3]) if result.user1.peak_hours else "暂无"
        peak2 = "、".join(f"{h}点" for h in result.user2.peak_hours[:3]) if result.user2.peak_hours else "暂无"
        lines.append(f"  活跃时段: {peak1} vs {peak2}")

    tags1 = " ".join(result.user1.style_tags) if result.user1.style_tags else "均衡型"
    tags2 = " ".join(result.user2.style_tags) if result.user2.style_tags else "均衡型"
    lines.extend([
        "",
        "🏷️ 风格标签",
        f"  {n1}: {tags1}",
        f"  {n2}: {tags2}",
    ])

    if result.style_similarity:
        lines.append(f"  🤝 共同: {' '.join(result.style_similarity)}")
    if result.style_difference:
        lines.append(f"  ⚡ 差异: {' '.join(result.style_difference)}")

    if result.pos_comparison:
        lines.extend(["", "📝 词性对比"])
        pos_labels = {"n": "名词", "v": "动词", "a": "形容词", "d": "副词"}
        for pos in ["n", "v", "a", "d"]:
            if pos in result.pos_comparison:
                p1, p2 = result.pos_comparison[pos]
                label = pos_labels.get(pos, pos)
                bar_len = 10
                b1 = "▓" * int(p1 * bar_len) + "░" * (bar_len - int(p1 * bar_len))
                b2 = "▓" * int(p2 * bar_len) + "░" * (bar_len - int(p2 * bar_len))
                lines.append(f"  {label}")
                lines.append(f"    {n1} {b1} {p1:.0%}")
                lines.append(f"    {n2} {b2} {p2:.0%}")

    if result.common_words:
        lines.extend(["", "🔤 共同高频词"])
        for word, c1, c2 in result.common_words[:5]:
            lines.append(f"  {word}: {c1} vs {c2}")

    if result.unique_words_1 or result.unique_words_2:
        lines.extend(["", "💎 独特词汇"])
        if result.unique_words_1:
            words1 = " ".join(f"{w}({c})" for w, c in result.unique_words_1)
            lines.append(f"  {n1}: {words1}")
        if result.unique_words_2:
            words2 = " ".join(f"{w}({c})" for w, c in result.unique_words_2)
            lines.append(f"  {n2}: {words2}")

    return "\n".join(lines)
