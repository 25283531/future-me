# 未来我 (Future Me) — 后端 API

FastAPI + SQLite，单容器部署。给 Android App 用：写愿望 → 多供应商大模型生成未来信（文本+语音）→ 每日一句 → 打卡 → 活动/消息拉取。

第一阶段免费，不接支付；所有功能不设付费墙。默认端口 **6999**。

## 目录

| 路径 | 说明 |
|---|---|
| `app/` | 源码（`main.py` 路由，`admin.py` 后台接口 + `admin.html` 后台页面，`llm.py` 多供应商 LLM（千问/混元/硅基流动/智谱/通用接口），`tts.py` TTS 降级链，`catalog.py` 音色/通用兜底句，`content_filter.py` 内容过滤 + 违规分类，`database.py` SQLite + 设置库，`auth.py` 设备鉴权，`context.py` 用户上下文组装，`daily.py` 个性化每日一句，`crypto.py` 字段级加密） |
| `data/` | 数据卷：SQLite（`futureme.db`）、音频缓存（`audio/`）、加密密钥（`.encryption.key`，0600）、活动/消息种子（`activities.json`、`messages.json`） |
| `tests/` | pytest 冒烟测试 |
| `scripts/smoke.sh` | curl 冒烟脚本 |
| `scripts/decrypt_export.py` | 解密导出工具（检查专用，见下） |

## 后台管理（Web Admin）

地址：`http://<服务器IP>:6999/admin`

- 首次打开：设置管理员密码（至少 6 位，scrypt 存库），设置后即登录。
- 之后：密码登录，会话 Cookie 7 天有效；右上角可退出。
- 栏目：仪表盘（汇总数字）、话题与合规（分类分布 + 违规类型统计）、LLM 配置、TTS 配置、会员配置、消息推送、活动管理、每日一句（生成设置）、邮件（SMTP，阿里企业邮箱）。
- **所有 Key 都在这里配**：LLM 五家供应商、TTS 三家、会员试用天数/月费/付费墙。密钥存在数据库设置表里，不走环境变量，不进 App。

## 隐私红线（硬性）

- 后台**绝对不查看任何单个用户的内容**：不看愿望原文、信件内容、记忆内容、每日一句内容，不按设备/用户列出，不导出。
- 后台只看汇总数字：设备/愿望/信件/打卡总数、今日活跃（去重设备数）、各愿望分类的数量、违规类型的数量。
- 用户内容与 AI 答复在 SQLite 里是**加密存储**的（Fernet，见下）。后台接口永远不返回解密后的用户内容。

## 加密存储（Fernet）

- 加密字段：`wishes.text`、`letters.text`、`daily_messages.text`、`memories.text`、`persona.summary`。不加密的只保留运营必需的元数据：分类、日期、数量、device_id、违规标记（聚合统计靠这些明文字段）。
- 密钥文件：`DATA_DIR/.encryption.key`，首次启动自动生成，权限 0600，与数据库分开存放。密钥绝不进数据库、不打日志、不走任何 API。
- 解密边界：服务端只在内存里解密，且只为两种情况——(a) 把内容回传给内容所属用户自己的 App；(b) 生成该用户的 AI 内容（写信/每日一句）时组装上下文。
- 启动迁移：启动时自动把表中还是明文的旧行加密（能按 Fernet 解开的视为已加密，否则视为明文，加密后写回）。
- **密钥文件要单独备份，丢了数据就永久无法恢复。**

### 解密检查（公检法/人工检查路径）

后台 UI 里没有任何查看/解密用户内容的入口。检查只能用命令行工具，同时需要密钥文件 + 数据库文件：

```bash
python3 scripts/decrypt_export.py \
  --db data/futureme.db --key data/.encryption.key \
  --out /tmp/futureme-export.json --operator "检查人姓名"
# 可选：--types wishes,letters,memories,daily_messages（默认全部）
```

每次运行都会往审计日志（默认 `<out>.audit.log`）记一条：时间、操作人、导出了哪几类记录各多少条——**不记内容**。

