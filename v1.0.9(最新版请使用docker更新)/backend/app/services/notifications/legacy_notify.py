from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import smtplib
import threading
import time
import urllib.parse
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

import requests

_send_lock = threading.Lock()

logger = logging.getLogger(__name__)


DEFAULT_PUSH_CONFIG = {
    "HITOKOTO": False,
    "BARK_PUSH": "",
    "BARK_ARCHIVE": "",
    "BARK_GROUP": "",
    "BARK_SOUND": "",
    "BARK_ICON": "",
    "BARK_LEVEL": "",
    "BARK_URL": "",
    "DD_BOT_SECRET": "",
    "DD_BOT_TOKEN": "",
    "FSKEY": "",
    "GOBOT_URL": "",
    "GOBOT_QQ": "",
    "GOBOT_TOKEN": "",
    "GOTIFY_URL": "",
    "GOTIFY_TOKEN": "",
    "GOTIFY_PRIORITY": 0,
    "IGOT_PUSH_KEY": "",
    "PUSH_KEY": "",
    "DEER_KEY": "",
    "DEER_URL": "",
    "CHAT_URL": "",
    "CHAT_TOKEN": "",
    "PUSH_PLUS_TOKEN": "",
    "PUSH_PLUS_USER": "",
    "PUSH_PLUS_TEMPLATE": "html",
    "PUSH_PLUS_CHANNEL": "wechat",
    "PUSH_PLUS_WEBHOOK": "",
    "PUSH_PLUS_CALLBACKURL": "",
    "PUSH_PLUS_TO": "",
    "WE_PLUS_BOT_TOKEN": "",
    "WE_PLUS_BOT_RECEIVER": "",
    "WE_PLUS_BOT_VERSION": "pro",
    "QMSG_KEY": "",
    "QMSG_TYPE": "",
    "QYWX_ORIGIN": "",
    "QYWX_AM": "",
    "QYWX_KEY": "",
    "TG_BOT_TOKEN": "",
    "TG_USER_ID": "",
    "TG_API_HOST": "",
    "TG_PROXY_AUTH": "",
    "TG_PROXY_HOST": "",
    "TG_PROXY_PORT": "",
    "AIBOTK_KEY": "",
    "AIBOTK_TYPE": "",
    "AIBOTK_NAME": "",
    "SMTP_SERVER": "",
    "SMTP_SSL": "false",
    "SMTP_EMAIL": "",
    "SMTP_PASSWORD": "",
    "SMTP_NAME": "",
    "SMTP_EMAIL_TO": "",
    "SMTP_NAME_TO": "",
    "PUSHME_KEY": "",
    "PUSHME_URL": "",
    "CHRONOCAT_QQ": "",
    "CHRONOCAT_TOKEN": "",
    "CHRONOCAT_URL": "",
    "WEBHOOK_URL": "",
    "WEBHOOK_BODY": "",
    "WEBHOOK_HEADERS": "",
    "WEBHOOK_METHOD": "",
    "WEBHOOK_CONTENT_TYPE": "",
    "NTFY_URL": "",
    "NTFY_TOPIC": "",
    "NTFY_PRIORITY": "3",
    "NTFY_TOKEN": "",
    "NTFY_USERNAME": "",
    "NTFY_PASSWORD": "",
    "NTFY_ACTIONS": "",
    "WXPUSHER_APP_TOKEN": "",
    "WXPUSHER_TOPIC_IDS": "",
    "WXPUSHER_UIDS": "",
    "DODO_BOTTOKEN": "",
    "DODO_BOTID": "",
    "DODO_LANDSOURCEID": "",
    "DODO_SOURCEID": "",
}

push_config = dict(DEFAULT_PUSH_CONFIG)

for k in push_config:
    if os.getenv(k):
        v = os.getenv(k)
        push_config[k] = v


def _result(channel: str, ok: bool, error: str | None = None) -> dict[str, object]:
    return {"channel": channel, "ok": ok, "error": error}


