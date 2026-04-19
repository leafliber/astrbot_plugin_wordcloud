from collections import Counter
from dataclasses import dataclass
from typing import Optional


@dataclass
class RankingEntry:
    sender_id: str
    sender_name: Optional[str]
    count: int
    percentage: float


def compute_ranking(
    messages: list,
    limit: int = 10,
    show_percentage: bool = True,
) -> list[RankingEntry]:
    counter: Counter = Counter()
    name_map: dict[str, str] = {}

    for msg in messages:
        sender_id = msg.sender_id if hasattr(msg, "sender_id") else ""
        sender_name = msg.sender_name if hasattr(msg, "sender_name") else None
        if not sender_id:
            continue
        counter[sender_id] += 1
        if sender_name:
            name_map[sender_id] = sender_name

    total = sum(counter.values())
    ranking = []

    for sender_id, count in counter.most_common(limit):
        pct = (count / total * 100) if total > 0 and show_percentage else 0.0
        ranking.append(RankingEntry(
            sender_id=sender_id,
            sender_name=name_map.get(sender_id),
            count=count,
            percentage=round(pct, 1),
        ))

    return ranking


def format_ranking(ranking: list[RankingEntry], period_name: str) -> str:
    if not ranking:
        return f"{period_name}暂无发言记录"

    lines = [f"📊 {period_name}发言排名"]
    for i, entry in enumerate(ranking, 1):
        name = entry.sender_name or entry.sender_id
        if entry.percentage > 0:
            lines.append(f"  {i}. {name} — {entry.count} 条 ({entry.percentage}%)")
        else:
            lines.append(f"  {i}. {name} — {entry.count} 条")

    return "\n".join(lines)