## API（全部在 `/api/v1` 下，`GET /audio/{file}.mp3` 与 `/admin` 除外）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/health` | 健康检查 + 已配置的供应商 |
| POST | `/api/v1/auth/device` | `{device_id}` → `{token}`，其余接口用 `Authorization: Bearer <token>` |
| GET | `/api/v1/auth/captcha` | 注册验证码：返回 `{challenge_id, svg}`（4 字符 SVG，纯 stdlib 绘制） |
| POST | `/api/v1/auth/register` | `{email, password, device_id, captcha_challenge_id, captcha_answer}` → `{token, user, email_sent}`；未验证也可正常使用 |
| POST | `/api/v1/auth/login` | `{email, password, device_id}` → `{token, user}`；未验证也可登录 |
| GET | `/api/v1/auth/me` | 当前登录账号（`account: null` 表示匿名设备） |
| POST | `/api/v1/auth/verify-email` | `{code}`（6 位，10 分钟有效，错 5 次作废） |
| POST | `/api/v1/auth/resend-verification` | 登录态重发验证邮件；已验证返回 `already_verified`，SMTP 未配时返回 `email_sent: false` |
| POST | `/api/v1/auth/forgot-password` | `{email}` → 永远返回同一通用回复，不透露邮箱是否存在；仅已验证邮箱会收到码 |
| POST | `/api/v1/auth/reset-password` | `{email, code, new_password}`（仅已验证邮箱可用） |
| POST | `/api/v1/auth/change-password` | `{current_password, new_password}`（登录态；仅已验证邮箱可用） |
| POST | `/api/v1/auth/delete-account` | `{password}` → 删除账号及关联设备在服务端的数据（愿望/信件/打卡/记忆），不可恢复 |
| GET | `/privacy` | 隐私协议 HTML 页 |
| GET | `/api/v1/privacy` | 隐私协议 JSON（App 拉取，离线时用 App 内置副本） |
| POST/GET | `/api/v1/wishes` | 创建 / 列出我的愿望（category：事业升职/换工作、财富收入、脱单恋爱、健康身材、学习考证、家庭亲子；days：30/90/365） |
| GET | `/api/v1/wishes/{id}` | 愿望详情 |
| POST | `/api/v1/letters/generate` | `{wish_id, voice_id?, provider?}` → 生成未来信（服务端调大模型；没有任何供应商 Key 时 503；`provider` 指定未配置/不存在的供应商时 400） |
| GET | `/api/v1/llm/providers` | 大模型供应商表 `[{id, name, configured, model}]`，App 用来展示可用供应商 |
| GET | `/api/v1/letters`、`/api/v1/letters/{id}` | 我的信件 |
| GET | `/api/v1/voices` | 音色目录（Qwen 24 + 智谱 7 + 腾讯精品 6 + Edge 4） |
| POST | `/api/v1/tts/synthesize` | `{text, voice_id}` → `{audio_url}`，按 sha256(text+voice) 缓存 |
| GET | `/audio/{file}.mp3` | 播放缓存音频 |
| GET | `/api/v1/daily-sentence` | **个性化每日一句**：按该用户的进行中愿望 + 上下文，AI 生成一句来自“目标实现后的自己”的话；当天已生成过返回缓存；无愿望/无 LLM Key 时用内置通用鼓励句兜底 |
| POST | `/api/v1/checkin` | 打卡（连续 7 天自动记一条 progress 记忆） |
| GET | `/api/v1/checkin/status` | `{streak_days, total_days, checked_in_today}` |
| GET | `/api/v1/activities` | 活动列表（后台管理） |
| GET | `/api/v1/messages` | 消息列表，App 打开时拉取（后台管理） |
| GET | `/api/v1/membership/status` | `{plan: free_trial, trial_days_left, price_monthly_cny: 9.9, paywalled: false}`（按后台会员配置返回）；登录账号时返回账号会员（`account: true`），否则按设备试用 |

### 未来信供应商（OpenAI 兼容 `/chat/completions`，统一走 `app/llm.py`）

| id | 供应商 | 默认模型 | Key 去哪拿 |
|---|---|---|---|
| `qwen`（默认） | 阿里云千问 | `qwen-plus` | 阿里云百炼 Model Studio（DashScope Key，与 Qwen3-TTS 共用） |
| `hunyuan` | 腾讯混元 | `hunyuan-turbos-latest` | 腾讯混元控制台 |
| `siliconflow` | 硅基流动 | `Qwen/Qwen3-8B` | siliconflow.cn |
| `zhipu` | 智谱 GLM | `glm-4-flash` | 智谱 bigmodel.cn（与 GLM-TTS 共用） |
| `generic` | 通用接口 | （必填，无默认值） | 任意 OpenAI 兼容网关（Base URL + Key + 模型三者齐全） |