def bark(title: str, content: str) -> dict[str, object]:
    if not push_config.get("BARK_PUSH"):
        return _result("bark", False, "not_configured")

    if push_config.get("BARK_PUSH").startswith("http"):
        url = f"{push_config.get('BARK_PUSH')}"
    else:
        url = f"https://api.day.app/{push_config.get('BARK_PUSH')}"

    bark_params = {
        "BARK_ARCHIVE": "isArchive",
        "BARK_GROUP": "group",
        "BARK_SOUND": "sound",
        "BARK_ICON": "icon",
        "BARK_LEVEL": "level",
        "BARK_URL": "url",
    }
    data = {
        "title": title,
        "body": content,
    }
    for pair in filter(
        lambda pairs: pairs[0].startswith("BARK_")
        and pairs[0] != "BARK_PUSH"
        and pairs[1]
        and bark_params.get(pairs[0]),
        push_config.items(),
    ):
        data[bark_params.get(pair[0])] = pair[1]
    headers = {"Content-Type": "application/json;charset=utf-8"}
    try:
        response = requests.post(url=url, data=json.dumps(data), headers=headers, timeout=15).json()
    except Exception as exc:
        return _result("bark", False, str(exc))
    ok = response.get("code") == 200
    return _result("bark", ok, None if ok else json.dumps(response, ensure_ascii=False))


def console(title: str, content: str) -> dict[str, object]:
    if str(push_config.get("CONSOLE")).lower() != "false":
        logger.info("%s\n\n%s", title, content)
        return _result("console", True, None)
    return _result("console", False, "disabled")


def dingding_bot(title: str, content: str) -> dict[str, object]:
    if not push_config.get("DD_BOT_SECRET") or not push_config.get("DD_BOT_TOKEN"):
        return _result("dingding", False, "not_configured")

    timestamp = str(round(time.time() * 1000))
    secret_enc = push_config.get("DD_BOT_SECRET").encode("utf-8")
    string_to_sign = "{}\n{}".format(timestamp, push_config.get("DD_BOT_SECRET"))
    string_to_sign_enc = string_to_sign.encode("utf-8")
    hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    url = f"https://oapi.dingtalk.com/robot/send?access_token={push_config.get('DD_BOT_TOKEN')}&timestamp={timestamp}&sign={sign}"
    headers = {"Content-Type": "application/json;charset=utf-8"}
    data = {"msgtype": "text", "text": {"content": f"{title}\n\n{content}"}}
    try:
        response = requests.post(url=url, data=json.dumps(data), headers=headers, timeout=15).json()
    except Exception as exc:
        return _result("dingding", False, str(exc))
    ok = response.get("errcode") == 0
    return _result("dingding", ok, None if ok else json.dumps(response, ensure_ascii=False))


def feishu_bot(title: str, content: str) -> dict[str, object]:
    if not push_config.get("FSKEY"):
        return _result("feishu", False, "not_configured")

    url = f"https://open.feishu.cn/open-apis/bot/v2/hook/{push_config.get('FSKEY')}"
    headers = {"Content-Type": "application/json"}
    data = {"msg_type": "text", "content": {"text": f"{title}\n\n{content}"}}
    try:
        response = requests.post(url=url, data=json.dumps(data), headers=headers, timeout=15).json()
    except Exception as exc:
        return _result("feishu", False, str(exc))
    ok = response.get("StatusCode") == 0 or response.get("code") == 0
    return _result("feishu", ok, None if ok else json.dumps(response, ensure_ascii=False))


def go_cqhttp(title: str, content: str) -> dict[str, object]:
    if not push_config.get("GOBOT_URL") or not push_config.get("GOBOT_QQ"):
        return _result("gocqhttp", False, "not_configured")

    url = push_config.get("GOBOT_URL")
    data = {"message": f"{title}\n\n{content}"}
    headers = {"Content-Type": "application/json"}
    if push_config.get("GOBOT_TOKEN"):
        headers["Authorization"] = f"Bearer {push_config.get('GOBOT_TOKEN')}"

    if "/send_private_msg" in url:
        data["user_id"] = push_config.get("GOBOT_QQ")
    elif "/send_group_msg" in url:
        data["group_id"] = push_config.get("GOBOT_QQ")
    else:
        return _result("gocqhttp", False, "invalid_url")

    try:
        response = requests.post(url=url, data=json.dumps(data), headers=headers, timeout=15).json()
    except Exception as exc:
        return _result("gocqhttp", False, str(exc))
    ok = response.get("status") == "ok"
    return _result("gocqhttp", ok, None if ok else json.dumps(response, ensure_ascii=False))


