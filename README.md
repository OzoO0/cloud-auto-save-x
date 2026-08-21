<div align="center">

![cloud-logo](img/icon.png)

# 网盘自动转存 Cloud Auto Save X（CASX）

一条龙网盘媒体自动化平台：从找资源、追剧自动转存、智能重命名整理、数据同步分发、生成 CAS/STRM，到多网盘 302 直连反代播放，全流程打通；内置每日签到、异常任务自动修复与多渠道通知推送。

[![wiki](https://img.shields.io/badge/wiki-Documents-green?logo=github)](https://github.com/OzoO0/cloud-auto-save-x/wiki) [![github releases](https://img.shields.io/github/v/release/OzoO0/cloud-auto-save-x?logo=github)](https://github.com/OzoO0/cloud-auto-save-x) [![docker pulls](https://img.shields.io/docker/pulls/ozoo0/cloud-auto-save-x?logo=docker&\&logoColor=white)](https://hub.docker.com/r/ozoo0/cloud-auto-save-x) [![docker image size](https://img.shields.io/docker/image-size/ozoo0/cloud-auto-save-x?logo=docker&\&logoColor=white)](https://hub.docker.com/r/ozoo0/cloud-auto-save-x)

本软件完全免费开源，如果这个项目对你有帮助，请点击右上角 ⭐ Star 支持一下！

</div>

***

> \[!CAUTION]
> ⛔️⛔️⛔️ 注意！资源不会每时每刻更新，**严禁设定过高的定时运行频率！** 以免账号风控和给网盘服务器造成不必要的压力。雪山崩塌，每一片雪花都有责任！

<p align="center">
  <strong><span style="font-size: 1.25em;">Telegram 交流群：<a href="https://telegram.me/Oz0Casx">https://telegram.me/Oz0Casx</a></span></strong>
</p>

## 💡 它解决了什么：告别"手动追剧"的漫长链路

用网盘追剧的人，大多经历过这样的"一天"：

打开资源站翻找分享链接，试了几个才发现已失效；把有效的链接一集一集手动转存，追的剧多了根本顾不过来；转存完文件名五花八门，媒体库一部都刮削不出来；想在线看片又得先下载，还动不动限速；链接失效、账号被限流，只能熬夜蹲守手动修复……

本项目的目标，就是把这整条链路一次性自动化：

| 传统手动方式 | 本项目 |
| --- | --- |
| 在资源站、分享群里来回翻找链接，很多已失效 | 影视发现 + 资源搜索一键定位可用链接 |
| 分享链接一集一集手动转存，剧多顾不过来 | 填入链接后按更新节奏全自动转存 |
| 转存后文件名混乱，媒体库识别不了 | 转存即整理，自动识别剧集并标准命名 |
| 想在线看片要先下载，还常遇限速、失效 | 302 直连播放，网盘资源直接进播放器 |
| 链接失效、账号限流，需要人工盯守修复 | 自动换链、自动切号，异常自愈 + 通知推送 |

**把"找资源、追更、整理、播放"这条链路全部交给程序，你只需要打开播放器看片。**

## 🎯 核心定位：找资源 → 追剧转存 → 智能整理 → 同步分发 → 302 播放

你可以把它理解成一个"网盘追剧自动化流水线"，六个环节全自动衔接：

1. **找资源**：浏览影视榜单、搜索可用分享链接，一键创建追剧任务，不用再满网翻链接。
2. **追剧转存**：按剧集更新节奏自动运行，新剧集自动转存到你的网盘目录；分享链接失效了会自动换链修复。
3. **智能整理**：自动识别剧集并标准化重命名，转存完的文件直接就是媒体库能识别的规范命名。
4. **同步分发**：把网盘内容同步到本地媒体库或其他网盘，网盘之间互相复制还有秒传加速。
5. **挂载 STRM / 生成 CAS**：批量生成接入媒体库所需的索引数据（CAS）与直连文件（STRM），把网盘资源直接"挂"进媒体库。
6. **302 播放**：多网盘 302 智能反代（已支持飞牛影视、Emby），让播放器直接走网盘直链，在线观看不用下载。

本文档面向 Docker 镜像使用者，重点介绍功能能力、部署方式和初始化配置流程。

## 🚀 核心功能总览

### 1. 🔄 追剧任务与自动转存：项目的核心主线能力

项目最核心的能力，不是简单的"手动转存一次"，而是面向连载剧集的"追剧自动化"——你只管填链接、选目录，剩下的更新、转存、整理全部自动完成：

* **定时 + 自动双模式**：按周更日历定时运行，也可根据节目状态和任务进度自动触发，只转新增剧集，不重复转存。

* **分享目录自动定位**：粘贴分享链接后自动识别资源所在文件夹，遇到带访问码的链接也能自动处理，直接定位到剧集目录。

* **异常自动修复**：分享链接失效自动换新链（同剧同集优先匹配、大小优选、防串剧），账号被限流或探测失败自动停用并切换，任务全程无需人工值守。

* **智能重命名**：配置 TMDB API 密钥后，自动识别剧集并按标准命名整理，内置多重兜底机制，再奇怪的分享命名也能整理成规范文件名。

* **文件过滤**：通过过滤规则排除广告、样片等不需要的文件或文件夹，支持高级过滤，让转存目录干干净净。

* **一次性转存**：除追剧任务外，也支持一次性转存任务，适合电影、合集类资源。

* **自动解压**：支持压缩包自动解压转存（仅限夸克高级会员）。

* **任务全生命周期管理**：任务筛选、排序、暂停、停止、继续、手动运行，实时日志与运行记录随时可回溯。

一句话总结：**把"追更"这件事完全交给程序，你只需要看片。**

### 2. 🎬 影视发现与追剧日历

为了降低"建任务"的门槛，项目提供了完整的前置入口：

* **影视发现**：浏览热门影视榜单，自动识别剧集信息，一键创建追剧任务，剧集名、年份、更新星期自动填好。

* **资源搜索**：集成多个资源搜索渠道，自动检查链接是否有效、过滤失效链接，搜索命中后直接定位到分享目录。

* **追剧日历**：追踪节目播出时间与转存进度，支持海报视图、日历视图和年度视图，一眼看清哪些剧在更、转到了哪一集。

* **追剧总览**：首页大盘汇总全部任务运行状态、更新进度与异常提醒。

### 3. 🗂️ 智能规则：正则处理与魔法匹配

转存文件的命名整理，从"全部照收"到"精细整理"都能满足：

| pattern                        | replace                 | 效果                        |
| ------------------------------ | ----------------------- | ------------------------- |
| `.*`                           | <br />                  | 无脑转存所有文件，不整理              |
| `\.mp4$`                       | <br />                  | 转存所有 `.mp4` 后缀的文件         |
| `^【电影TT】花好月圆(\d+)\.(mp4\|mkv)` | `\1.\2`                 | 【电影TT】花好月圆01.mp4 → 01.mp4 |
| `^(\d+)\.mp4`                  | `S02E\1.mp4`            | 01.mp4 → S02E01.mp4       |
| `TV_REGEX`                     | <br />                  | 魔法匹配剧集文件                  |
| `^(\d+)\.mp4`                  | `{TASKNAME}.S02E\1.mp4` | 01.mp4 → 任务名.S02E01.mp4   |

* **默认规则**：已配置 TMDB 后，规则留空即启用兜底智能识别匹配。

* **魔法匹配和魔法变量**：表达式以 `$` 开头且替换式留空时，自动使用预设的正则表达式进行匹配和替换；`{TASKNAME}` 等变量可在替换式中引用。

* 更多说明：[正则处理教程](https://github.com/OzoO0/cloud-auto-save-x/wiki/正则处理教程)、[魔法匹配和魔法变量](https://github.com/OzoO0/cloud-auto-save-x/wiki/魔法匹配和魔法变量)

### 4. 🔁 数据同步：网盘 ⇄ 网盘 ⇄ NAS

* **多种同步端点**：支持 OpenList、网盘直连、NAS 本地目录作为数据来源或目标，组合灵活。

* **多种同步方向**：网盘与网盘、网盘与 NAS、本地资料库之间的数据同步，既能把常用网盘内容落到本地媒体库，也能在多个网盘之间建立副本。

* **统一管理**：所有同步任务统一查看进度、执行状态、运行记录与异常信息，完成后还能自动触发后续插件动作。

* **安全机制**：内置并发保护与临时文件覆盖机制，多个任务同时运行也不会冲突、不留脏数据。

### 5. 📦 网盘复制与秒传加速（dl302）

项目内置自研高速复制引擎，提供网盘之间的文件复制与分发能力：

* **全方向复制**：支持本地 → 网盘、网盘 → 本地、网盘 → 网盘的文件复制。

* **两种复制模式**：流式复制（速度快、不占本地空间）与下载复制（更省空间），可按场景选择；大文件支持分片并发下载，分片并发数与分片大小均可配置。

* **同盘秒传**：115、天翼云盘、移动云盘等同一网盘的不同账号之间，支持更高效的秒传复制体验。

* **秒传数据自动沉淀**：复制完成后自动准备好可复用的秒传数据，之后把同一文件分发到其他网盘时可以秒传；即使文件先落到本地或临时目录，也能为后续上传做好秒传准备。

### 6. ⚡ CAS 数据与 STRM 生成

CAS 与 STRM 是"网盘资源接入媒体库"的幕后数据——生成它们之后，302 播放才能把网盘资源直接变成可播直链：

* **CAS 数据任务**：扫描网盘中的视频文件，批量生成索引数据（CAS），供 302 播放、预览和多网盘分发使用。

* **任务可恢复**：任务状态自动持久化，服务重启或意外中断后可继续处理未完成的部分。

* **适用场景**：首次接入 302 播放时做一次性预热，也适合之后按需补全。

* **STRM 生成**：生成直连文件（STRM）对接媒体库，并提供 AList STRM 生成、SmartSTRM 等多种插件化方案。

### 7. 🎞️ 多网盘 302 智能反代

项目的另一条主线能力：把"网盘里的资源"变成"播放器直接能播的直链"，在线看片不用下载、不用等：

* **飞牛影视 / Emby 反代**：内置飞牛影视与 Emby 的直连适配，其它媒体系统陆续适配中。

* **智能切换(Pro)**：系统会根据访问设备的情况，自动挑选最合适的播放方式——能吃到更高画质时走本地媒体库，追求速度时自动切到网盘 302 直连。同一部资源、不同设备，自动选最优链路，全程无需手动切换。

* **智能负载均衡(Pro)**：多个账号都存有同一资源时，播放时自动轮流切换账号出直链，单个账号不会被反复请求压垮，降低限速与风控风险；一个账号出问题时自动切到其他账号，播放不中断。

* **免手动同步**：多账号自动分担无需手动同步资源，配合 CAS 能力实现"主网盘有资源、子网盘少操作甚至免操作"的 302 直连播放。

* **配合 STRM**：结合直连文件（STRM）使用时，可进一步提升媒体库预览和播放体验。

> ⚠️ 注：不建议将反代端口直接暴露给公网，可能存在安全风险，建议搭配 Web 反代服务使用。

### 8. 🧩 插件系统与媒体库联动

媒体库联动能力以插件方式集成，转存或同步完成后自动触发后续动作，无需手动操作：

| 插件                                         | 能力                                  |
| ------------------------------------------ | ----------------------------------- |
| Emby / Plex / 飞牛（fnv）                      | 转存后自动刷新媒体库，支持局部刷新（fnv\_refresh\_v2） |
| AList / OpenList                           | 挂载联动、目录同步                           |
| alist\_strm / alist\_strm\_gen / smartstrm | 多种 STRM 文件生成方案                      |
| aria2                                      | 下载任务推送                              |
| auto\_unarchive                            | 压缩包自动解压（夸克高级会员）                     |

### 9. 🔔 通知推送与日常运维

* **20+ 通知渠道**：Bark、钉钉机器人、飞书机器人、Telegram Bot、企业微信（应用/机器人）、PushPlus、Server酱、PushDeer、PushMe、wxpusher、ntfy、Gotify、Qmsg、go-cqhttp、Synology Chat、DoDo、SMTP 邮件、自定义 Webhook 等，均支持在 Web 设置页配置与测试。

* **Telegram 交互机器人**：不仅是推送，还可以作为交互机器人接收指令、远程操作。

* **自动签到**：每日自动签到领空间（支持夸克网盘、天翼云盘、百度网盘、移动云盘）。

* **多用户与权限**：Web 登录认证、用户管理与细粒度权限控制（任务、同步、账号、用户分级授权）。

* **初始化向导**：首次运行提供 Setup 向导，引导完成基础配置。

## 🏷️ 版本对比：Free 与 Pro

本软件Free 版即可使用全部核心能力（追剧转存、智能整理、同步分发、302 播放等）。Pro 版解锁"多账号协同"与"智能播放调度"等进阶能力，适合拥有多个网盘账号的重度用户。

| 能力 | Free | Pro |
| --- | --- | --- |
| 追剧自动转存 / 智能整理 / 影视发现 / 追剧日历 | ✅ | ✅ |
| 数据同步 / 网盘复制秒传 / 插件联动 / 通知推送 | ✅ | ✅ |
| CAS 生成、STRM 生成、302 播放 | ✅ 仅默认账号 | ✅ 全部账号 |
| 多账号目录配置维护 | ❌ | ✅ |
| 多账号参与权重设置 | ❌ | ✅ |
| 多账号智能负载均衡 | ❌ | ✅ |
| 智能切换：智能选择最优播放链路 | ❌ | ✅ |

### Pro 专属能力对你的实际作用

当你拥有多个网盘账号、且账号里都存有资源时，Pro 能力配合起来解决"多账号如何分工、不同设备怎么看最舒服"的问题：

* **多账号目录配置维护**：系统要先"知道每个账号的资源放在哪个目录"，才能找到并播放它们。Free 版只能登记默认账号的目录，其他账号里的资源系统"看不见"；Pro 版可以登记全部账号的目录，让所有账号里的资源都能被找到、参与播放。

* **多账号参与权重设置**：同一部资源在多个网盘里都有时，你可以按网盘速度调节"优先用谁"——把速度快的账号权重调高，播放时优先从快网盘出直链，加载更快、追剧不卡；不常用、速度慢的账号设为 0 不参与，请求不会白白消耗在慢账号上。

* **多账号智能负载均衡**：多个账号都存有同一资源时，播放时自动轮流切换账号出直链。单个账号不会被反复请求压垮，降低限速与风控风险；一个账号出问题时自动切到其他账号，播放不中断。

* **智能切换：智能选择最优播放链路**：系统会根据访问设备的情况，自动挑选最合适的播放方式——能吃到更高画质时走本地媒体库，追求速度时自动切到网盘 302 直连。同一部资源、不同设备，自动选最优链路，全程无需手动切换。（智能负载均衡是在"多个网盘账号"之间切换，智能切换是在"本地媒体库与网盘直连"两种播放方式之间切换）

一句话总结：**Free 版用默认账号即可享受全部核心能力；Pro 版让多账号资源全面激活，实现"多账号分工扛流量、哪个网盘快就从哪个播、不同设备自动匹配最优观看体验"。**

需要 Pro 许可证？欢迎加入 Telegram 交流群咨询：[https://telegram.me/Oz0Casx](https://telegram.me/Oz0Casx)。后续开放其他购买渠道。

## 网盘支持情况

|  网盘名称 |  签到 |  转存 | 302直连 | CAS | STRM |
| :---: | :-: | :-: | :---: | :-: | :--: |
|  夸克网盘 |  ✅  |  ✅  |   ✅   |  ✅  |   ✅  |
|  天翼云盘 |  ✅  |  ✅  |   ✅   |  ✅  |   ✅  |
|  移动云盘 |  ✅  |  ✅  |   ✅   |  ✅  |   ✅  |
| 115网盘 |  ❌  |  ✅  |   ✅   |  ✅  |   ✅  |
|  UC网盘 |  ❌  |  ✅  |   ✅   |  ✅  |   ✅  |
|  光鸭云盘 |  ❌  |  ✅  |   ✅   |  ✅  |   ✅  |
|  百度网盘 |  ✅  |  ✅  |   ❌   |  ❌  |   ❌  |
|  阿里云盘 |  ❌  |  ✅  |   ❌   |  ❌  |   ❌  |
| 123网盘 |  ❌  |  ✅  |   ❌   |  ❌  |   ❌  |
|  迅雷网盘 |  ❌  |  ✅  |   ✅   |  ✅  |   ✅  |

## 界面预览

![run\_log](img/run_log.png)

<details open>
<summary>WebUI 预览</summary>

![dashboard](img/96fd01ae-dc64-42f2-992c-4faf6daab0bb.png)

![discover](img/57b6b274-2b26-44df-9a28-f53e8def0582.png)

![calendar](img/76083cce-5c3e-406c-87fa-51ae8a31bcd2.png)

![calendar-year](img/8cdb803a-4107-49ac-84b4-7a215a527a5f.png)

![account](img/48c4b746-5d82-419d-8054-c3bf8514bbc5.png)

</details>


## 🚢 快速部署

### 1. 准备环境

* Docker 20.10+，Docker Compose 2.x。

* 一台可长期运行的 NAS / Linux 服务器（x86\_64 与 ARM64 均支持）。

* 如需 TMDB 智能识别、豆瓣影视发现，请确保容器可访问 TMDB / 豆瓣（必要时配置代理）。

### 2. Docker 一键部署

```shell
docker run -d \
  --name cloud-auto-save-x \
  -p 5115:5115 \
  -p 5225:5225 \
  -v ./cloud-auto-save-x/data:/app/backend/data \
  -v ./cloud-auto-save-x/media:/media \
  -v ./cloud-auto-save-x/strm:/strm \
  -v ./cloud-auto-save-x/nasfile:/app/backend/data/sync/nasfile \
  --network bridge \
  --restart unless-stopped \
  ozoo0/cloud-auto-save-x:latest
  # 国内镜像：registry.cn-hangzhou.aliyuncs.com/ozoo0/cloud-auto-save-x:latest
```

### 3. docker-compose 部署（推荐）

```yaml
name: cloud-auto-save-x
services:
  cloud-auto-save-x:
    image: ozoo0/cloud-auto-save-x:latest
    container_name: cloud-auto-save-x
    network_mode: bridge
    ports:
      - 5115:5115   # Web 管理台 + 302 端口（:前可改，:后不可改）
      - 5225:5225   # 反代端口（:前可改，:后不可改）
    restart: unless-stopped
    volumes:
      - ./cloud-auto-save-x/data:/app/backend/data        # 必须，配置与数据库持久化
      - ./cloud-auto-save-x/media:/media                  # 可选，alist_strm_gen 插件生成 STRM 使用
      - ./cloud-auto-save-x/strm:/strm                    # 可选，项目本身生成 STRM 使用
      - ./cloud-auto-save-x/nasfile:/app/backend/data/sync/nasfile  # 可选，同步任务 Local 本地目录
```

启动：

```shell
docker compose pull   # 拉取最新镜像
docker compose up -d  # 后台启动
```

访问 Web 管理台：<http://你的服务器IP:5115>，首次进入会引导完成初始化向导。

### 4. 端口与挂载说明

| 项                               | 默认值    | 说明                |
| ------------------------------- | ------ | ----------------- |
| 管理端口                            | `5115` | Web 管理台与 302 服务端口 |
| 反代端口                            | `5225` | 媒体库反代服务端口         |
| `data` 挂载                       | 必须     | 数据库、配置、缓存全部持久化在这里 |
| `media` / `strm` / `nasfile` 挂载 | 可选     | 按实际使用的能力按需挂载      |

### 5. 常用环境变量

| 环境变量                                                                         | 默认                                                     | 备注                                 |
| ---------------------------------------------------------------------------- | ------------------------------------------------------ | ---------------------------------- |
| `PORT`                                                                       | `5115`                                                 | 管理后台/302端口                         |
| `REVERSE_PORT`                                                               | `5225`                                                 | 反代端口                               |
| `DEBUG`                                                                      | `0`                                                    | 开启调试模式，打印更多日志信息                    |
| `DB_DRIVER`                                                                  | `sqlite3`                                              | 数据库驱动，可选 `sqlite3` / `mysql`       |
| `DATABASE_URL`                                                               | 空                                                      | 完整数据库连接串，配置后优先级最高                  |
| `SQLITE_PATH`                                                                | `./data/app.db`                                        | SQLite 数据库文件路径                     |
| `APP_DATA_DIR`                                                               | `./data`                                               | 项目运行数据目录，缓存等文件会落在这里                |
| `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_CHARSET` | `127.0.0.1` / `3306` / `casx` / `root` / 空 / `utf8mb4` | MySQL 分项配置，仅 `DB_DRIVER=mysql` 时生效 |
| `DRIVE_ACCOUNT_LSDIR_SCAN_RATE_LIMIT_PER_SECOND`                             | `1.0`                                                  | 网盘目录 lsdir 扫描速率限制（每秒请求数）           |
| `DRAMA_SCHEDULE_RANDOM_DELAY_MAX_SECONDS`                                    | `300`                                                  | 追剧任务最大随机延迟时间（秒）                    |
| `DRAMA_SCHEDULE_TASK_INTERVAL_MAX_SECONDS`                                   | `30`                                                   | 追剧任务最大间隔时间（秒）                      |
| `DRAMA_RUNTIME_RETRY_MAX_ATTEMPTS`                                           | `0`                                                    | 任务运行最大重试次数，0 表示不重试                 |
| `DRAMA_RUNTIME_RETRY_BACKOFF_SECONDS`                                        | `1`                                                    | 重试延迟时间（秒）                          |
| `DRAMA_RUNTIME_RETRY_MAX_BACKOFF_SECONDS`                                    | `8`                                                    | 最大重试延迟时间（秒）                        |
| `DRAMA_RUNTIME_RETRY_JITTER_RATIO`                                           | `0.2`                                                  | 重试延迟随机化比例                          |
| `DL302_COPY_PART_CONCURRENCY`                                                | `4`                                                    | dl302 下载模式分片并发数                    |
| `DL302_COPY_PART_SIZE_MB`                                                    | `10`                                                   | dl302 下载模式单分片大小（MB）                |

### 6. 使用 MySQL（可选）

项目默认使用 SQLite，开箱即用。如需切换到 MySQL：

```env
DB_DRIVER=mysql
DATABASE_URL=mysql+pymysql://root:your_password@127.0.0.1:3306/casx?charset=utf8mb4
APP_DATA_DIR=./data
```

或使用分项配置 `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_CHARSET`。

说明：

* `DATABASE_URL` 优先级最高，配置后会覆盖分项配置。

* 首次切换前请先手动创建数据库：`CREATE DATABASE casx CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;`

* 配置完成后请先执行数据库迁移再启动服务（源码运行：`cd backend && alembic upgrade head`）。

## Web 初始化建议

首次进入 Web 管理台后，建议按下面顺序配置：

1. 跟随**初始化向导**完成管理员账号与基础设置。
2. 打开「网盘账号」，添加要使用的网盘账号（夸克、天翼、115、UC、移动等），账号探测失败的会被自动标记。
3. 打开「设置」，配置 TMDB API 密钥（智能重命名必需）与通知推送渠道，并发送测试消息验证。
4. 打开「影视发现」或直接创建「追剧任务」：填入分享链接，系统自动定位资源目录、填充剧集信息与更新星期，选择保存目录与重命名规则。
5. 打开「追剧日历 / 追剧首页」确认任务运行与更新进度。
6. 如需把网盘内容同步到 NAS 或其他网盘，打开「同步」创建同步任务，配置源端与目标端。
7. 如需媒体库 302 播放，打开「302 代理」：配置账号 `302_path`，创建 CAS 数据任务预热，再创建飞牛 / Emby 反代实例。

## 常用命令

```shell
docker compose ps        # 查看运行状态
docker compose logs -f   # 查看日志
docker compose pull && docker compose up -d   # 更新镜像
docker compose down      # 停止服务
```

备份时建议至少保留：

* `data/`：数据库、配置、任务状态、CAS 数据与缓存。

* `strm/`：生成的 STRM 文件。

## FAQ

### 追剧任务没有运行 / 没有转存新剧集？

优先检查：任务是否处于暂停状态、运行周期与运行星期配置、分享链接是否仍然有效（任务详情会给出失效原因）、账号是否被限流或探测失败。分享失效时项目会自动尝试换链修复，也可手动运行一次任务查看实时日志定位问题。

### TMDB 智能重命名不生效？

确认已在「设置」中配置 TMDB API 密钥，且容器可以访问 TMDB（必要时配置代理）。未配置 TMDB 时只能依赖正则规则与魔法匹配。

### STRM 可以生成但媒体库无法播放？

确认 STRM 中的 302 服务地址能被播放器/媒体服务器访问；确认对应网盘账号仍然有效；确认 CAS 数据已覆盖该资源；确认反代端口未被防火墙阻断。

### 302 反代应该怎样暴露？

不建议把反代端口直接暴露公网，建议通过 Web 反代服务（如 Nginx 反代加鉴权）对外提供访问。

### 为什么强烈建议不要调高运行频率？

网盘资源并非实时上传，过高频率只会增加账号风控风险并给网盘服务器造成压力。项目内置随机延迟与任务间隔机制，请保持默认或更宽松的节奏。

## 声明

本项目基于个人兴趣开发并开源，仅供学习与交流使用，不包含任何破解行为，只是对网盘官方 API 的封装与调用，所有数据均来源于各大网盘官方，本人不对网盘内容及官方 API 变更所导致的任何后果负责。

* 请确保你拥有对应账号、资源和媒体内容的合法使用权。

* 请遵守所在地区法律法规、网盘服务条款和第三方服务规则。

* 使用过程中产生的账号、数据、网络和版权风险由使用者自行承担。

## 致谢

本项目参考 [Cp0204/quark-auto-save](https://github.com/Cp0204/quark-auto-save/releases/tag/v0.8.4) 思路进行整体重构，感谢 [Cp0204](https://github.com/Cp0204) 的开源贡献。


## ❤️ 支持项目

如果觉得这个项目对你有帮助，你可以通过以下方式支持我：

1. ⭐ 给项目点个 Star，让更多的人看到
2. 📢 分享给更多有需要的朋友
3. ☕ 请作者喝杯冰阔乐~

<div align="center">
<img src="img/wechat.jpg" alt="微信" height="300">
    <img src="img/ali.jpg" alt="支付宝" height="300" style="margin-right: 20px">
</div>


## Sponsor

CDN acceleration and security protection for this project are sponsored by Tencent EdgeOne.

<a href="https://edgeone.ai/?from=github" target="_blank"><img title="Best Asian CDN, Edge, and Secure Solutions - Tencent EdgeOne" src="https://edgeone.ai/media/34fe3a45-492d-4ea4-ae5d-ea1087ca7b4b.png" width="300"></a>

## Star History

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=OzoO0/cloud-auto-save-x&type=Date&theme=dark" />
  <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=OzoO0/cloud-auto-save-x&type=Date" />
  <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=OzoO0/cloud-auto-save-x&type=Date" />
</picture>
