from collections import Counter
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TrendResult:
    emerging: list[tuple[str, int, float]] = field(default_factory=list)
    declining: list[tuple[str, int, float]] = field(default_factory=list)
    stable: list[tuple[str, int, float]] = field(default_factory=list)


def compute_trend(
    freq_current: Counter,
    freq_previous: Counter,
    threshold: float = 0.5,
    emerging_limit: int = 10,
    declining_limit: int = 5,
) -> TrendResult:
    emerging = []
    declining = []
    stable = []

    all_words = set(freq_current.keys()) | set(freq_previous.keys())

    for word in all_words:
        curr = freq_current.get(word, 0)
        prev = freq_previous.get(word, 0)

        if prev == 0 and curr > 0:
            emerging.append((word, curr, float("inf")))
        elif curr == 0 and prev > 0:
            declining.append((word, prev, -1.0))
        else:
            growth = (curr - prev) / prev
            if growth > threshold:
                emerging.append((word, curr, growth))
            elif growth < -threshold:
                declining.append((word, curr, growth))
            else:
                stable.append((word, curr, growth))

    return TrendResult(
        emerging=sorted(emerging, key=lambda x: x[1], reverse=True)[:emerging_limit],
        declining=sorted(declining, key=lambda x: abs(x[2]), reverse=True)[:declining_limit],
        stable=sorted(stable, key=lambda x: x[1], reverse=True)[:5],
    )


def _growth_arrow(growth: float) -> str:
    if growth == float("inf"):
        return "🆕"
    if growth == -1.0:
        return "💀"
    if growth > 1.0:
        return "↑↑↑"
    if growth > 0.5:
        return "↑↑"
    if growth > 0:
        return "↑"
    if growth < -1.0:
        return "↓↓↓"
    if growth < -0.5:
        return "↓↓"
    if growth < 0:
        return "↓"
    return "→"


def format_trend_report(
    trend: TrendResult,
    period_current: str,
    period_previous: str,
) -> str:
    if not trend.emerging and not trend.declining and not trend.stable:
        return "暂无足够数据生成热词趋势"

    lines = [f"🔥 热词趋势: {period_current} vs {period_previous}", ""]

    if trend.emerging:
        lines.append("  📈 新兴热词:")
        for word, count, growth in trend.emerging:
            arrow = _growth_arrow(growth)
            if growth == float("inf"):
                lines.append(f"    {arrow} {word} — {count} 次 (新词)")
            else:
                lines.append(f"    {arrow} {word} — {count} 次 (+{growth:.0%})")
        lines.append("")

    if trend.declining:
        lines.append("  📉 衰退话题:")
        for word, count, growth in trend.declining:
            arrow = _growth_arrow(growth)
            if growth == -1.0:
                lines.append(f"    {arrow} {word} — 已消失")
            else:
                lines.append(f"    {arrow} {word} — {count} 次 ({growth:.0%})")
        lines.append("")

    if trend.stable:
        lines.append("  ➡️ 持续热门:")
        for word, count, growth in trend.stable:
            lines.append(f"    → {word} — {count} 次 ({growth:+.0%})")

    return "\n".join(lines)