def gotify(title: str, content: str) -> dict[str, object]:
    if not push_config.get("GOTIFY_URL") or not push_config.get("GOTIFY_TOKEN"):
        return _result("gotify", False, "not_configured")

    url = f"{push_config.get('GOTIFY_URL')}/message?token={push_config.get('GOTIFY_TOKEN')}"
    headers = {"Content-Type": "application/json"}
    data = {"title": title, "message": content, "priority": push_config.get("GOTIFY_PRIORITY")}
    try:
        response = requests.post(url=url, data=json.dumps(data), headers=headers, timeout=15).json()
    except Exception as exc:
        return _result("gotify", False, str(exc))
    ok = bool(response.get("id"))
    return _result("gotify", ok, None if ok else json.dumps(response, ensure_ascii=False))


def iGot(title: str, content: str) -> dict[str, object]:
    if not push_config.get("IGOT_PUSH_KEY"):
        return _result("igot", False, "not_configured")

    url = "https://push.hellyw.com/" + push_config.get("IGOT_PUSH_KEY")
    headers = {"Content-Type": "application/json"}
    data = {"title": title, "content": content}
    try:
        response = requests.post(url=url, data=json.dumps(data), headers=headers, timeout=15).json()
    except Exception as exc:
        return _result("igot", False, str(exc))
    ok = response.get("ret") == 0
    return _result("igot", ok, None if ok else json.dumps(response, ensure_ascii=False))


def serverJ(title: str, content: str) -> dict[str, object]:
    if not push_config.get("PUSH_KEY"):
        return _result("serverj", False, "not_configured")

    url = "https://sctapi.ftqq.com/" + push_config.get("PUSH_KEY") + ".send"
    data = {"title": title, "desp": content}
    try:
        response = requests.post(url=url, data=data, timeout=15).json()
    except Exception as exc:
        return _result("serverj", False, str(exc))
    ok = response.get("code") == 0
    return _result("serverj", ok, None if ok else json.dumps(response, ensure_ascii=False))


def pushdeer(title: str, content: str) -> dict[str, object]:
    if not push_config.get("DEER_KEY"):
        return _result("pushdeer", False, "not_configured")

    url = push_config.get("DEER_URL") or "https://api2.pushdeer.com/message/push"
    data = {"pushkey": push_config.get("DEER_KEY"), "text": title, "desp": content, "type": "markdown"}
    try:
        response = requests.post(url=url, data=data, timeout=15).json()
    except Exception as exc:
        return _result("pushdeer", False, str(exc))
    ok = response.get("code") == 0
    return _result("pushdeer", ok, None if ok else json.dumps(response, ensure_ascii=False))


def chat(title: str, content: str) -> dict[str, object]:
    if not push_config.get("CHAT_URL") or not push_config.get("CHAT_TOKEN"):
        return _result("synology_chat", False, "not_configured")

    url = push_config.get("CHAT_URL")
    headers = {"Content-Type": "application/json"}
    data = {"token": push_config.get("CHAT_TOKEN"), "text": f"{title}\n{content}"}
    try:
        response = requests.post(url=url, data=json.dumps(data), headers=headers, timeout=15).json()
    except Exception as exc:
        return _result("synology_chat", False, str(exc))
    ok = bool(response.get("success"))
    return _result("synology_chat", ok, None if ok else json.dumps(response, ensure_ascii=False))


def pushplus_bot(title: str, content: str) -> dict[str, object]:
    if not push_config.get("PUSH_PLUS_TOKEN"):
        return _result("pushplus", False, "not_configured")

    url = "http://www.pushplus.plus/send"
    data = {
        "token": push_config.get("PUSH_PLUS_TOKEN"),
        "title": title,
        "content": content,
        "template": push_config.get("PUSH_PLUS_TEMPLATE"),
        "channel": push_config.get("PUSH_PLUS_CHANNEL"),
        "webhook": push_config.get("PUSH_PLUS_WEBHOOK"),
        "callbackUrl": push_config.get("PUSH_PLUS_CALLBACKURL"),
        "to": push_config.get("PUSH_PLUS_TO"),
    }
    if push_config.get("PUSH_PLUS_USER"):
        data["topic"] = push_config.get("PUSH_PLUS_USER")
    try:
        response = requests.post(url=url, data=json.dumps(data), headers={"Content-Type": "application/json"}, timeout=15).json()
    except Exception as exc:
        return _result("pushplus", False, str(exc))
    ok = response.get("code") == 200
    return _result("pushplus", ok, None if ok else json.dumps(response, ensure_ascii=False))


