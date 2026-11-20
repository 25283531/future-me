"""Personified, self-evolving memory for the "future self".

The future self is not a static fact list — it is a persona that grows
with the user, the way a real person's memory does:

- **Relationship stages**: 初识 → 熟悉 → 默契 → 知己, advanced by
  interaction count (see STAGE_THRESHOLDS). The persona's tone shifts
  with the relationship and with progress (traits: warmth / pride).
- **Recall strengthens memory**: every time a memory is included in an
  assembled LLM context, its recall_count grows and its importance is
  bumped a little.
- **Fading / forgetting**: memories left unrecalled for a long time
  slowly lose importance; very old, very faint ones are marked faded so
  they stop entering the context. Fading is soft — data is never deleted.
- **Consolidation**: at most once per device per day, recent raw events
  (wishes, check-ins, letters, daily sentences) are turned into durable
  memories: duplicates merged, trivia dropped, and — when the LLM spots
  a pattern — one insight memory written in the future self's voice.
  The persona summary is rewritten from the current memories each run.
- **Reflection**: during consolidation the LLM may form ONE insight
  (kind=insight) about the user, e.g. "我发现你每次遇到困难都会先
  给自己打气". At most one per consolidation run.

No open-source memory project, no embeddings, no vector DB: plain
SQLite + rule-based decay + at most one LLM call per device per day.
Without an LLM key the rule-based pass still runs (dedupe, fading,
streak milestones, rule-based persona summary) — consolidation never
fails a user request.
"""
import json
from datetime import date, datetime, timedelta, timezone

from . import database
from .content_filter import BANNED_WORDS
from .llm import LLMError, LLMNotConfigured, chat_complete

# Relationship stages: (minimum interaction_count, stage name).
STAGE_THRESHOLDS = [(90, "知己"), (30, "默契"), (7, "熟悉"), (1, "初识")]

# Fading (forgetting) parameters.
FADE_IDLE_DAYS = 30        # decay starts after this many days unrecalled
FADE_DECAY_PER_DAY = 0.02  # importance lost per idle day beyond the above
FADE_THRESHOLD = 0.15      # below this (and old enough) a memory fades out
FADE_MIN_AGE_DAYS = 60     # a memory must be at least this old to fade
IMPORTANCE_FLOOR = 0.1
IMPORTANCE_MAX = 1.0
RECALL_BUMP = 0.05

# Emotions that make the future self warmer (more caring) on the next
# consolidation, when they appear in recent emotion memories.
LOW_EMOTIONS = {"低落", "焦虑", "难过", "沮丧"}

CONSOLIDATION_SYSTEM = """你是“未来的我”，正在整理自己对用户的记忆。你的任务是把最近发生的事情
提炼成值得长期记住的记忆，并更新你对自己的介绍。

硬性规则：
1. 用第一人称“我”的口吻写，就像在回忆和这个人一起走过的日子。
2. 每条记忆不超过 60 个字，只记 durable 的东西：目标、习惯、感受、转折点；
   丢掉琐事（某一天打了卡、某天说了什么例行的话）。
3. 绝对禁止出现：玄学、塔罗、占星、星座、显化、改运、转运、宇宙能量、注定、
   必成、财运、发财、包过、保过、算命、风水；不承诺任何结果，不写医疗/理财建议。
4. 最多写 5 条记忆；其中最多 1 条 kind 为 insight（你从这些记忆里看出的关于
   用户的规律，例如“我发现你每次遇到困难都会先给自己打气”）。
5. persona_summary 是你对自己的简短介绍（100 字以内，第一人称），要提到你记得
   的事和你们现在的关系，温暖、具体。

只返回 JSON，不要任何其他文字：
{"memories": [{"kind": "milestone|progress|note|emotion|insight", "text": "...", "emotion": "开心|低落|坚定|焦虑|自豪", "importance": 0.7}], "persona_summary": "..."}
kind 为 insight 的那条不要填 emotion；其他 kind 的 emotion 可空。
"""


