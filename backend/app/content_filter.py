"""Output filter for AI-generated future letters.

Rules (must match the system prompt in llm.py):
- First-person future-self voice, past tense, as if the wish already came true.
- 150-200 Chinese characters.
- Must reference the wish text and the day count.
- NEVER: 玄学/塔罗/占星/显化/改运/转运/宇宙能量/注定/必成/财运/
  考试包过 promises, or any medical / financial / exam-outcome guarantee.

`validate_letter` returns (ok, problems). The generate endpoint retries once
with a correction prompt, then fails with 502 if the text is still invalid.
"""
import re

BANNED_WORDS = [
    "玄学", "塔罗", "占星", "星座", "显化", "改运", "转运", "宇宙能量",
    "注定", "必成", "财运", "发财", "包过", "保过", "必过", "命中注定",
    "改命", "算命", "风水", "开光", "锦鲤", "许愿成真", "心想事成",
    "保证治愈", "保证通过", "一定能考上", "保证考上",
]

# Phrases that amount to an outcome guarantee (checked as substrings).
BANNED_PHRASES = [
    "一定能", "保证你", "肯定能", "包你", "必定会",
]

# Violation types for the admin compliance overview. The backend only ever
# stores and shows TYPE + COUNT per day — never the offending text, never
# the device/user it came from (privacy red line).
VIOLATION_TYPES: dict[str, list[str]] = {
    "玄学占卜": [
        "玄学", "塔罗", "占星", "星座", "显化", "改运", "转运", "宇宙能量",
        "注定", "必成", "改命", "命中注定", "算命", "风水", "开光", "锦鲤",
        "许愿成真", "心想事成",
    ],
    "医疗承诺": ["保证治愈"],
    "结果保证": [
        "包过", "保过", "必过", "保证通过", "一定能考上", "保证考上",
        "一定能", "保证你", "肯定能", "包你", "必定会",
    ],
    "财运": ["财运", "发财"],
}


def classify_violation(text: str) -> list[str]:
    """Return the violation types present in `text` (each at most once).

    Used only for aggregate counting — the text itself is never stored
    with the result and never shown in the admin console.
    """
    clean = _clean(text)
    return [t for t, words in VIOLATION_TYPES.items() if any(w in clean for w in words)]

MIN_CHARS = 150
MAX_CHARS = 200

# Day counts may be written as Arabic or Chinese numerals ("90天" or "九十天").
DAY_FORMS: dict[int, list[str]] = {
    30: ["30", "三十"],
    90: ["90", "九十"],
    365: ["365", "三百六十五"],
}


def _clean(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _wish_keywords(wish_text: str) -> list[str]:
    """2-char chunks of the wish, minus common particles, for the reference check."""
    stop = set("的了是我在和与你我他她它吗呢啊吧着过也都就把被对为")
    clean = _clean(wish_text)
    return [clean[i : i + 2] for i in range(len(clean) - 1) if clean[i] not in stop]


def validate_letter(text: str, wish_text: str, days: int) -> tuple[bool, list[str]]:
    problems: list[str] = []
    clean = _clean(text)

    if not (MIN_CHARS <= len(clean) <= MAX_CHARS):
        problems.append(f"length {len(clean)} chars, must be {MIN_CHARS}-{MAX_CHARS}")

    for w in BANNED_WORDS + BANNED_PHRASES:
        if w in clean:
            problems.append(f"contains banned word/phrase: {w}")

    if "我" not in clean:
        problems.append("not written in first person (no 我)")

    if not any(form in clean for form in DAY_FORMS.get(days, [str(days)])):
        problems.append(f"does not reference the {days}-day goal")

    keywords = _wish_keywords(wish_text)
    if keywords and not any(k in clean for k in keywords):
        problems.append("does not reference the wish content")

    return (not problems, problems)