def weplus_bot(title: str, content: str) -> dict[str, object]:
    if not push_config.get("WE_PLUS_BOT_TOKEN"):
        return _result("weplus", False, "not_configured")

    url = "https://www.wechatplus.com.cn/api/message/send"
    data = {
        "token": push_config.get("WE_PLUS_BOT_TOKEN"),
        "receiver": push_config.get("WE_PLUS_BOT_RECEIVER"),
        "msg": f"{title}\n\n{content}",
    }
    try:
        response = requests.post(url=url, data=data, timeout=15).json()
    except Exception as exc:
        return _result("weplus", False, str(exc))
    ok = response.get("code") == 0
    return _result("weplus", ok, None if ok else json.dumps(response, ensure_ascii=False))


def qmsg_bot(title: str, content: str) -> dict[str, object]:
    if not push_config.get("QMSG_KEY") or not push_config.get("QMSG_TYPE"):
        return _result("qmsg", False, "not_configured")

    url = f"https://qmsg.zendee.cn/{push_config.get('QMSG_TYPE')}/{push_config.get('QMSG_KEY')}"
    data = {"msg": f"{title}\n\n{content}"}
    try:
        response = requests.post(url=url, data=data, timeout=15).json()
    except Exception as exc:
        return _result("qmsg", False, str(exc))
    ok = response.get("code") == 0
    return _result("qmsg", ok, None if ok else json.dumps(response, ensure_ascii=False))


def wecom_app(title: str, content: str) -> dict[str, object]:
    if not push_config.get("QYWX_AM"):
        return _result("wecom_app", False, "not_configured")

    origin = push_config.get("QYWX_ORIGIN") or "https://qyapi.weixin.qq.com"
    parts = [(item or "").strip() for item in str(push_config.get("QYWX_AM") or "").split(",")]
    if len(parts) != 4 or not all(parts):
        return _result("wecom_app", False, "invalid_QYWX_AM")
    corpid, corpsecret, agentid, touser = parts
    token_url = f"{origin}/cgi-bin/gettoken?corpid={corpid}&corpsecret={corpsecret}"
    try:
        token_resp = requests.get(token_url, timeout=15).json()
    except Exception as exc:
        return _result("wecom_app", False, str(exc))
    access_token = token_resp.get("access_token")
    if not access_token:
        return _result("wecom_app", False, json.dumps(token_resp, ensure_ascii=False))

    send_url = f"{origin}/cgi-bin/message/send?access_token={access_token}"
    data = {
        "touser": touser,
        "msgtype": "text",
        "agentid": agentid,
        "text": {"content": f"{title}\n\n{content}"},
        "safe": 0,
    }
    response = requests.post(send_url, data=json.dumps(data), timeout=15).json()
    ok = response.get("errcode") == 0
    return _result("wecom_app", ok, None if ok else json.dumps(response, ensure_ascii=False))


def wecom_bot(title: str, content: str) -> dict[str, object]:
    if not push_config.get("QYWX_KEY"):
        return _result("wecom_bot", False, "not_configured")

    url = push_config.get("QYWX_KEY")
    headers = {"Content-Type": "application/json"}
    data = {"msgtype": "text", "text": {"content": f"{title}\n\n{content}"}}
    try:
        response = requests.post(url=url, data=json.dumps(data), headers=headers, timeout=15).json()
    except Exception as exc:
        return _result("wecom_bot", False, str(exc))
    ok = response.get("errcode") == 0
    return _result("wecom_bot", ok, None if ok else json.dumps(response, ensure_ascii=False))


