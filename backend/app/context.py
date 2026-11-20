"""Per-user context for LLM calls (letters + personalized daily sentence).

Assembles everything the AI needs to stay tied to the user's own topic:
who the future self is right now (persona summary + relationship stage),
in-progress wishes, check-in streak, recent letters, the last 7 days of
daily sentences, and memory facts (evolved importance first, then
recency) plus the latest insight.

The persona is personified and self-evolving (see evolution.py): the
relationship deepens with interactions, memories strengthen when
recalled and fade when forgotten, and a daily consolidation rewrites
the persona summary. Building the context also registers the recall:
every memory included here gets recall_count + 1 and a small
importance bump.
"""
from datetime import date, timedelta

from . import database
from . import evolution


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

    # Who the future self is right now — persona first, so the LLM speaks
    # as that person, not as a generic encourager.
    persona = database.get_persona(device_id)
    summary = persona["summary"] or (
        "我是来自未来的你。我们才刚刚认识，我正在慢慢了解你的目标和日常。"
    )
    traits = persona["traits"]
    parts.append(
        f"【未来的我】{summary}\n"
        f"我们现在的关系：{persona['relationship_stage']}（已经互动"
        f" {persona['interaction_count']} 次）。"
        f"我的状态：温暖 {traits.get('warmth', 0.5):.1f}，"
        f"自豪 {traits.get('pride', 0.5):.1f}。"
        "请以这个身份和你对用户的了解说话。"
    )

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

    # Live memories only (faded ones are excluded by list_memories).
    # Every memory included here is recalled — strengthen it.
    memories = database.list_memories(device_id)[:20]
    if memories:
        lines = []
        for m in memories:
            extra = f"（{m['emotion']}）" if m.get("emotion") else ""
            lines.append(f"- [{m['kind']}]{extra} {m['text']}")
        parts.append("关于这个用户的记忆：\n" + "\n".join(lines))
        evolution.register_recall(device_id, [m["id"] for m in memories])

    # The latest insight gets its own line — it is the future self's
    # current understanding of the user.
    insights = [m for m in memories if m["kind"] == "insight"]
    if insights:
        parts.append(f"【我对你的最新感悟】{insights[0]['text']}")

    return "\n\n".join(parts)


def build_user_context_dict(device_id: str) -> dict:
    """Structured version of the same context (for tests / debugging)."""
    persona = database.get_persona(device_id)
    memories = database.list_memories(device_id)[:20]
    return {
        "persona": {
            "stage": persona["relationship_stage"],
            "summary": persona["summary"],
            "traits": persona["traits"],
            "interaction_count": persona["interaction_count"],
        },
        "wishes": in_progress_wishes(device_id),
        "checkin": database.checkin_status(device_id),
        "recent_letters": database.list_letters(device_id)[:3],
        "recent_daily": database.list_daily_messages(device_id, limit=7),
        "memories": memories,
        "insight": next(
            (m for m in memories if m["kind"] == "insight"), None
        ),
    }