切换方式（二选一）：

- 改默认供应商：后台 LLM 配置里改，或单次指定：`POST /letters/generate {"wish_id": 1, "provider": "hunyuan"}`。
- 至少要配一个供应商的 Key，否则写信接口返回 503；`GET /llm/providers` 可查各供应商是否已配置。
- 不用豆包：后端已不含任何豆包/火山方舟代码。

### 邮箱账号、反机器注册与邮件（2026-11-20）

- 账号（`users` 表，`app/accounts.py`）：邮箱唯一、scrypt 密码哈希、email_verified、6 位验证码 + 过期、重置码 + 过期。注册可选——匿名设备认证照常可用。**未验证邮箱可以登录并正常使用全部功能**；改密码和找回密码必须先验证邮箱；找回密码永远返回同一通用回复，不透露邮箱是否存在。
- Token：沿用 HMAC token，v2 在签名负载里加 `user_id`（`device.nonce.user_id`）；旧版 3 段 v1 token 仍可验证（匿名设备）。注册/登录时把调用设备关联到账号（`devices.user_id`）；会员按账号算（已登录），否则按设备试用；愿望/信件本轮仍按设备，不做跨设备迁移。注销账号会删除该账号及关联设备在服务端的数据。
- 防机器注册（无第三方 CAPTCHA、无外部 Key）：限流计数存 SQLite（`rate_limits` 表，重启不丢）——注册每 IP 每小时 5 次、登录每 IP/每邮箱每小时 10 次后临时锁定、验证/重发每邮箱每小时 3 次；验证码 10 分钟过期、一次有效、错 5 次作废。另加轻量服务端验证码：注册时后端生成随机 4 字符，用纯 stdlib 画成带噪点/扭曲的 SVG（`GET /api/v1/auth/captcha`），App 展示后用户输入，注册时校验（challenge 一次有效，失败即作废）。
- 邮件（`app/mail.py`，只用 stdlib smtplib）：验证/重置邮件走 SMTP，配置在后台设置表 + `/admin` 邮件栏目（主机、端口、加密、账号、密码、发件人）+ 测试发送按钮。**默认阿里企业邮箱**（用户 2026-11-20 决定）：`smtp.qiye.aliyun.com:465` + SSL（隐式 TLS）；阿里企业邮箱**不提供 587 端口**，不要改成 STARTTLS/587。用户名 = 完整邮箱地址；密码 = 该邮箱账号的密码（开启第三方客户端安全密码时填安全密码）。SMTP 未配置时注册登录照常可用（账号可用、未验证），只是发不出验证邮件——后台邮件栏目明确显示“未配置”。SMTP 密码按 secret 存设置表，不进环境变量、不进日志。
- 隐私协议（`app/privacy.py`）：中文协议与实际实现一致——收集内容（邮箱、密码哈希、愿望/信件/打卡、设备号）、用途、Fernet 加密、后台看不到任何单个用户内容（仅汇总）、LLM/TTS 供应商仅在生成时收到文本、保存期限 + 按请求删除、法律保留、用户权利、联系方式占位。`GET /privacy`（HTML）与 `GET /api/v1/privacy`（JSON，供 App）；App 在“我的”页有“隐私协议”入口，注册屏有“我已阅读并同意《隐私协议》”复选框，不勾选不能注册；App 内置一份协议副本（`res/raw/privacy_policy.txt`）作离线兜底。

### 每日一句（个性化）与记忆系统

