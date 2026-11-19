"""Static catalogs: voices and the daily positive-psychology sentences.

Voice lists are taken from the providers' public docs (checked 2026-11-19):
- Qwen3-TTS-Flash: DashScope documented system voices (24 core voices).
  Chinese names where documented: Cherry 芊悦, Serena 苏瑶, Ethan 晨煦,
  Chelsie 千雪, Vivian 十三.
- GLM-TTS: Zhipu docs — 7 system voices.
- Tencent: premium VoiceType codes 101001-101006 (云小宁/云小奇/云小晚/云小叶/
  云小龙/云小曼). Verify VoiceType IDs in the Tencent console before production.
- Edge TTS: Microsoft neural voices, no key needed (unofficial endpoint).

`provider_voice` is the exact value sent to that provider's API.
"""
from datetime import date

VOICES: list[dict] = [
    # ---- Qwen3-TTS-Flash (DashScope, primary, premium) ----
    {"id": "qwen-cherry", "name": "芊悦", "gender": "female", "style": "阳光积极、亲切自然", "provider": "qwen", "tier": "premium", "provider_voice": "Cherry"},
    {"id": "qwen-serena", "name": "苏瑶", "gender": "female", "style": "温柔", "provider": "qwen", "tier": "premium", "provider_voice": "Serena"},
    {"id": "qwen-ethan", "name": "晨煦", "gender": "male", "style": "阳光、温暖、活力、朝气", "provider": "qwen", "tier": "premium", "provider_voice": "Ethan"},
    {"id": "qwen-chelsie", "name": "千雪", "gender": "female", "style": "二次元虚拟女友", "provider": "qwen", "tier": "premium", "provider_voice": "Chelsie"},
    {"id": "qwen-vivian", "name": "十三", "gender": "female", "style": "自信、可爱、略带叛逆", "provider": "qwen", "tier": "premium", "provider_voice": "Vivian"},
    {"id": "qwen-momo", "name": "Momo", "gender": "female", "style": "活泼可爱", "provider": "qwen", "tier": "premium", "provider_voice": "Momo"},
    {"id": "qwen-moon", "name": "Moon", "gender": "female", "style": "温柔宁静", "provider": "qwen", "tier": "premium", "provider_voice": "Moon"},
    {"id": "qwen-maia", "name": "Maia", "gender": "female", "style": "优雅知性", "provider": "qwen", "tier": "premium", "provider_voice": "Maia"},
    {"id": "qwen-kai", "name": "Kai", "gender": "male", "style": "沉稳可靠", "provider": "qwen", "tier": "premium", "provider_voice": "Kai"},
    {"id": "qwen-nofish", "name": "Nofish", "gender": "male", "style": "幽默随性", "provider": "qwen", "tier": "premium", "provider_voice": "Nofish"},
    {"id": "qwen-bella", "name": "Bella", "gender": "female", "style": "甜美亲切", "provider": "qwen", "tier": "premium", "provider_voice": "Bella"},
    {"id": "qwen-eldric-sage", "name": "Eldric Sage", "gender": "male", "style": "睿智沉稳", "provider": "qwen", "tier": "premium", "provider_voice": "Eldric Sage"},
    {"id": "qwen-mia", "name": "Mia", "gender": "female", "style": "清新自然", "provider": "qwen", "tier": "premium", "provider_voice": "Mia"},
    {"id": "qwen-mochi", "name": "Mochi", "gender": "female", "style": "软糯可爱", "provider": "qwen", "tier": "premium", "provider_voice": "Mochi"},
    {"id": "qwen-bellona", "name": "Bellona", "gender": "female", "style": "坚定有力", "provider": "qwen", "tier": "premium", "provider_voice": "Bellona"},
    {"id": "qwen-vincent", "name": "Vincent", "gender": "male", "style": "绅士优雅", "provider": "qwen", "tier": "premium", "provider_voice": "Vincent"},
    {"id": "qwen-bunny", "name": "Bunny", "gender": "female", "style": "俏皮灵动", "provider": "qwen", "tier": "premium", "provider_voice": "Bunny"},
    {"id": "qwen-neil", "name": "Neil", "gender": "male", "style": "温和耐心", "provider": "qwen", "tier": "premium", "provider_voice": "Neil"},
    {"id": "qwen-elias", "name": "Elias", "gender": "male", "style": "深情磁性", "provider": "qwen", "tier": "premium", "provider_voice": "Elias"},
    {"id": "qwen-arthur", "name": "Arthur", "gender": "male", "style": "稳重儒雅", "provider": "qwen", "tier": "premium", "provider_voice": "Arthur"},
    {"id": "qwen-nini", "name": "Nini", "gender": "female", "style": "天真烂漫", "provider": "qwen", "tier": "premium", "provider_voice": "Nini"},
    {"id": "qwen-seren", "name": "Seren", "gender": "female", "style": "安静治愈", "provider": "qwen", "tier": "premium", "provider_voice": "Seren"},
    {"id": "qwen-pip", "name": "Pip", "gender": "male", "style": "少年气", "provider": "qwen", "tier": "premium", "provider_voice": "Pip"},
    {"id": "qwen-stella", "name": "Stella", "gender": "female", "style": "明亮自信", "provider": "qwen", "tier": "premium", "provider_voice": "Stella"},
    # ---- GLM-TTS (Zhipu, premium) ----
    {"id": "zhipu-tongtong", "name": "彤彤", "gender": "female", "style": "默认音色，温柔自然", "provider": "zhipu", "tier": "premium", "provider_voice": "tongtong"},
    {"id": "zhipu-xiaochen", "name": "小陈", "gender": "male", "style": "通用男声，沉稳", "provider": "zhipu", "tier": "premium", "provider_voice": "xiaochen"},
    {"id": "zhipu-chuichui", "name": "锤锤", "gender": "male", "style": "活泼男声", "provider": "zhipu", "tier": "premium", "provider_voice": "chuichui"},
    {"id": "zhipu-jam", "name": "Jam", "gender": "neutral", "style": "动动动物圈角色音色", "provider": "zhipu", "tier": "premium", "provider_voice": "jam"},
    {"id": "zhipu-kazi", "name": "Kazi", "gender": "neutral", "style": "动动动物圈角色音色", "provider": "zhipu", "tier": "premium", "provider_voice": "kazi"},
    {"id": "zhipu-douji", "name": "Douji", "gender": "neutral", "style": "动动动物圈角色音色", "provider": "zhipu", "tier": "premium", "provider_voice": "douji"},
    {"id": "zhipu-luodo", "name": "Luodo", "gender": "neutral", "style": "动动动物圈角色音色", "provider": "zhipu", "tier": "premium", "provider_voice": "luodo"},
    # ---- Tencent premium voices (premium) ----
    {"id": "tencent-yunxiaoning", "name": "云小宁", "gender": "female", "style": "精品音色，温柔亲切", "provider": "tencent", "tier": "premium", "provider_voice": "101001"},
    {"id": "tencent-yunxiaoqi", "name": "云小奇", "gender": "male", "style": "精品音色，阳光少年", "provider": "tencent", "tier": "premium", "provider_voice": "101002"},
    {"id": "tencent-yunxiaowan", "name": "云小晚", "gender": "female", "style": "精品音色，知性优雅", "provider": "tencent", "tier": "premium", "provider_voice": "101003"},
    {"id": "tencent-yunxiaoye", "name": "云小叶", "gender": "female", "style": "精品音色，清新活泼", "provider": "tencent", "tier": "premium", "provider_voice": "101004"},
    {"id": "tencent-yunxiaolong", "name": "云小龙", "gender": "male", "style": "精品音色，沉稳磁性", "provider": "tencent", "tier": "premium", "provider_voice": "101005"},
    {"id": "tencent-yunxiaoman", "name": "云小曼", "gender": "female", "style": "精品音色，甜美", "provider": "tencent", "tier": "premium", "provider_voice": "101006"},
    # ---- Edge TTS (Microsoft, free tier, no key) ----
    {"id": "edge-xiaoxiao", "name": "晓晓", "gender": "female", "style": "温柔，适合讲故事", "provider": "edge", "tier": "free", "provider_voice": "zh-CN-XiaoxiaoNeural"},
    {"id": "edge-yunyang", "name": "云扬", "gender": "male", "style": "阳光专业", "provider": "edge", "tier": "free", "provider_voice": "zh-CN-YunyangNeural"},
    {"id": "edge-yunze", "name": "云泽", "gender": "male", "style": "沉稳磁性", "provider": "edge", "tier": "free", "provider_voice": "zh-CN-YunzeNeural"},
    {"id": "edge-yunjian", "name": "云健", "gender": "male", "style": "活力运动", "provider": "edge", "tier": "free", "provider_voice": "zh-CN-YunjianNeural"},
]

