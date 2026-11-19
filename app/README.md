# 未来我 — Android App

写下愿望，生成一封来自未来的鼓励信，每天打卡坚持，和未来的自己一起慢慢变好。

> 不进应用商店，直发 APK。第一阶段全部免费（7 天试用 + ¥9.9/月是产品定价，暂不收费、不接支付）。

## 技术栈

- Kotlin + Jetpack Compose（Material 3），单 Activity + Navigation Compose
- minSdk 26 / targetSdk 34 / compileSdk 34，Java 17
- Retrofit + OkHttp + Gson（后端接口），Room（愿望/未来信离线缓存），
  DataStore（设备号、token、服务器地址、选中音色），
  ExoPlayer（androidx.media3，信件语音播放），WorkManager（每天 8:00 / 20:00 本地提醒）
- 手动依赖注入（`FutureMeApp` 里集中装配，无 DI 框架）

## 目录结构

```
app/
├── settings.gradle.kts / build.gradle.kts / gradle.properties
├── gradle/libs.versions.toml          # 版本目录（AGP 8.5.2 / Kotlin 2.0.21 / Compose BOM 2024.09.00）
└── app/
    ├── build.gradle.kts
    └── src/main/
        ├── AndroidManifest.xml
        ├── res/values/{colors, themes, strings}.xml
        ├── res/mipmap-anydpi-v26/     # 自适应图标占位（见下）
        └── java/com/junze/futureme/
            ├── MainActivity.kt        # 底部导航 + NavHost + 通知权限
            ├── FutureMeApp.kt         # Application：装配依赖、定时提醒
            ├── data/api/              # ApiService（DTO + Retrofit 接口）、ApiClient
            ├── data/local/            # Room：AppDatabase（wishes / letters）
            ├── data/prefs/            # SettingsStore（DataStore）
            ├── data/audio/            # AudioPlayer（ExoPlayer 包装）
            ├── data/repository/       # FutureMeRepository（缓存优先 + 401 重登）
            ├── worker/                # ReminderWorker（8:00 / 20:00 本地通知）
            └── ui/{theme, nav, components, home, letters, daily, me}/
```

## 界面（底部导航 4 个 Tab）

| Tab | 内容 |
|---|---|
| 许愿 | 写愿望（文本 + 6 分类 + 30/90/365 天）→ POST /wishes；下方是我的愿望列表（目标日、倒计时、状态），点进愿望可看它的信、生成新信 |
| 未来信 | 选愿望 + 选音色 → 生成未来信；信件列表；信件详情：全文（标“AI 生成”）+ 语音播放（播放/暂停、进度条、可拖动） |
| 每日一句 | 当日一句 + 大打卡按钮 + 坚持天数 / 累计天数 |
| 我的 | 会员状态、愿景板（当前愿望卡片，可保存图片到相册）、服务器地址设置、消息/活动（打开 App 时拉取）、关于 |

## 后端接口契约

Base URL 默认 `http://100.72.221.19:6999`（路由器 Tailscale IP），
局域网备用 `http://10.0.1.1:6999`，可在「我的 → 服务器地址」里改。

- 所有接口挂在 `/api/v1` 下；先 `POST /auth/device {device_id}` 换 token，
  之后每次请求带 `Authorization: Bearer <token>`；401 时自动重登一次再重试。
- 愿望：`POST /wishes`、`GET /wishes`
- 信件：`POST /letters/generate {wish_id, voice_id}`、`GET /letters`
- 音色：`GET /voices`（按 provider 分组、free/member 分档，App 端选音色后存 DataStore）
- 每日一句：`GET /daily-sentence`；打卡：`POST /checkin`、`GET /checkin/status`
- 会员：`GET /membership/status`；消息/活动：`GET /messages`、`GET /activities`
- 语音：信件里 `audio_url`（绝对地址 / 路径 / 文件名三种都认）或 `audio_file`，
  App 会拼成完整 URL 后用 ExoPlayer 流式播放。

**注意**：`backend/` 目录在写 App 时还不存在，上面是任务给定的契约。
后端落地后如有字段名出入，只改 `data/api/ApiService.kt` 里的 DTO 即可，
界面和缓存层不用动。

## 构建

1. 用 Android Studio（Ladybug 及以上，JDK 17）打开 `app/` 目录，等待 Gradle 同步。
   首次同步会自动下载 Gradle 8.7（`gradle/wrapper/gradle-wrapper.properties` 已配好；
   本仓库没有提交 `gradlew` 脚本和 wrapper jar，Android Studio 导入时会生成，
   或本机装好 Gradle 后跑 `gradle wrapper`）。
2. 连一台 Android 手机（或开模拟器），点 Run；或命令行：
   ```bash
   ./gradlew assembleDebug
   # APK: app/build/outputs/apk/debug/app-debug.apk
   ```
3. 发版：`./gradlew assembleRelease`（当前 release 未开混淆，`proguard-rules.pro` 已留好）。
4. 安装到手机：`adb install -r app-debug.apk`，首次打开允许通知权限（提醒用），
   再允许“安装未知应用”（直发 APK 的常规步骤）。

## 连后端

- 手机和路由器在同一个 Tailscale 网络时，默认地址就能通；
  在家连 Wi-Fi 时，可在「我的 → 服务器地址」里点「局域网」切到 `10.0.1.1:6999`。
- 服务器地址改完会清空 token 并重新做设备认证，不用重装 App。
- 离线时愿望和信件显示 Room 里的缓存，并提示“网络不可用，显示的是上次保存的内容”。

## 图标

- `res/mipmap-anydpi-v26/` 目前是**占位自适应图标**（奶油底 + 简易日出矢量），
  不要把 200×200 的 `weilaiwo-icon-200.png` 直接当启动图标用（尺寸不够）。
- 正式做法：用 `workspace/future-me-icon/` 里的 1600×1600 原图，
  在 Android Studio 里右键 `res` → New → Image Asset → Launcher Icons，
  选前景/背景图生成各密度 `mipmap-*`，再删掉占位矢量。
- 颜色已按图标取好：奶油底 `#FFF7E8`、暖橙 `#E8833A`、深琥珀文字 `#3D2C1E`。

## 已知未验证（本机无 Java/Android SDK，无法编译）

- 未跑过 `./gradlew assembleDebug`，未在真机/模拟器上跑过。
  交接后第一步就是在 Android Studio 里同步 + 编译，重点看：
  `rememberGraphicsLayer`（愿景板截图，Compose 1.7 API）、
  Media3 ExoPlayer 的播放状态回调、WorkManager 的 8:00/20:00 首次延迟计算。
- 后端 `backend/` 还不存在，接口契约按任务约定写死在 `ApiService.kt` 里，
  后端完成后需要逐个接口联调（字段名、分页、错误码都以服务端为准）。
- 包名暂定 `com.junze.futureme`，用户定下来后在 `app/build.gradle.kts`
  的 `namespace`/`applicationId` 里改一处即可。
- 愿望分类已按 PLAN.md 改为「事业升职/换工作、财富收入、脱单恋爱、健康身材、
  学习考证、家庭亲子」（`ui/home/HomeScreen.kt` 的 `WISH_CATEGORIES`）。
  ⚠️ 后端 `backend/app/main.py` 的 `CATEGORIES` 目前还是旧版
  （学习考证 / 健康 / 事业 / 家庭 / 财富 / 自我成长），不改后端会报 400，
  后端联调时必须同步改成 PLAN.md 这一套。
- 界面按年轻人审美：常规字号（标题 22sp / 正文 14sp / 小字 12sp），
  不再做老年人大字优化；主按钮统一 48dp 高，打卡按钮 96dp。