- 每日一句不是通用内容：用户设定目标后，AI 每天为该用户生成一句与目标相关的话（来自“目标实现后的自己”），当天已生成过就返回缓存，不重复生成；下一句生成时会参考前几天的句子，保持连续性。
- 记忆系统是拟人化、会自己演变的（`app/evolution.py`，自研，无开源记忆项目/向量库）：未来的自己有独立人格状态（`persona` 表：关系阶段 初识→熟悉→默契→知己，按互动次数进阶；第一人称介绍 summary；warmth/pride 特征值随事件变化）；记忆会回忆强化（进入上下文 recall_count+1、重要度+0.05）也会遗忘（30 天不回忆每天 -0.02，很淡很旧的标记 faded，不再进上下文，数据不删）；每天最多整合一次，把最近的事提炼成持久记忆、最多形成一条感悟（insight）、重写人格介绍；无 LLM Key 时只做规则处理，不失败。
- 记忆（`memories` 表）：愿望本身记为 milestone 记忆（内容+目标日）；连续打卡 7 天自动记一条 progress 记忆（带“自豪”情绪）；后台不查看记忆内容，记忆只供服务端组装 LLM 上下文使用。
- 上下文组装（`app/context.py`）：先是人格介绍（summary + 关系阶段 + 特征值），再是进行中愿望、打卡连续天数与近期打卡、最近几封信、最近 7 天每日一句、记忆事实（按演变后的重要度排序，排除 faded）、最新一条感悟。写信和每日一句生成都用这套上下文。
- 后台“记忆演变”栏目：演变总开关、反思感悟开关、整合间隔（1–7 天）。
- 兜底：无进行中愿望、关闭生成开关、或没有配 LLM Key 时，用服务端内置的少量通用鼓励句（写死在代码里，不进后台管理）。

### 未来信规则（prompt + 输出过滤双重 enforced）

- 第一人称“我”、过去时，像愿望已经实现一样回顾
- 150–200 汉字，必须提到愿望内容和天数
- 禁止：玄学/塔罗/占星/显化/改运/转运/宇宙能量/注定/必成/财运/包过等，以及任何医疗、理财、考试结果保证
- 生成后过过滤器，不合格自动重写一次，仍不合格返回 502；信件入库时标注 `ai_generated: true`，App 展示时须写“AI 生成”
- 违规只记类型和数量（`violation_stats` 表，按天汇总），不存原文、不关联具体用户

### TTS 降级链

Qwen3-TTS（DashScope，主力）→ 智谱 GLM-TTS → 腾讯云 TTS（精品）→ Edge TTS（免费兜底，无 Key 也能用）。
请求音色所属的供应商优先尝试，其次按后台默认 TTS 供应商，再按链降级。没有配任何 Key 时只走 Edge，接口不硬失败。
同一文本+音色只合成一次，存 `data/audio/<sha256>.mp3`。

## 本地运行

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 6999
# 健康检查：curl http://localhost:6999/api/v1/health
# 后台：打开 http://localhost:6999/admin，首次设置管理员密码，然后配 Key。
```

## 部署到家里路由器（iStoreOS Docker）

```bash
# 1. 把 backend/ 整个目录传到路由器上，例如 /root/futureme-backend/
# 2. 启动（镜像由 GitHub Actions 构建并推到 GHCR）：
docker compose pull
docker compose up -d
docker compose logs -f

# 3. 验证：
curl http://<路由器IP>:6999/api/v1/health
# 4. 打开 http://<路由器IP>:6999/admin，首次设置管理员密码，然后配 Key。
# 数据持久化在 ./data（SQLite + 音频缓存 + 加密密钥），升级时不要删这个目录。
# 密钥文件 data/.encryption.key 要单独备份，丢了数据无法恢复。
# 5. 更新：
docker compose pull
docker compose up -d
```

> App 内置服务器地址 `https://futureme.250886.xyz:32123`（用户不可改），
> 需要把 6999 端口映射到 32123 并配好 TLS；该地址尚未联通前 App 连不上后端。
> 域名/DDNS 沿用路由器现有的 Lucky/DDNS。

## 测试

```bash
# pytest（会真实调用 Edge TTS 合成一次，需要联网）：
.venv/bin/pytest tests/ -q

# curl 冒烟（启动一个临时服务，跑完自动停）：
bash scripts/smoke.sh
```

## 配置（服务器设置，改 `docker-compose.yml` 里的 `environment` 即可；没有 .env 文件）

| 变量 | 必填 | 说明 |
|---|---|---|
| `HOST` / `PORT` | 否 | 监听地址/端口，默认 `0.0.0.0:6999` |
| `DATA_DIR` | 否 | 数据目录，默认 `./data`（Docker 里是 `/app/data`） |
| `JWT_SECRET` | 否 | 仅老部署兼容：覆盖自动生成的设备 token 签名密钥；新部署不要设 |

其余配置（LLM/TTS Key、模型、会员、每日一句生成设置）全部在后台 `/admin` 里改，存在数据库设置表里。