VOICE_MAP: dict[str, dict] = {v["id"]: v for v in VOICES}


def public_voice(v: dict) -> dict:
    """Shape returned by GET /voices (spec fields)."""
    return {
        "id": v["id"],
        "name": v["name"],
        "gender": v["gender"],
        "style": v["style"],
        "provider": v["provider"],
        "tier": v["tier"],
    }


# ---- daily sentences (original, positive psychology, no mysticism) ----

DAILY_SENTENCES: list[str] = [
    "今天的你，比昨天多走了一小步，这就够了。",
    "目标不用一次完成，每天前进一点点，时间会帮你把路铺出来。",
    "先从最小的那件事开始，做完它，今天就赢了。",
    "你不需要和别人比速度，只需要比昨天的自己更靠近目标一点。",
    "坚持不是硬撑，是每天给自己一个小小的约定，然后兑现它。",
    "每一个认真过好今天的人，都在悄悄改写自己的未来。",
    "累了就歇一会儿，歇好了再走，停下来不是放弃。",
    "把大目标拆成小台阶，一级一级走上去，回头看已经很高了。",
    "今天的努力不一定立刻开花，但它一定在土里生根。",
    "相信过程：你做的每一件小事，都在为未来的自己投票。",
    "不用等到准备好了才开始，开始了才会慢慢准备好。",
    "给自己一点耐心，好事情的发生往往比想象中慢一点，但一定会来。",
    "今天的你值得一句夸奖：你还在坚持，这本身就很了不起。",
    "把注意力放在能做的事情上，一件一件来，焦虑会慢慢变小。",
    "习惯的力量很安静，每天重复一点点，改变会在某天突然被看见。",
    "遇到困难先别急着否定自己，先问一句：下一步最小能做什么？",
    "你的未来不是等来的，是今天的每一个选择一点点拼出来的。",
    "允许今天做得不够好，明天还有一次重新开始的机会。",
    "认真对待自己的愿望，就是认真对待自己的人生。",
    "每一次打卡，都是在告诉未来的自己：我没有食言。",
    "慢慢来也没关系，重要的是方向对了，而且一直在走。",
    "今天种下的种子，不会明天就长成大树，但它一定在生长。",
    "把今天过好，就是对未来最好的准备。",
    "你已经走过的路，比你以为的要远得多，别小看自己。",
    "困难是暂时的，成长是自己的，今天的难是为了明天的轻松。",
    "给自己一个微笑，再小的进步也值得被庆祝。",
    "不要小看每天十五分钟，坚持下去就是一笔不小的财富。",
    "愿望实现的那一天，你会感谢今天没有放弃的自己。",
    "今天的你正在成为未来那个更好的自己，继续走下去。",
    "生活不会一下子变好，但每天变好一点点，就是变好。",
]


def daily_sentence(for_date: date | None = None) -> dict:
    d = for_date or date.today()
    idx = d.toordinal() % len(DAILY_SENTENCES)
    return {"date": d.isoformat(), "sentence": DAILY_SENTENCES[idx], "index": idx}
