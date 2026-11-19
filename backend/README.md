# 未来我 (Future Me) — 后端 API

FastAPI + SQLite，单容器部署。给 Android App 用：写愿望 → 多供应商大模型生成未来信（文本+语音）→ 每日一句 → 打卡 → 活动/消息拉取。

第一阶段免费，不接支付；所有功能不设付费墙。

## 目录

| 路径 | 说明 |
|---|---|
| `app/` | 源码（`main.py` 路由，`llm.py` 多供应商 LLM（千问/混元/硅基流动/智谱/通用接口），`tts.py` TTS 降级链，`catalog.py` 音色/每日一句，`content_filter.py` 信件内容过滤，`database.py` SQLite，`auth.py` 设备鉴权） |
| `data/` | 数据卷：SQLite（`futureme.db`）、音频缓存（`audio/`）、活动/消息种子（`activities.json`、`messages.json`） |
| `tests/` | pytest 冒烟测试 |
| `scripts/smoke.sh` | curl 冒烟脚本 |

## API（全部在 `/api/v1` 下，`GET /audio/{file}.mp3` 除外）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/health` | 健康检查 + 已配置的供应商 |
| POST | `/api/v1/auth/device` | `{device_id}` → `{token}`，其余接口用 `Authorization: Bearer <token>` |
| POST/GET | `/api/v1/wishes` | 创建 / 列出我的愿望（category：学习考证/健康/事业/家庭/财富/自我成长；days：30/90/365） |
| GET | `/api/v1/wishes/{id}` | 愿望详情 |
| POST | `/api/v1/letters/generate` | `{wish_id, voice_id?, provider?}` → 生成未来信（服务端调大模型；没有任何供应商 Key 时 503；`provider` 指定未配置/不存在的供应商时 400） |
| GET | `/api/v1/llm/providers` | 大模型供应商表 `[{id, name, configured, model}]`，App 用来展示可用供应商 |
| GET | `/api/v1/letters`、`/api/v1/letters/{id}` | 我的信件 |
| GET | `/api/v1/voices` | 音色目录（Qwen 24 + 智谱 7 + 腾讯精品 6 + Edge 4） |
| POST | `/api/v1/tts/synthesize` | `{text, voice_id}` → `{audio_url}`，按 sha256(text+voice) 缓存 |
| GET | `/audio/{file}.mp3` | 播放缓存音频 |
| GET | `/api/v1/daily-sentence` | 当天一句（30 句按日期轮换） |
| POST | `/api/v1/checkin` | 打卡 |
| GET | `/api/v1/checkin/status` | `{streak_days, total_days, checked_in_today}` |
| GET | `/api/v1/activities` | 活动列表（`data/activities.json`） |
| GET | `/api/v1/messages` | 消息列表，App 打开时拉取（`data/messages.json`） |
| GET | `/api/v1/membership/status` | `{plan: free_trial, trial_days_left, price_monthly_cny: 9.9, paywalled: false}` |

### 未来信供应商（OpenAI 兼容 `/chat/completions`，统一走 `app/llm.py`）

| id | 供应商 | 默认模型 | Key 环境变量 | Key 去哪拿 |
|---|---|---|---|---|
| `qwen`（默认） | 阿里云千问 | `qwen-plus` | `DASHSCOPE_API_KEY`（与 Qwen3-TTS 共用） | 阿里云百炼 Model Studio |
| `hunyuan` | 腾讯混元 | `hunyuan-turbos-latest` | `HUNYUAN_API_KEY` | 腾讯混元控制台 |
| `siliconflow` | 硅基流动 | `Qwen/Qwen3-8B` | `SILICONFLOW_API_KEY` | siliconflow.cn |
| `zhipu` | 智谱 GLM | `glm-4-flash` | `ZHISHU_API_KEY`（与 GLM-TTS 共用） | 智谱 bigmodel.cn |
| `generic` | 通用接口 | （必填，无默认值） | `GENERIC_LLM_API_KEY` + `GENERIC_LLM_BASE_URL` + `GENERIC_LLM_MODEL` | 任意 OpenAI 兼容网关 |

切换方式（二选一）：

- 改默认供应商：`.env` 里设 `LLM_PROVIDER=zhipu`，重启容器；
- 单次指定：`POST /letters/generate {"wish_id": 1, "provider": "hunyuan"}`。
- 至少要配一个供应商的 Key，否则写信接口返回 503；`GET /api/v1/llm/providers` 可查各供应商是否已配置。
- 不用豆包：后端已不含任何豆包/火山方舟代码。

