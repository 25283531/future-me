"""Personalized daily sentence: one AI-generated sentence per user per day,
from the 'future self' after the goal is achieved, tied to that user's own
wish and context.

Flow for GET /daily-sentence (device-authenticated):
1. Already generated today -> return the cached sentence (never regenerate).
2. Generation disabled in admin settings, or no in-progress wish, or no LLM
   provider configured, or the LLM call fails -> fallback (built-in generic
   encouragement from catalog.py, or the most recent daily sentence when
   fallback_mode is 'previous').
3. Otherwise generate with the default LLM provider, store it in
   daily_messages, return it. The next day's generation can build on it
   (context includes the last 7 days of daily sentences).

The built-in generic sentences are fallback only — they are hardcoded in
code and never admin-managed.
"""
from datetime import date

from . import database
from .catalog import daily_sentence as fallback_sentence
from .context import build_user_context, in_progress_wishes
from .llm import LLMError, LLMNotConfigured, generate_daily_sentence


def _fallback(device_id: str, today: str) -> dict:
    mode = database.get_setting("daily.fallback_mode", "generic")
    if mode == "previous":
        recent = database.list_daily_messages(device_id, limit=1)
        if recent:
            row = recent[0]
            return {
                "date": today,
                "sentence": row["text"],
                "text": row["text"],
                "index": None,
                "personalized": False,
                "cached": True,
                "wish_id": row["wish_id"],
                "fallback": "previous",
            }
    fb = fallback_sentence()
    return {
        "date": today,
        "sentence": fb["sentence"],
        "text": fb["sentence"],
        "index": fb["index"],
        "personalized": False,
        "cached": False,
        "wish_id": None,
        "fallback": "generic",
    }


def get_daily_sentence_for_device(device_id: str) -> dict:
    today = date.today().isoformat()

    # 1. Same-day cache: never generate twice.
    cached = database.get_daily_message(device_id, today)
    if cached:
        return {
            "date": today,
            "sentence": cached["text"],
            "text": cached["text"],
            "index": None,
            "personalized": True,
            "cached": True,
            "wish_id": cached["wish_id"],
        }

    # 2. Generation disabled, or nothing to personalize with -> fallback.
    if database.get_setting("daily.enabled", "1") != "1":
        return _fallback(device_id, today)
    wishes = in_progress_wishes(device_id)
    if not wishes:
        return _fallback(device_id, today)

    # 3. Generate with the LLM (default / first configured provider).
    wish = wishes[-1]  # most recently created in-progress wish
    try:
        max_chars = int(database.get_setting("daily.max_chars", "60"))
    except ValueError:
        max_chars = 60
    max_chars = max(10, min(max_chars, 200))
    template = database.get_setting("daily.prompt_template", "")
    try:
        text = generate_daily_sentence(
            context_text=build_user_context(device_id),
            wish_text=wish["text"],
            days_left=wish["days_left"],
            max_chars=max_chars,
            template=template,
        )
    except (LLMNotConfigured, LLMError):
        return _fallback(device_id, today)

    row = database.create_daily_message(device_id, wish["id"], today, text)
    return {
        "date": today,
        "sentence": row["text"],
        "text": row["text"],
        "index": None,
        "personalized": True,
        "cached": False,
        "wish_id": wish["id"],
    }