def telegram_bot(title: str, content: str) -> dict[str, object]:
    if not push_config.get("TG_BOT_TOKEN") or not push_config.get("TG_USER_ID"):
        return _result("telegram", False, "not_configured")

    tg_api_host = push_config.get("TG_API_HOST") or "https://api.telegram.org"
    token = push_config.get("TG_BOT_TOKEN")
    chat_id = push_config.get("TG_USER_ID")
    proxy_host = push_config.get("TG_PROXY_HOST")
    proxy_port = push_config.get("TG_PROXY_PORT")
    proxy_auth = push_config.get("TG_PROXY_AUTH")

    if proxy_host and proxy_port:
        proxy_url = f"http://{proxy_host}:{proxy_port}"
        if proxy_auth:
            proxy_url = f"http://{proxy_auth}@{proxy_host}:{proxy_port}"
        proxies = {"http": proxy_url, "https": proxy_url}
    else:
        proxies = None

    url = f"{tg_api_host}/bot{token}/sendMessage"
    data = {"chat_id": chat_id, "text": f"{title}\n\n{content}"}
    try:
        response = requests.post(url=url, data=data, proxies=proxies, timeout=15).json()
    except Exception as exc:
        return _result("telegram", False, str(exc))
    ok = bool(response.get("ok"))
    return _result("telegram", ok, None if ok else json.dumps(response, ensure_ascii=False))


def aibotk(title: str, content: str) -> dict[str, object]:
    if not push_config.get("AIBOTK_KEY") or not push_config.get("AIBOTK_TYPE") or not push_config.get("AIBOTK_NAME"):
        return _result("aibotk", False, "not_configured")

    url = "http://wechat.aibotk.com/openapi/v1/sendMsg"
    headers = {"Content-Type": "application/json"}
    data = {
        "apiKey": push_config.get("AIBOTK_KEY"),
        "type": push_config.get("AIBOTK_TYPE"),
        "name": push_config.get("AIBOTK_NAME"),
        "msg": f"{title}\n\n{content}",
    }
    try:
        response = requests.post(url=url, data=json.dumps(data), headers=headers, timeout=15).json()
    except Exception as exc:
        return _result("aibotk", False, str(exc))
    ok = response.get("code") == 0
    return _result("aibotk", ok, None if ok else json.dumps(response, ensure_ascii=False))


def smtp(title: str, content: str) -> dict[str, object]:
    if (
        not push_config.get("SMTP_SERVER")
        or not push_config.get("SMTP_SSL")
        or not push_config.get("SMTP_EMAIL")
        or not push_config.get("SMTP_PASSWORD")
        or not push_config.get("SMTP_NAME")
    ):
        return _result("smtp", False, "not_configured")

    smtp_server = push_config.get("SMTP_SERVER")
    smtp_ssl = str(push_config.get("SMTP_SSL")).lower() == "true"
    smtp_email = push_config.get("SMTP_EMAIL")
    smtp_password = push_config.get("SMTP_PASSWORD")
    smtp_name = push_config.get("SMTP_NAME")
    smtp_email_to = push_config.get("SMTP_EMAIL_TO") or smtp_email
    smtp_name_to = push_config.get("SMTP_NAME_TO") or smtp_name

    msg = MIMEText(content, "plain", "utf-8")
    msg["From"] = formataddr((Header(smtp_name, "utf-8").encode(), smtp_email))
    msg["To"] = formataddr((Header(smtp_name_to, "utf-8").encode(), smtp_email_to))
    msg["Subject"] = Header(title, "utf-8").encode()

    try:
        if smtp_ssl:
            server = smtplib.SMTP_SSL(smtp_server, timeout=15)
        else:
            server = smtplib.SMTP(smtp_server, timeout=15)
        server.login(smtp_email, smtp_password)
        server.sendmail(smtp_email, smtp_email_to.split(","), msg.as_string())
        server.quit()
        return _result("smtp", True, None)
    except Exception as e:
        return _result("smtp", False, str(e))


def pushme(title: str, content: str) -> dict[str, object]:
    if not push_config.get("PUSHME_KEY"):
        return _result("pushme", False, "not_configured")

    url = push_config.get("PUSHME_URL") or "https://push.i-i.me"
    data = {
        "push_key": push_config.get("PUSHME_KEY"),
        "title": title,
        "content": content,
        "date": push_config.get("date"),
        "type": push_config.get("type"),
    }
    try:
        response = requests.get(url=url, params=data, timeout=15).json()
    except Exception as exc:
        return _result("pushme", False, str(exc))
    ok = response.get("code") == 0
    return _result("pushme", ok, None if ok else json.dumps(response, ensure_ascii=False))