### 未来信规则（prompt + 输出过滤双重 enforced）

- 第一人称“我”、过去时，像愿望已经实现一样回顾
- 150–200 汉字，必须提到愿望内容和天数
- 禁止：玄学/塔罗/占星/显化/改运/转运/宇宙能量/注定/必成/财运/包过等，以及任何医疗、理财、考试结果保证
- 生成后过过滤器，不合格自动重写一次，仍不合格返回 502；信件入库时标注 `ai_generated: true`，App 展示时须写“AI 生成”

### TTS 降级链

Qwen3-TTS（DashScope，主力）→ 智谱 GLM-TTS → 腾讯云 TTS（精品）→ Edge TTS（免费兜底，无 Key 也能用）。
请求音色所属的供应商优先尝试，失败后按链降级。没有配任何 Key 时只走 Edge，接口不硬失败。
同一文本+音色只合成一次，存 `data/audio/<sha256>.mp3`。

## 本地运行

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # 填 Key；不填也能跑，信件生成会 503、TTS 走 Edge
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
# 健康检查：curl http://localhost:8000/api/v1/health
```

## 部署到家里路由器（iStoreOS Docker）

```bash
# 1. 把 backend/ 整个目录传到路由器上，例如 /root/futureme-backend/
# 2. 配 Key：
cp .env.example .env
vi .env   # 填 JWT_SECRET、各供应商 Key（如 DASHSCOPE_API_KEY）

# 3. 启动：
docker compose up -d --build
docker compose logs -f

# 4. 验证：
curl http://<路由器IP>:8000/api/v1/health
# 数据持久化在 ./data（SQLite + 音频缓存），升级时不要删这个目录。
# 5. 更新：
docker compose pull  # （无外部镜像时跳过）
docker compose up -d --build
```

> 域名/DDNS：沿用路由器现有的 Lucky/DDNS，把 8000 端口映射出去即可；也可以用
> Tailscale 从外网访问（路由器已跑 Tailscale）。

## 测试

```bash
# pytest（会真实调用 Edge TTS 合成一次，需要联网）：
.venv/bin/pytest tests/ -q

# curl 冒烟（启动一个临时服务，跑完自动停）：
bash scripts/smoke.sh
```

## 配置（环境变量，见 `.env.example`）

| 变量 | 必填 | 说明 |
|---|---|---|
| `JWT_SECRET` | 生产必填 | 设备 token 签名密钥，越长越好 |
| `LLM_PROVIDER` | 否 | 默认写信供应商，默认 `qwen`；`GET /llm/providers` 可查可用供应商 |
| `DASHSCOPE_API_KEY` | 写信必填其一 | 阿里云百炼 Key，千问 LLM + Qwen3-TTS 共用；不填则 qwen 不可用 |
| `QWEN_LLM_MODEL` | 否 | 千问写信模型，默认 `qwen-plus`（注意 `QWEN_MODEL` 是 TTS 模型，别混淆） |
| `HUNYUAN_API_KEY` / `HUNYUAN_MODEL` | 否 | 腾讯混元 Key / 模型（默认 `hunyuan-turbos-latest`） |
| `SILICONFLOW_API_KEY` / `SILICONFLOW_MODEL` | 否 | 硅基流动 Key / 模型（默认 `Qwen/Qwen3-8B`） |
| `ZHISHU_API_KEY` | 写信必填其一 | 智谱 bigmodel.cn Key，GLM LLM + GLM-TTS 共用 |
| `ZHISHU_MODEL` | 否 | 智谱写信模型，默认 `glm-4-flash` |
| `GENERIC_LLM_BASE_URL` / `GENERIC_LLM_API_KEY` / `GENERIC_LLM_MODEL` | 否 | 通用 OpenAI 兼容接口，三者齐全才可用 |
| `DASHSCOPE_API_KEY` | 否 | 阿里云百炼 Key，Qwen3-TTS 用；按量付费，充 100 元先用 |
| `ZHISHU_API_KEY` | 否 | 智谱 bigmodel.cn Key，GLM-TTS 用 |
| `TENCENT_SECRET_ID` / `TENCENT_SECRET_KEY` | 否 | 腾讯云 TTS；精品音色走后付费 0.3 元/万字符，不用买 2100 资源包 |
| `DATA_DIR` | 否 | 数据目录，默认 `./data`（Docker 里是 `/app/data`） |
