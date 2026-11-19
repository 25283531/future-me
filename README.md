# 未来我 — 给未来自己的一封信

积极心理 / 目标可视化 App：写下愿望，AI 以“未来的自己”口吻回一封信（文本 + 语音），每天一句、打卡、愿景板。第一阶段免费，不进应用商店，直发 APK。

## 结构

- `app/` — Android 客户端（Kotlin + Jetpack Compose）
- `backend/` — 后端（Python + FastAPI + SQLite，Docker 部署）
- `.github/workflows/` — CI：`android.yml` 编 debug APK，`backend.yml` 跑 pytest
- `PLAN.md` — 产品方案；`TTS-PRICING.md` — TTS 选型与套餐比价

## App 构建

推代码到 `main` 即自动构建，APK 在 Actions 的 `futureme-debug-apk` 产物里下载。本地构建见 `app/README.md`（需 Android Studio）。

## 后端部署

见 `backend/README.md`：配好 `.env`（至少一个 LLM 提供商 Key + TTS Key），`docker compose up -d`。部署在用户家里路由器（iStoreOS + Docker）。

## 关键规则

- 写信 LLM：多提供商 OpenAI 兼容接口（千问 / 腾讯混元 / 硅基流动 / 智谱 GLM / 通用接口），**不用豆包**；Key 只放服务端。
- 信件 150–200 字，第一人称过去时；不写玄学 / 塔罗 / 占星 / 显化 / 改运 / 转运 / 宇宙能量 / 注定 / 必成，不承诺结果。
- TTS：Qwen3-TTS 为主，智谱 / 腾讯 / Edge 兜底；同一封信 + 同一音色只合成一次并缓存。