def chronocat(title: str, content: str) -> dict[str, object]:
    if not push_config.get("CHRONOCAT_URL") or not push_config.get("CHRONOCAT_QQ") or not push_config.get("CHRONOCAT_TOKEN"):
        return _result("chronocat", False, "not_configured")

    url = push_config.get("CHRONOCAT_URL")
    headers = {"Content-Type": "application/json"}
    data = {
        "token": push_config.get("CHRONOCAT_TOKEN"),
        "qq": push_config.get("CHRONOCAT_QQ"),
        "text": f"{title}\n\n{content}",
    }
    try:
        response = requests.post(url=url, data=json.dumps(data), headers=headers, timeout=15).json()
    except Exception as exc:
        return _result("chronocat", False, str(exc))
    ok = response.get("code") == 0
    return _result("chronocat", ok, None if ok else json.dumps(response, ensure_ascii=False))


def dodo_bot(title: str, content: str) -> dict[str, object]:
    if (
        not push_config.get("DODO_BOTTOKEN")
        or not push_config.get("DODO_BOTID")
        or not push_config.get("DODO_LANDSOURCEID")
        or not push_config.get("DODO_SOURCEID")
    ):
        return _result("dodo", False, "not_configured")

    url = "https://botopen.imdodo.com/api/v2/chat/sendMessage"
    headers = {"Content-Type": "application/json;charset=utf-8"}
    data = {
        "botId": push_config.get("DODO_BOTID"),
        "dodoSourceId": push_config.get("DODO_SOURCEID"),
        "landSourceId": push_config.get("DODO_LANDSOURCEID"),
        "messageType": 1,
        "messageBody": {"content": f"{title}\n\n{content}"},
    }
    try:
        response = requests.post(url=url, data=json.dumps(data), headers=headers, timeout=15).json()
    except Exception as exc:
        return _result("dodo", False, str(exc))
    ok = response.get("status") == 0
    return _result("dodo", ok, None if ok else json.dumps(response, ensure_ascii=False))


def custom_notify(title: str, content: str) -> dict[str, object]:
    if not push_config.get("WEBHOOK_URL") or not push_config.get("WEBHOOK_METHOD"):
        return _result("webhook", False, "not_configured")

    WEBHOOK_URL = push_config.get("WEBHOOK_URL")
    WEBHOOK_BODY = push_config.get("WEBHOOK_BODY") or ""
    WEBHOOK_HEADERS = push_config.get("WEBHOOK_HEADERS") or ""
    WEBHOOK_METHOD = push_config.get("WEBHOOK_METHOD")
    WEBHOOK_CONTENT_TYPE = push_config.get("WEBHOOK_CONTENT_TYPE") or "application/json"

    if ("$title" not in WEBHOOK_URL) and ("$title" not in WEBHOOK_BODY):
        return _result("webhook", False, "missing_$title")

    headers = {"Content-Type": WEBHOOK_CONTENT_TYPE}
    if WEBHOOK_HEADERS:
        try:
            headers.update(json.loads(WEBHOOK_HEADERS))
        except Exception as exc:
            return _result("webhook", False, f"invalid_headers_json: {exc}")

    body = WEBHOOK_BODY.replace("$title", title).replace("$content", content)
    formatted_url = WEBHOOK_URL.replace("$title", urllib.parse.quote_plus(title)).replace(
        "$content", urllib.parse.quote_plus(content)
    )
    try:
        response = requests.request(method=WEBHOOK_METHOD, url=formatted_url, headers=headers, timeout=15, data=body)
    except Exception as exc:
        return _result("webhook", False, str(exc))
    ok = response.status_code == 200
    return _result("webhook", ok, None if ok else f"{response.status_code} {response.text}")


