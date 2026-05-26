<div align="center">

![cloud-logo](img/icon.png)

# 网盘自动转存

网盘签到、自动转存、命名整理、发推送提醒、刷新媒体库一条龙，内置自动修复异常任务能力。

[![zread](https://img.shields.io/badge/Ask_AI-_.svg?style=flat&color=00b0aa&labelColor=000000&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTQuOTYxNTYgMS42MDAxSDIuMjQxNTZDMS44ODgxIDEuNjAwMSAxLjYwMTU2IDEuODg2NjQgMS42MDE1NiAyLjI0MDFWNC45NjAxQzEuNjAxNTYgNS4zMTM1NiAxLjg4ODEgNS42MDAxIDIuMjQxNTYgNS42MDAxSDQuOTYxNTZDNS4zMTUwMiA1LjYwMDEgNS42MDE1NiA1LjMxMzU2IDUuNjAxNTYgNC45NjAxVjIuMjQwMUM1LjYwMTU2IDEuODg2NjQgNS4zMTUwMiAxLjYwMDEgNC45NjE1NiAxLjYwMDFaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00Ljk2MTU2IDEwLjM5OTlIMi4yNDE1NkMxLjg4ODEgMTAuMzk5OSAxLjYwMTU2IDEwLjY4NjQgMS42MDE1NiAxMS4wMzk5VjEzLjc1OTlDMS42MDE1NiAxNC4xMTM0IDEuODg4MSAxNC4zOTk5IDIuMjQxNTYgMTQuMzk5OUg0Ljk2MTU2QzUuMzE1MDIgMTQuMzk5OSA1LjYwMTU2IDE0LjExMzQgNS42MDE1NiAxMy43NTk5VjExLjAzOTlDNS42MDE1NiAxMC42ODY0IDUuMzE1MDIgMTAuMzk5OSA0Ljk2MTU2IDEwLjM5OTlaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik0xMy43NTg0IDEuNjAwMUgxMS4wMzg0QzEwLjY4NSAxLjYwMDEgMTAuMzk4NCAxLjg4NjY0IDEwLjM5ODQgMi4yNDAxVjQuOTYwMUMxMC4zOTg0IDUuMzEzNTYgMTAuNjg1IDUuNjAwMSAxMS4wMzg0IDUuNjAwMUgxMy43NTg0QzE0LjExMTkgNS42MDAxIDE0LjM5ODQgNS4zMTM1NiAxNC4zOTg0IDQuOTYwMVYyLjI0MDFDMTQuMzk4NCAxLjg4NjY0IDE0LjExMTkgMS42MDAxIDEzLjc1ODQgMS42MDAxWiIgZmlsbD0iI2ZmZiIvPgo8cGF0aCBkPSJNNCAxMkwxMiA0TDQgMTJaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00IDEyTDEyIDQiIHN0cm9rZT0iI2ZmZiIgc3Ryb2tlLXdpZHRoPSIxLjUiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPgo8L3N2Zz4K&logoColor=ffffff)](https://zread.ai/OzoO0/cloud-auto-save-x)

[![wiki][wiki-image]][wiki-url] [![github releases][gitHub-releases-image]][github-url] [![docker pulls][docker-pulls-image]][docker-url] [![docker image size][docker-image-size-image]][docker-url]

[wiki-image]: https://img.shields.io/badge/wiki-Documents-green?logo=github
[gitHub-releases-image]: https://img.shields.io/github/v/release/OzoO0/cloud-auto-save-x?logo=github
[docker-pulls-image]: https://img.shields.io/docker/pulls/ozoo0/cloud-auto-save-x?logo=docker&&logoColor=white
[docker-image-size-image]: https://img.shields.io/docker/image-size/ozoo0/cloud-auto-save-x?logo=docker&&logoColor=white
[github-url]: https://github.com/OzoO0/cloud-auto-save-x
[docker-url]: https://hub.docker.com/r/ozoo0/cloud-auto-save-x
[wiki-url]: https://github.com/Cp0204/quark-auto-save/wiki

![run_log](img/run_log.png)

</div>

> \[!CAUTION]
> ⛔️⛔️⛔️ 注意！资源不会每时每刻更新，**严禁设定过高的定时运行频率！** 以免账号风控和给网盘服务器造成不必要的压力。雪山崩塌，每一片雪花都有责任！

> \[!NOTE]
> 开发者≠客服，开源免费≠帮你解决使用问题；本项目 Wiki 已经相对完善，遇到问题请先翻阅 Issues 和 Wiki ，请勿盲目发问。

## 项目简介

网盘自动转存（Cloud Auto Save X 简称 CASX）是一个基于 FastAPI + Vue3 的 Web 应用，提供网盘自动转存功能，可以帮助你：

- 🔄 **自动转存**：定时或自动（根据节目状态和任务进度）运行，自动转存各种网盘分享链接中的文件
- 🔄 **数据同步**：基于OpenList实现的多网盘数据同步和网盘与NAS本地的数据同步
- 📝 **智能规则**：在为手动配置重命名规则并且配置TMDB配置时，支持自动识别-重命名
- 🧩 **文件过滤**：通过过滤规则排除不需要的文件或文件夹，支持高级过滤功能
- 📊 **任务管理**：支持多任务管理，支持全局统一设置及单任务独立设置，支持任务筛选和排序
- 🔍 **资源搜索**：智能搜索网盘资源，自动识别链接可用性，自动定位到分享目录
- 🎬 **影视发现**：浏览豆瓣热门影视榜单，一键快速创建任务，智能填充配置
- 📅 **追剧日历**：追踪节目播出时间，了解转存进度，支持海报视图和日历视图
- ✅ **自动签到**：每日自动签到领空间（支持：夸克网盘、天翼云盘、百度网盘）
- 🔔 **通知推送**：支持多个通知推送渠道，及时了解转存状态
- 🔌 **插件系统**：支持多种插件扩展功能，包括媒体库局部刷新、下载任务推送、strm 文件生成等
- 🔄 **自动修复异常任务**：自动识别并修复异常任务，如分享链接失效、账号被限流等


## 核心功能

### 网盘支持情况

| 网盘名称 | 支持情况 |
| --- | --- |
| 夸克网盘 | 支持 |
| 天翼云盘 | 支持 |
| 百度网盘 | 支持 |
| 阿里云盘 | 支持 |
| 115网盘 | 支持 |
| 123网盘 | 支持 |
| UC网盘 | 支持 |
| 迅雷网盘 | 支持 |

### 自动转存

- 分享链接自动识别资源存放文件夹
- 转存任务文件智能重命名（需配置TMDB API密钥）
- 智能搜索资源并自动填充（集成 CloudSaver、PanSou，支持有效性检查、失效过滤）
- 支持自动修复异常任务（如分享链接失效、账号被限流等）
- 支持自动解压压缩包（仅限夸克高级会员）
- 支持一次性转存任务


## 部署

### Docker 部署

Docker 部署提供 WebUI 进行管理配置，部署命令：

```shell
docker run -d \
  --name cloud-auto-save-x \
  -p 5115:5115 \ # 映射端口，:前的可以改，即部署后访问的端口，:后的不可改
  -v ./cloud-auto-save-x/data:/app/backend/data \ # 必须，配置持久化
  -v ./cloud-auto-save-x/media:/media \ # 可选，模块alist_strm_gen生成strm使用
  -v ./cloud-auto-save-x/nasfile:/app/backend/data/sync/nasfile \ # 可选，用于同步任务Local使用，可与网盘数据同步
  --network bridge \
  --restart unless-stopped \
  ozoo0/cloud-auto-save-x:latest
  # registry.cn-hangzhou.aliyuncs.com/ozoo0/cloud-auto-save-x:latest # 国内镜像地址
```

docker-compose.yml

```yaml
name: cloud-auto-save-x
services:
  cloud-auto-save-x:
    image: ozoo0/cloud-auto-save-x:latest
    container_name: cloud-auto-save-x
    network_mode: bridge
    ports:
      - 5115:5115
    restart: unless-stopped
    volumes:
      - ./cloud-auto-save-x/data:/app/backend/data
      - ./cloud-auto-save-x/media:/media
      - ./cloud-auto-save-x/nasfile:/app/backend/data/sync/nasfile
```

管理地址：<http://yourhost:5115>

| 环境变量             | 默认         | 备注                           |
| ---------------- | ---------- | ---------------------------- |
| `PORT`           | `5115`     | 管理后台端口                       |
| `DEBUG`          | `0`        | 开启调试模式，打印更多日志信息 |


<details open>
<summary>WebUI 预览</summary>

![dashboard](img/96fd01ae-dc64-42f2-992c-4faf6daab0bb.png)

![discover](img/57b6b274-2b26-44df-9a28-f53e8def0582.png)

![calendar](img/76083cce-5c3e-406c-87fa-51ae8a31bcd2.png)

![calendar-year](img/8cdb803a-4107-49ac-84b4-7a215a527a5f.png)

![account](img/48c4b746-5d82-419d-8054-c3bf8514bbc5.png)

</details>

## 使用说明

### 正则处理示例

| pattern                        | replace                 | 效果                                                 |
| ------------------------------ | ----------------------- | -------------------------------------------------- |
| `.*`                           | <br />                  | 无脑转存所有文件，不整理                                       |
| `\.mp4$`                       | <br />                  | 转存所有 `.mp4` 后缀的文件                                  |
| `^【电影TT】花好月圆(\d+)\.(mp4\|mkv)` | `\1.\2`                 | 【电影TT】花好月圆01.mp4 → 01.mp4【电影TT】花好月圆02.mkv → 02.mkv |
| `^(\d+)\.mp4`                  | `S02E\1.mp4`            | 01.mp4 → S02E01.mp402.mp4 → S02E02.mp4             |
| `TV_REGEX`                          | <br />                  | [魔法匹配](#魔法匹配)剧集文件                                  |
| `^(\d+)\.mp4`                  | `{TASKNAME}.S02E\1.mp4` | 01.mp4 → 任务名.S02E01.mp4                            |

**默认规则**：在已配置TMDB后，留空则增加兜底智能匹配。

更多正则使用说明：[正则处理教程](https://github.com/ozoo0/cloud-auto-save-x/wiki/正则处理教程)

> \[!TIP]
>
> **魔法匹配和魔法变量**：在正则处理中，我们定义了一些“魔法匹配”模式，如果 表达式 的值以 $ 开头且 替换式 留空，程序将自动使用预设的正则表达式进行匹配和替换。
>
> 更多说明请看[魔法匹配和魔法变量](https://github.com/ozoo0/cloud-auto-save-x/wiki/魔法匹配和魔法变量)


### 刷新媒体库

在有新转存时，可触发完成相应功能，如自动刷新媒体库、生成 .strm 文件等。配置指南：[插件配置](https://github.com/ozoo0/cloud-auto-save-x/wiki/插件配置)

媒体库模块以插件的方式的集成，如果你有兴趣请参考[插件开发指南](https://github.com/ozoo0/cloud-auto-save-x/tree/main/plugins)。

### 更多使用技巧

请参考 Wiki ：[使用技巧集锦](https://github.com/ozoo0/cloud-auto-save-x/wiki/使用技巧集锦)


## 声明

本项目基于个人兴趣开发并开源，仅供学习与交流使用，不包含任何破解行为，只是对网盘官方 API 的封装与调用，所有数据均来源于各大网盘官方，本人不对网盘内容及官方 API 变更所导致的任何后果负责。

## 致谢

本项目参考 [Cp0204/quark-auto-save](https://github.com/Cp0204/quark-auto-save/releases/tag/v0.8.4) 思路进行整体重构，感谢 [Cp0204](https://github.com/Cp0204) 的开源贡献。

## Sponsor

CDN acceleration and security protection for this project are sponsored by Tencent EdgeOne.

<a href="https://edgeone.ai/?from=github" target="_blank"><img title="Best Asian CDN, Edge, and Secure Solutions - Tencent EdgeOne" src="https://edgeone.ai/media/34fe3a45-492d-4ea4-ae5d-ea1087ca7b4b.png" width="300"></a>
