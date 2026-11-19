"""Per-user context for LLM calls (letters + personalized daily sentence).

Assembles everything the AI needs to stay tied to the user's own topic:
in-progress wishes, check-in streak, recent letters, the last 7 days of
daily sentences, and memory facts (importance first, then recency).

v1 memory sources (no free-text auto-extraction): wishes are recorded as
milestone memories at creation, 7-day check-in streaks as progress
memories, and the admin can add/delete memories per device.
"""
from datetime import date, timedelta

from . import database


def in_progress_wishes(device_id: str) -> list[dict]:
    """Wishes whose target date (created date + days) has not passed yet."""
    today = date.today()
    out = []
    for w in database.list_wishes(device_id):
        try:
            created = date.fromisoformat(str(w["created_at"])[:10])
        except ValueError:
            continue
        target = created + timedelta(days=w["days"])
        if target >= today:
            out.append({**w, "target_date": target.isoformat(),
                        "days_left": (target - today).days})
    return out


def build_user_context(device_id: str) -> str:
    """Render the user's context as a Chinese text block for an LLM prompt."""
    parts: list[str] = []

    wishes = in_progress_wishes(device_id)
    if wishes:
        lines = []
        for w in wishes:
            lines.append(
                f"- 愿望：{w['text']}（{w['category']}），目标 {w['days']} 天，"
                f"目标日 {w['target_date']}，还剩 {w['days_left']} 天"
            )
        parts.append("进行中的愿望：\n" + "\n".join(lines))
    else:
        parts.append("进行中的愿望：无")

    status = database.checkin_status(device_id)
    parts.append(
        f"打卡：连续 {status['streak_days']} 天，累计 {status['total_days']} 天，"
        f"今天{'已' if status['checked_in_today'] else '未'}打卡"
    )

    letters = database.list_letters(device_id)[:3]
    if letters:
        lines = [f"- {l['text'][:80]}" for l in letters]
        parts.append("最近的未来信（节选）：\n" + "\n".join(lines))

    recent_daily = database.list_daily_messages(device_id, limit=7)
    if recent_daily:
        lines = [f"- {d['date']}：{d['text']}" for d in reversed(recent_daily)]
        parts.append("最近 7 天的每日一句：\n" + "\n".join(lines))

    memories = database.list_memories(device_id)[:20]
    if memories:
        lines = [f"- [{m['kind']}] {m['text']}" for m in memories]
        parts.append("关于这个用户的记忆：\n" + "\n".join(lines))

    return "\n\n".join(parts)


def build_user_context_dict(device_id: str) -> dict:
    """Structured version of the same context (for tests / debugging)."""
    return {
        "wishes": in_progress_wishes(device_id),
        "checkin": database.checkin_status(device_id),
        "recent_letters": database.list_letters(device_id)[:3],
        "recent_daily": database.list_daily_messages(device_id, limit=7),
        "memories": database.list_memories(device_id)[:20],
    }