def ntfy(title: str, content: str) -> dict[str, object]:
    if not push_config.get("NTFY_TOPIC"):
        return _result("ntfy", False, "not_configured")

    base_url = push_config.get("NTFY_URL") or "https://ntfy.sh"
    topic = push_config.get("NTFY_TOPIC")
    url = f"{base_url}/{topic}"
    headers = {
        "Title": Header(title, "utf-8").encode(),
        "Priority": str(push_config.get("NTFY_PRIORITY") or "3"),
    }
    if push_config.get("NTFY_TOKEN"):
        headers["Authorization"] = f"Bearer {push_config.get('NTFY_TOKEN')}"
    if push_config.get("NTFY_USERNAME") and push_config.get("NTFY_PASSWORD"):
        auth = (push_config.get("NTFY_USERNAME"), push_config.get("NTFY_PASSWORD"))
    else:
        auth = None
    if push_config.get("NTFY_ACTIONS"):
        headers["Actions"] = push_config.get("NTFY_ACTIONS")

    try:
        response = requests.post(url=url, data=content.encode("utf-8"), headers=headers, auth=auth, timeout=15)
    except Exception as exc:
        return _result("ntfy", False, str(exc))
    ok = response.status_code == 200
    return _result("ntfy", ok, None if ok else f"{response.status_code} {response.text}")


def wxpusher_bot(title: str, content: str) -> dict[str, object]:
    if not push_config.get("WXPUSHER_APP_TOKEN"):
        return _result("wxpusher", False, "not_configured")

    url = "https://wxpusher.zjiecode.com/api/send/message"
    payload = {
        "appToken": push_config.get("WXPUSHER_APP_TOKEN"),
        "content": f"{title}\n\n{content}",
        "contentType": 1,
    }
    topic_ids = str(push_config.get("WXPUSHER_TOPIC_IDS") or "").strip()
    uids = str(push_config.get("WXPUSHER_UIDS") or "").strip()
    if topic_ids:
        payload["topicIds"] = [int(x) for x in topic_ids.split(";") if str(x).strip().isdigit()]
    if uids:
        payload["uids"] = [x for x in uids.split(";") if str(x).strip()]

    try:
        response = requests.post(url=url, json=payload, timeout=15).json()
    except Exception as exc:
        return _result("wxpusher", False, str(exc))
    ok = response.get("code") == 1000
    return _result("wxpusher", ok, None if ok else json.dumps(response, ensure_ascii=False))


def one() -> str:
    url = "https://v1.hitokoto.cn/"
    res = requests.get(url, timeout=15).json()
    return res["hitokoto"] + "    ----" + res["from"]


def add_notify_function():
    notify_function = []
    if push_config.get("BARK_PUSH"):
        notify_function.append(bark)
    if push_config.get("DD_BOT_TOKEN") and push_config.get("DD_BOT_SECRET"):
        notify_function.append(dingding_bot)
    if push_config.get("FSKEY"):
        notify_function.append(feishu_bot)
    if push_config.get("GOBOT_URL") and push_config.get("GOBOT_QQ"):
        notify_function.append(go_cqhttp)
    if push_config.get("GOTIFY_URL") and push_config.get("GOTIFY_TOKEN"):
        notify_function.append(gotify)
    if push_config.get("IGOT_PUSH_KEY"):
        notify_function.append(iGot)
    if push_config.get("PUSH_KEY"):
        notify_function.append(serverJ)
    if push_config.get("DEER_KEY"):
        notify_function.append(pushdeer)
    if push_config.get("CHAT_URL") and push_config.get("CHAT_TOKEN"):
        notify_function.append(chat)
    if push_config.get("PUSH_PLUS_TOKEN"):
        notify_function.append(pushplus_bot)
    if push_config.get("WE_PLUS_BOT_TOKEN"):
        notify_function.append(weplus_bot)
    if push_config.get("QMSG_KEY") and push_config.get("QMSG_TYPE"):
        notify_function.append(qmsg_bot)
    if push_config.get("QYWX_AM"):
        notify_function.append(wecom_app)
    if push_config.get("QYWX_KEY"):
        notify_function.append(wecom_bot)
    if push_config.get("TG_BOT_TOKEN") and push_config.get("TG_USER_ID"):
        notify_function.append(telegram_bot)
    if push_config.get("AIBOTK_KEY") and push_config.get("AIBOTK_TYPE") and push_config.get("AIBOTK_NAME"):
        notify_function.append(aibotk)
    if (
        push_config.get("SMTP_SERVER")
        and push_config.get("SMTP_SSL")
        and push_config.get("SMTP_EMAIL")
        and push_config.get("SMTP_PASSWORD")
        and push_config.get("SMTP_NAME")
    ):
        notify_function.append(smtp)
    if push_config.get("PUSHME_KEY"):
        notify_function.append(pushme)
    if push_config.get("CHRONOCAT_URL") and push_config.get("CHRONOCAT_QQ") and push_config.get("CHRONOCAT_TOKEN"):
        notify_function.append(chronocat)
    if (
        push_config.get("DODO_BOTTOKEN")
        and push_config.get("DODO_BOTID")
        and push_config.get("DODO_LANDSOURCEID")
        and push_config.get("DODO_SOURCEID")
    ):
        notify_function.append(dodo_bot)
    if push_config.get("WEBHOOK_URL") and push_config.get("WEBHOOK_METHOD"):
        notify_function.append(custom_notify)
    if push_config.get("NTFY_TOPIC"):
        notify_function.append(ntfy)
    if push_config.get("WXPUSHER_APP_TOKEN") and (push_config.get("WXPUSHER_TOPIC_IDS") or push_config.get("WXPUSHER_UIDS")):
        notify_function.append(wxpusher_bot)
    return notify_function