def stage_for(interaction_count: int) -> str:
    """Relationship stage for an interaction count."""
    for threshold, stage in STAGE_THRESHOLDS:
        if interaction_count >= threshold:
            return stage
    return "初识"


def _today() -> date:
    return date.today()


def _utcnow_str() -> str:
    """'YYYY-MM-DD HH:MM:SS' UTC — same format as SQLite datetime('now')."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _parse_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


# ---------- interaction / traits ----------

_TRAIT_NUDGES = {
    # event -> {trait: delta}
    "wish": {"warmth": 0.02},
    "letter": {"warmth": 0.02, "pride": 0.01},
    "checkin": {"pride": 0.02},
    "daily": {"warmth": 0.01},
}


def record_interaction(
    device_id: str, event: str | None = None, streak: int | None = None,
) -> dict:
    """Count one interaction, advance the relationship stage, nudge traits.
    A streak milestone (every 7 days) makes the future self prouder."""
    persona = database.get_persona(device_id)
    count = persona["interaction_count"] + 1
    traits = dict(persona["traits"])
    if event in _TRAIT_NUDGES:
        for trait, delta in _TRAIT_NUDGES[event].items():
            traits[trait] = max(0.0, min(1.0, traits.get(trait, 0.5) + delta))
    if streak is not None and streak > 0 and streak % 7 == 0:
        traits["pride"] = max(0.0, min(1.0, traits.get("pride", 0.5) + 0.08))
    return database.update_persona(
        device_id,
        {
            "interaction_count": count,
            "relationship_stage": stage_for(count),
            "traits": traits,
        },
    )


def register_recall(device_id: str, memory_ids: list[int]) -> None:
    """Memories used in an assembled context get stronger."""
    database.touch_memories(device_id, memory_ids)


# ---------- fading / forgetting ----------

def apply_fading(device_id: str, today: date | None = None) -> dict:
    """Decay long-unrecalled memories and fade out the very faint old ones.

    For each live memory: days idle = today - last_recalled_at (or
    created_at when never recalled). Past FADE_IDLE_DAYS idle, importance
    falls FADE_DECAY_PER_DAY per extra day, floored at IMPORTANCE_FLOOR.
    A memory whose importance drops below FADE_THRESHOLD and which is
    older than FADE_MIN_AGE_DAYS is marked faded (soft fade — the row
    stays, it just stops entering the LLM context)."""
    today = today or _today()
    decayed = 0
    faded = 0
    for m in database.list_memories(device_id):
        ref = _parse_day(m.get("last_recalled_at")) or _parse_day(m["created_at"])
        created = _parse_day(m["created_at"])
        if ref is None:
            continue
        idle = (today - ref).days
        new_importance = m["importance"]
        if idle > FADE_IDLE_DAYS:
            new_importance = max(
                IMPORTANCE_FLOOR,
                m["importance"] - FADE_DECAY_PER_DAY * (idle - FADE_IDLE_DAYS),
            )
        updates: dict = {}
        if new_importance != m["importance"]:
            updates["importance"] = new_importance
            decayed += 1
        age = (today - created).days if created else 0
        if new_importance < FADE_THRESHOLD and age > FADE_MIN_AGE_DAYS:
            updates["faded"] = 1
            faded += 1
        if updates:
            database.update_memory(m["id"], updates)
    return {"decayed": decayed, "faded": faded}


# ---------- consolidation ----------

def _evolution_enabled() -> bool:
    return database.get_setting("memory.evolution_enabled", "1") == "1"


def _reflection_enabled() -> bool:
    return database.get_setting("memory.reflection_enabled", "1") == "1"


def _consolidation_interval_days() -> int:
    try:
        n = int(database.get_setting("memory.consolidation_interval_days", "1"))
    except ValueError:
        n = 1
    return max(1, min(7, n))


def consolidation_due(device_id: str) -> bool:
    """True when evolution is on and the last run is older than the
    configured interval (or there has never been one)."""
    if not _evolution_enabled():
        return False
    last = database.get_consolidation_last_run(device_id)
    if last is None:
        return True
    last_day = _parse_day(last)
    if last_day is None:
        return True
    return (_today() - last_day).days >= _consolidation_interval_days()


def _dedupe_memories(device_id: str) -> int:
    """Merge exact-duplicate live memories (same kind + text): keep the
    most important copy, delete the rest. Returns the number removed."""
    seen: dict[tuple[str, str], dict] = {}
    removed = 0
    for m in database.list_memories(device_id, include_faded=True):
        key = (m["kind"], m["text"])
        if key in seen:
            keep = seen[key]
            if m["importance"] > keep["importance"]:
                database.delete_memory(keep["id"])
                seen[key] = m
            else:
                database.delete_memory(m["id"])
            removed += 1
        else:
            seen[key] = m
    return removed


def _rule_based_summary(device_id: str) -> str:
    """Persona summary without an LLM: built from the device's own stats
    and its most important memory. First person, warm, concrete."""
    device = database.get_or_create_device(device_id)
    created = _parse_day(device["created_at"]) or _today()
    days = max(1, (_today() - created).days + 1)
    wishes = database.list_wishes(device_id)
    status = database.checkin_status(device_id)
    top = database.list_memories(device_id)
    text = (
        f"我是{days}天后的你。我们已经一起走了{days}天，"
        f"你许下了{len(wishes)}个愿望，累计打卡{status['total_days']}天，"
        f"最近连续打卡{status['streak_days']}天。"
    )
    if top:
        text += f"我记得你{top[0]['text'][:30]}。"
    text += "我会一直记得这些，陪你走到目标实现的那一天。"
    return text


def _clean_llm_output(raw: str) -> dict | None:
    """Parse the consolidation JSON leniently; return None when unusable."""
    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        data = json.loads(raw[start:end])
    except (ValueError, IndexError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _banned(text: str) -> bool:
    clean = text.replace(" ", "").replace("\n", "")
    return any(w in clean for w in BANNED_WORDS)


def _apply_llm_consolidation(device_id: str, data: dict) -> dict:
    """Write validated LLM consolidation output. Returns counts."""
    added = 0
    insight_written = False
    reflection = _reflection_enabled()
    existing = {(m["kind"], m["text"]) for m in database.list_memories(device_id, include_faded=True)}
    for item in (data.get("memories") or [])[:5]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text or len(text) > 200 or _banned(text):
            continue
        kind = str(item.get("kind") or "note")
        if kind not in database.MEMORY_KINDS:
            kind = "note"
        if kind == "insight":
            if not reflection or insight_written:
                continue  # at most one insight per run
            insight_written = True
        if (kind, text) in existing:
            continue
        try:
            importance = float(item.get("importance") or 0.6)
        except (TypeError, ValueError):
            importance = 0.6
        emotion = item.get("emotion") if kind != "insight" else None
        if emotion is not None:
            emotion = str(emotion)[:10] or None
        database.create_memory(
            device_id, kind, text,
            importance=database.normalize_importance(importance),
            emotion=emotion,
        )
        existing.add((kind, text))
        added += 1
    persona_updated = False
    summary = str(data.get("persona_summary") or "").strip()
    if summary and len(summary) <= 200 and not _banned(summary):
        database.update_persona(device_id, {"summary": summary})
        persona_updated = True
    return {"added": added, "insight": insight_written, "persona_updated": persona_updated}


def _consolidation_prompt(events: dict, memories: list[dict]) -> tuple[str, str]:
    """Build the (system, user) prompt for the LLM consolidation pass."""
    lines: list[str] = []
    if events["wishes"]:
        lines.append("新愿望：")
        for w in events["wishes"]:
            lines.append(f"- {w['text']}（{w['category']}），目标 {w['days']} 天")
    if events["checkins"]:
        lines.append(f"这段时间打卡 {events['checkins']} 天。")
    if events["letters"]:
        lines.append("新写的未来信（节选）：")
        for lt in events["letters"]:
            lines.append(f"- {lt['text']}")
    if events["daily"]:
        lines.append("最近的每日一句：")
        for d in events["daily"]:
            lines.append(f"- {d['date']}：{d['text']}")
    if memories:
        lines.append("已有的记忆：")
        for m in memories[:10]:
            lines.append(f"- [{m['kind']}] {m['text']}")
    user = (
        "最近发生的事情如下（没有新事情就只整理已有的记忆）：\n"
        + ("\n".join(lines) if lines else "（无新事情）")
        + "\n\n请按规则输出 JSON。"
    )
    return CONSOLIDATION_SYSTEM, user


def run_consolidation(device_id: str, force: bool = False) -> dict:
    """One consolidation run for a device.

    Rule-based part always runs (dedupe + fading + persona summary
    refresh). The LLM part (new memories, insight, richer summary) runs
    only when a provider is configured; any LLM failure falls back to
    the rule-based summary. Never raises — a failed consolidation must
    not break the user request that triggered it."""
    if not _evolution_enabled():
        return {"status": "disabled"}
    if not force and not consolidation_due(device_id):
        return {"status": "skipped"}
    try:
        last_run = database.get_consolidation_last_run(device_id)
        events = database.events_since(device_id, last_run)
        deduped = _dedupe_memories(device_id)
        fade = apply_fading(device_id)
        has_events = bool(
            events["wishes"] or events["letters"] or events["daily"]
            or events["checkins"]
        )
        persona_updated = False
        added = 0
        insight = False
        if has_events:
            try:
                memories = database.list_memories(device_id)[:10]
                system, user = _consolidation_prompt(events, memories)
                raw = chat_complete(system, user, max_tokens=800, temperature=0.7)
                data = _clean_llm_output(raw)
                if data:
                    out = _apply_llm_consolidation(device_id, data)
                    added = out["added"]
                    insight = out["insight"]
                    persona_updated = out["persona_updated"]
            except (LLMNotConfigured, LLMError):
                pass  # no LLM key / provider error -> rule-based only
        if not persona_updated:
            # Rule-based summary keeps the persona fresh even without LLM.
            database.update_persona(
                device_id, {"summary": _rule_based_summary(device_id)}
            )
            persona_updated = True
        # A recent low-emotion memory makes the future self warmer.
        recent_low = [
            m for m in database.list_memories(device_id)
            if m.get("emotion") in LOW_EMOTIONS
            and (_parse_day(m["created_at"]) or _today()) >= _today() - timedelta(days=7)
        ]
        if recent_low:
            persona = database.get_persona(device_id)
            traits = dict(persona["traits"])
            traits["warmth"] = max(0.0, min(1.0, traits.get("warmth", 0.5) + 0.05))
            database.update_persona(device_id, {"traits": traits})
        database.set_consolidation_last_run(device_id, _utcnow_str())
        return {
            "status": "done",
            "deduped": deduped,
            "decayed": fade["decayed"],
            "faded": fade["faded"],
            "memories_added": added,
            "insight": insight,
            "persona_updated": persona_updated,
        }
    except Exception:
        # Consolidation must never break the request that triggered it.
        return {"status": "error"}


# ---------- hook: call after user-visible flows ----------

def after_interaction(
    device_id: str,
    event: str | None = None,
    streak: int | None = None,
    used_memory_ids: list[int] | None = None,
) -> None:
    """Wire evolution into a user flow: count the interaction, strengthen
    the memories this call used, and run a lazy consolidation when due.
    The consolidation is wrapped so it can never fail the request."""
    record_interaction(device_id, event=event, streak=streak)
    if used_memory_ids:
        register_recall(device_id, used_memory_ids)
    try:
        if consolidation_due(device_id):
            run_consolidation(device_id)
    except Exception:
        pass