def _get_channel_enabled_map() -> dict[str, bool]:
    raw = push_config.get("__channel_enabled")
    if not isinstance(raw, dict):
        return {}
    result: dict[str, bool] = {}
    for key, value in raw.items():
        if isinstance(key, str):
            result[key] = bool(value)
    return result


def _func_channel_id(name: str) -> str:
    return {
        "bark": "bark",
        "dingding_bot": "dingding",
        "feishu_bot": "feishu",
        "go_cqhttp": "gocqhttp",
        "gotify": "gotify",
        "iGot": "igot",
        "serverJ": "serverj",
        "pushdeer": "pushdeer",
        "chat": "synology_chat",
        "pushplus_bot": "pushplus",
        "weplus_bot": "weplus",
        "qmsg_bot": "qmsg",
        "wecom_app": "wecom_app",
        "wecom_bot": "wecom_bot",
        "telegram_bot": "telegram",
        "aibotk": "aibotk",
        "smtp": "smtp",
        "pushme": "pushme",
        "chronocat": "chronocat",
        "dodo_bot": "dodo",
        "custom_notify": "webhook",
        "ntfy": "ntfy",
        "wxpusher_bot": "wxpusher",
    }.get(name, name)


def send(title: str, content: str, ignore_default_config: bool = False, channels: list[str] | None = None, **kwargs) -> list[dict[str, object]]:
    with _send_lock:
        global push_config
        snapshot = dict(push_config)
        try:
            if kwargs:
                if ignore_default_config:
                    push_config = kwargs
                else:
                    push_config.update(kwargs)

            if not content:
                return []

            skipTitle = os.getenv("SKIP_PUSH_TITLE")
            if skipTitle:
                if title in re.split("\n", skipTitle):
                    return []

            hitokoto = push_config.get("HITOKOTO")
            if hitokoto and str(hitokoto).lower() != "false":
                content += "\n\n" + one()

            enabled_map = _get_channel_enabled_map()
            filter_set = set(channels or [])
            funcs = []
            for mode in add_notify_function():
                channel_id = _func_channel_id(mode.__name__)
                if filter_set and channel_id not in filter_set:
                    continue
                if channel_id in enabled_map and not enabled_map[channel_id]:
                    continue
                funcs.append((channel_id, mode))

            results: list[dict[str, object]] = []
            mutex = threading.Lock()

            def _runner(channel_id: str, func):
                try:
                    res = func(title, content)
                    if isinstance(res, dict):
                        if "channel" not in res:
                            res["channel"] = channel_id
                        with mutex:
                            results.append(res)
                    else:
                        with mutex:
                            results.append(_result(channel_id, True, None))
                except Exception as exc:
                    with mutex:
                        results.append(_result(channel_id, False, str(exc)))

            ts = [threading.Thread(target=_runner, args=(channel_id, mode), name=mode.__name__) for channel_id, mode in funcs]
            [t.start() for t in ts]
            [t.join() for t in ts]
            return results
        finally:
            push_config = snapshot
