# -*- coding: utf-8 -*-
import base64
import binascii
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse, quote, unquote
from xml.etree import ElementTree as ET

import requests

from app.extensions.adapters.base_adapter import BaseCloudDriveAdapter
from app.extensions.adapters.drive_auth import DriveAuthRequired

logger = logging.getLogger(__name__)
_global_config_saver = None


def set_config_saver(config_path: Any):
    global _global_config_saver
    if callable(config_path):
        _global_config_saver = config_path


class Cloud189CaptchaRequired(Exception):
    def __init__(self, captcha_token: str, image_bytes: bytes, context: Dict[str, str]):
        super().__init__("captcha required")
        self.captcha_token = captcha_token
        self.image_bytes = image_bytes
        self.context = context


class Cloud189SecondValidRequired(Exception):
    def __init__(self, message: str, context: Dict[str, Any]):
        super().__init__(message)
        self.context = context


class Cloud189Adapter(BaseCloudDriveAdapter):
    DRIVE_TYPE = "cloud189"
    DRIVE_NAME = "天翼云盘"
    CONFIG_FORMAT = "kv"
    default_config = {
        "username": "",
        "password": "",
        "ssoncookie": "",
        "protocol": "pc",
        "name": "",
        "debug": False,
    }
    config_fields = [
        {
            "key": "username",
            "label": "用户名",
            "description": "天翼云盘登录用户名。",
            "input_type": "text",
            "required": False,
            "secret": False,
            "placeholder": "",
        },
        {
            "key": "password",
            "label": "密码",
            "description": "天翼云盘登录密码；如已填写 ssoncookie 可留空。",
            "input_type": "password",
            "required": False,
            "secret": True,
            "placeholder": "",
        },
        {
            "key": "ssoncookie",
            "label": "SSO Cookie",
            "description": "已获取到的登录态；支持 ssoncookie 或 SSON。",
            "input_type": "textarea",
            "required": False,
            "secret": True,
            "placeholder": "ssoncookie",
        },
        {
            "key": "protocol",
            "label": "协议",
            "description": "请求协议，默认 pc。",
            "input_type": "text",
            "required": False,
            "secret": False,
            "placeholder": "pc",
        },
        {
            "key": "name",
            "label": "账户别名",
            "description": "可选，用于区分多个天翼云盘账户。",
            "input_type": "text",
            "required": False,
            "secret": False,
            "placeholder": "",
        },
        {
            "key": "debug",
            "label": "调试模式",
            "description": "开启后输出更多调试日志。",
            "input_type": "switch",
            "required": False,
            "secret": False,
            "placeholder": "",
        },
    ]

    HOST_URL = "https://cloud.189.cn"
    AUTH_URL = "https://open.e.189.cn/api/logbox/oauth2/"

    PC_APP_ID = 8025431004
    PC_CLIENT_TYPE = 10020
    PC_RETURN_URL = "https://cloud.189.cn/main.action"

    RSA_KEY = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDY7mpaUysvgQkbp0iIn2ezoUyh
i1zPFn0HCXloLFWT7uoNkqtrphpQ/63LEcPz1VYzmDuDIf3iGxQKzeoHTiVMSmW6
FlhDeqVOG094hFJvZeK4OzA6HVwzwnEW5vIZ7d+u61RV1bsFxmB68+8JXs3ycGcE
4anY+YzZJcyOcEGKVQIDAQAB
-----END PUBLIC KEY-----"""

    _B64MAP = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    _BI_RM = list("0123456789abcdefghijklmnopqrstuvwxyz")

    WEB_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        cookie: str = "",
        index: int = 0,
        config: dict | None = None,
        account_name: str = "",
        no_login: bool = False,
    ):
        super().__init__(cookie, index, config=config, no_login=no_login)
        self._cookie_kv = {str(k): v for k, v in self.config.items()}
        self._user_name = self._cookie_kv.get("username") or self._cookie_kv.get("mobile") or ""
        self._password = self._cookie_kv.get("password") or self._cookie_kv.get("passWord") or ""
        self._ssoncookie = self._cookie_kv.get("ssoncookie") or self._cookie_kv.get("SSON") or ""
        self._protocol = (self._cookie_kv.get("protocol") or "pc").strip().lower()
        self._account_name = self._cookie_kv.get("name") or account_name or f"cloud189用户{self.index}"
        self._debug = (
            str(self._cookie_kv.get("debug", "")).strip().lower() in ("1", "true", "yes", "on")
            or os.environ.get("CLOUD_AUTO_SAVE_CLOUD189_DEBUG", "").strip() == "1"
        )

        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self.WEB_USER_AGENT,
                "Referer": "https://open.e.189.cn/",
                "Accept": "application/json;charset=UTF-8",
            }
        )
        if self._debug:
            logger.setLevel(logging.DEBUG)

        self._last_share_code = ""
        self._auth_state: Dict[str, Any] | None = None

    def _request(
        self,
        method: str,
        url: str,
        *,
        raise_status: bool = True,
        timeout: int | float = 15,
        allow_redirects: bool | None = None,
        **kwargs,
    ) -> requests.Response:
        if allow_redirects is not None:
            kwargs["allow_redirects"] = allow_redirects
        self._throttle_request()
        
        resp = self._session.request(method=method, url=url, timeout=timeout, **kwargs)
        if raise_status:
            resp.raise_for_status()
        return resp

    def _request_json(self, method: str, url: str, **kwargs) -> Any:
        resp = self._request(method, url, **kwargs)
        try:
            return resp.json()
        except Exception:
            raise RuntimeError((resp.text or "").strip()[:200] or "响应解析失败")

    def _request_text(self, method: str, url: str, **kwargs) -> str:
        resp = self._request(method, url, **kwargs)
        return resp.text or ""

    def _mask_mobile(self, mobile: str) -> str:
        s = str(mobile or "").strip()
        if len(s) < 7:
            return s
        return f"{s[:3]}****{s[-4:]}"

    def _tail(self, value: str, n: int = 6) -> str:
        s = str(value or "").strip()
        if not s:
            return ""
        return s[-n:] if len(s) > n else s

    def _mask_passcode(self, value: str) -> str:
        s = str(value or "").strip()
        if not s:
            return ""
        if len(s) <= 1:
            return "*"
        return f"{s[0]}***"

    def _snippet(self, text: str, n: int = 200) -> str:
        s = str(text or "").replace("\n", " ").replace("\r", " ").strip()
        if len(s) <= n:
            return s
        return s[:n]

    def _finalize_login(self) -> Any:
        info = self._get_logined_infos() or {}
        cookies = self._session.cookies.get_dict()
        sson = cookies.get("SSON") or ""
        if sson:
            self._cookie_kv["ssoncookie"] = sson
            self._cookie_kv["SSON"] = sson
            self._ssoncookie = sson
        for k in ("OPENINFO", "DEVICEID", "GUID", "LT", "JSESSIONID", "pageOp", "GRAYNUMBER"):
            v = cookies.get(k) or ""
            if v:
                self._cookie_kv[k] = v
        if sson:
            self._cookie_kv["cookiejar"] = self._export_cookiejar_b64()
            self.cookie = self._cookie_kv_to_str(self._cookie_kv)
            self._persist_cookie()
        self.is_active = True
        self.nickname = (info or {}).get("nickname") or self._account_name
        self._auth_state = None
        return info

    def submit_captcha(self, captcha_code: str) -> Any:
        if not self._auth_state or self._auth_state.get("method") != "captcha":
            raise RuntimeError("验证码会话已失效，请重新获取")
        login_params = dict(self._auth_state.get("context") or {})
        j = self._login_submit(self._user_name, self._password, captcha_code or "", login_params)
        if isinstance(j, dict) and int(j.get("result", 1)) == 0:
            to_url = j.get("toUrl") or ""
            if to_url:
                self._session.get(to_url, timeout=15)
            return self._finalize_login()
        if isinstance(j, dict) and int(j.get("result", 1)) in (-133, -134):
            result = int(j.get("result", 1))
            msg = j.get("msg") or "需要二次设备校验"
            ctx = dict(login_params)
            ctx["second_mode"] = "sms" if result == -133 else "psw"
            for k in ("mobile", "showName", "apToken", "isSystem", "romaSecondAuth"):
                if k in j:
                    ctx[k] = j.get(k)
            self._auth_state = {"method": "sms", "context": ctx}
            raise DriveAuthRequired(
                method="sms",
                message=msg,
                payload={
                    "mobile": self._mask_mobile(str(ctx.get("mobile") or "")),
                    "show_name": str(ctx.get("showName") or ""),
                    "second_mode": str(ctx.get("second_mode") or ""),
                },
                adapter=self,
            )
        msg = (j or {}).get("msg") if isinstance(j, dict) else ""
        raise RuntimeError(msg or "验证码校验失败")

    def send_sms(self) -> Dict[str, Any]:
        if not self._auth_state or self._auth_state.get("method") != "sms":
            raise RuntimeError("短信会话已失效，请重新获取")
        login_params = dict(self._auth_state.get("context") or {})
        if str(login_params.get("second_mode") or "").lower() != "sms":
            raise RuntimeError("当前账号未开启短信验证")
        mobile = str(login_params.get("mobile") or "")
        return self._second_valid_send_sms(login_params, mobile)

    def submit_sms(self, sms_code: str) -> Any:
        if not self._auth_state or self._auth_state.get("method") != "sms":
            raise RuntimeError("短信会话已失效，请重新获取")
        login_params = dict(self._auth_state.get("context") or {})
        if str(login_params.get("second_mode") or "").lower() != "sms":
            raise RuntimeError("当前账号未开启短信验证")
        mobile = str(login_params.get("mobile") or "")
        resp = self._second_valid_submit_sms(login_params, mobile, self._user_name, sms_code or "")
        if isinstance(resp, dict) and int(resp.get("result", 1)) == 0:
            to_url = resp.get("toUrl") or ""
            if to_url:
                self._session.get(to_url, timeout=15)
            return self._finalize_login()
        msg = (resp or {}).get("msg") if isinstance(resp, dict) else ""
        raise RuntimeError(msg or "短信校验失败")

    def _parse_cookie_kv(self, cookie: str) -> Dict[str, str]:
        result: Dict[str, str] = {}
        if not cookie:
            return result
        for kv in cookie.split(";"):
            kv = kv.strip()
            if not kv or "=" not in kv:
                continue
            k, v = kv.split("=", 1)
            k = k.strip()
            v = v.strip()
            if k:
                result[k] = v
        return result

    def _cookie_kv_to_str(self, kv: Dict[str, str]) -> str:
        preferred = ["name", "username", "password", "ssoncookie", "cookiejar", "debug", "protocol"]
        used = set()
        parts: List[str] = []
        for k in preferred:
            if k in kv and kv[k] != "":
                parts.append(f"{k}={kv[k]}")
                used.add(k)
        for k, v in kv.items():
            if k in used:
                continue
            if v == "":
                continue
            parts.append(f"{k}={v}")
        return ";".join(parts)

    def _export_cookiejar_b64(self) -> str:
        try:
            d = self._session.cookies.get_dict()
            raw = json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            return base64.urlsafe_b64encode(raw).decode("utf-8")
        except Exception:
            return ""

    def _import_cookiejar_b64(self, b64: str):
        if not b64:
            return
        try:
            raw = base64.urlsafe_b64decode(b64.encode("utf-8"))
            items = json.loads(raw.decode("utf-8"))
        except Exception:
            return
        if not isinstance(items, dict):
            return
        try:
            self._session.cookies.update({str(k): str(v) for k, v in items.items() if k and v})
        except Exception:
            pass

    def _persist_cookie(self):
        if callable(_global_config_saver):
            try:
                _global_config_saver(self.cookie)
            except Exception as e:
                logger.warning(f"[cloud189] persist cookie failed: {e}")

    def _parse_time_to_ts(self, v: Any) -> int:
        if v is None:
            return 0
        if isinstance(v, (int, float)):
            return int(v)
        s = str(v).strip()
        if not s:
            return 0
        if s.isdigit():
            try:
                n = int(s)
                return n if n > 1e12 else n
            except Exception:
                pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d %H:%M:%S"):
            try:
                return int(datetime.strptime(s[:19], fmt).timestamp())
            except Exception:
                continue
        try:
            return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
        except Exception:
            return 0

    def _rsa_encrypt(self, text: str) -> str:
        try:
            import rsa
        except Exception as e:
            raise RuntimeError("缺少依赖 rsa，请先安装 requirements.txt") from e
        pub = rsa.PublicKey.load_pkcs1_openssl_pem(self.RSA_KEY.encode("utf-8"))
        enc = rsa.encrypt(text.encode("utf-8"), pub)
        b64 = base64.b64encode(enc).decode("utf-8")
        return self._b64tohex(b64)

    def _rsa_encode_dynamic(self, j_rsakey: str, text: str) -> str:
        try:
            import rsa
        except Exception as e:
            raise RuntimeError("缺少依赖 rsa，请先安装 requirements.txt") from e
        rsa_key = f"-----BEGIN PUBLIC KEY-----\n{j_rsakey}\n-----END PUBLIC KEY-----"
        pub = rsa.PublicKey.load_pkcs1_openssl_pem(rsa_key.encode("utf-8"))
        enc = rsa.encrypt(text.encode("utf-8"), pub)
        b64 = base64.b64encode(enc).decode("utf-8")
        return self._b64tohex(b64)

    def _encrypt_for_login(self, login_params: Dict[str, Any], text: str) -> str:
        key = str(login_params.get("pubKey") or login_params.get("j_rsakey") or login_params.get("j_rsaKey") or "")
        pre = str(login_params.get("pre") or "")
        if key:
            enc = self._rsa_encode_dynamic(key, text)
        else:
            enc = self._rsa_encrypt(text)
        if pre:
            return pre + enc
        return "{RSA}" + enc

    def _int2char(self, a: int) -> str:
        return self._BI_RM[a]

    def _b64tohex(self, a: str) -> str:
        d = ""
        e = 0
        for i in range(len(a)):
            if list(a)[i] != "=":
                v = self._B64MAP.index(list(a)[i])
                if 0 == e:
                    e = 1
                    d += self._int2char(v >> 2)
                    c = 3 & v
                elif 1 == e:
                    e = 2
                    d += self._int2char(c << 2 | v >> 4)
                    c = 15 & v
                elif 2 == e:
                    e = 3
                    d += self._int2char(c)
                    d += self._int2char(v >> 2)
                    c = 3 & v
                else:
                    e = 0
                    d += self._int2char(c << 2 | v >> 4)
                    d += self._int2char(15 & v)
        if e == 1:
            d += self._int2char(c << 2)
        return d

    def _get_login_url_params(self) -> Dict[str, Any]:
        url = f"{self.HOST_URL}/api/portal/loginUrl.action"
        params = {"pageId": 1, "redirectURL": f"{self.HOST_URL}/main.action"}
        resp = self._request("GET", url, params=params, timeout=15, allow_redirects=True)

        parsed = urlparse(resp.url)
        qs = parse_qs(parsed.query or "")
        lt = (qs.get("lt") or [""])[0] or ""
        req_id = (qs.get("reqId") or [""])[0] or ""
        app_id = (qs.get("appId") or [""])[0] or ""
        if resp.url.rstrip("/") in (f"{self.HOST_URL}/web/main", f"{self.HOST_URL}/web/main/"):
            raise RuntimeError("当前会话疑似已登录但状态异常，请清空 Cookie 后重试登录")
        if not lt or not req_id or not app_id:
            raise RuntimeError("页面已过期，刷新页面后重试")

        headers = {
            "lt": lt,
            "reqId": req_id,
            "reqid": req_id,
            "origin": "https://open.e.189.cn",
            "referer": resp.url,
        }

        conf_url = f"{self.HOST_URL.replace('cloud.189.cn', 'open.e.189.cn')}/api/logbox/oauth2/appConf.do"
        conf = self._request_json(
            "POST",
            conf_url,
            headers=headers,
            data={"version": "2.0", "appKey": app_id},
            timeout=15,
        )
        if not isinstance(conf, dict) or str(conf.get("result")) != "0":
            raise RuntimeError(conf.get("msg") or "页面已过期，刷新页面后重试")
        data = conf.get("data") or {}
        if not isinstance(data, dict) or not data:
            raise RuntimeError("页面已过期，刷新页面后重试")

        encrypt_url = f"{self.HOST_URL.replace('cloud.189.cn', 'open.e.189.cn')}/api/logbox/config/encryptConf.do"
        enc = self._request_json("POST", encrypt_url, headers=headers, data={"appId": app_id}, timeout=15)
        if not isinstance(enc, dict) or int(enc.get("result", 1)) != 0:
            raise RuntimeError("页面已过期，刷新页面后重试")
        enc_data = enc.get("data") or {}
        if not isinstance(enc_data, dict) or not enc_data:
            raise RuntimeError("页面已过期，刷新页面后重试")

        out: Dict[str, Any] = dict(data)
        out.update(
            {
                "lt": lt,
                "reqId": req_id,
                "appKey": app_id,
                "pre": str(enc_data.get("pre") or ""),
                "pubKey": str(enc_data.get("pubKey") or ""),
                "dynamicCheck": "FALSE",
                "cb_SaveName": str(data.get("cb_SaveName") or "3"),
                "state": str(data.get("state") or ""),
            }
        )
        return out

    def _need_captcha(self, login_params: Dict[str, Any], username: str) -> bool:
        url = f"{self.AUTH_URL}needcaptcha.do"
        enc_user = self._encrypt_for_login(login_params, username)
        post_data = {
            "accountType": str(login_params.get("accountType") or "01"),
            "userName": enc_user,
            "appKey": str(login_params.get("appKey") or "cloud"),
        }
        lt = str(login_params.get("lt") or "")
        req_id = str(login_params.get("reqId") or "")
        resp = self._session.post(
            url,
            data=post_data,
            headers={"lt": lt, "REQID": req_id, "reqId": req_id},
            timeout=15,
        )
        resp.raise_for_status()
        try:
            v = resp.json()
        except Exception:
            v = (resp.text or "").strip()
        try:
            return int(v) == 1
        except Exception:
            return str(v).strip() == "1"

    def _get_captcha_image(self, login_params: Dict[str, Any]) -> Tuple[str, str, bytes]:
        lt = str(login_params.get("lt") or "")
        req_id = str(login_params.get("reqId") or "")
        captcha_token = str(login_params.get("captchaToken") or "")
        if captcha_token:
            img_url = f"{self.AUTH_URL}picCaptcha.do"
            img = self._request("GET", img_url, params={"token": captcha_token}, timeout=30)
            return captcha_token, "", img.content or b""

        app_id = str(login_params.get("appKey") or login_params.get("appId") or "cloud")
        uuid_url = f"{self.AUTH_URL}getUUID.do"
        j = self._request_json(
            "POST",
            uuid_url,
            data={"appId": app_id},
            headers={"lt": lt, "reqId": req_id},
            timeout=30,
        )
        if not isinstance(j, dict) or int(j.get("result", 1)) != 0:
            raise RuntimeError("获取验证码失败，请刷新重试")
        token = str(j.get("encryuuid") or "")
        encode_uuid = str(j.get("encodeuuid") or "")
        if not token or not encode_uuid:
            raise RuntimeError("获取验证码失败，请刷新重试")

        img_url = f"{self.AUTH_URL}image.do"
        img = self._request(
            "GET",
            img_url,
            params={"uuid": encode_uuid, "REQID": req_id},
            headers={"lt": lt, "reqId": req_id},
            timeout=30,
        )
        return token, encode_uuid, img.content or b""

    def _login_submit(
        self,
        username: str,
        password: str,
        captcha_code: str,
        login_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        url = f"{self.AUTH_URL}loginSubmit.do"
        lt = str(login_params.get("lt") or "")
        req_id = str(login_params.get("reqId") or "")
        if lt:
            self._session.headers.update({"lt": lt, "reqId": req_id})

        return_url = str(login_params.get("returnUrl") or "")
        param_id = str(login_params.get("paramId") or "")
        if not return_url or not param_id:
            raise RuntimeError("页面已过期，刷新页面后重试")

        enc_user = self._encrypt_for_login(login_params, username)
        enc_pwd = self._encrypt_for_login(login_params, password)

        captcha_type = str(login_params.get("captchaType") or ("1" if captcha_code else "0"))
        data = {
            "version": "v2.0",
            "appKey": str(login_params.get("appKey") or "cloud"),
            "accountType": str(login_params.get("accountType") or "01"),
            "userName": enc_user,
            "epd": enc_pwd,
            "captchaType": captcha_type,
            "validateCode": captcha_code or str(login_params.get("validateCode") or ""),
            "smsValidateCode": captcha_code or str(login_params.get("smsValidateCode") or ""),
            "captchaToken": str(login_params.get("captchaToken") or ""),
            "returnUrl": return_url,
            "mailSuffix": str(login_params.get("mailSuffix") or "@189.cn"),
            "dynamicCheck": str(login_params.get("dynamicCheck") or "FALSE"),
            "clientType": str(login_params.get("clientType") or "1"),
            "cb_SaveName": str(login_params.get("cb_SaveName") or "3"),
            "isOauth2": str(login_params.get("isOauth2") or "true").lower(),
            "state": str(login_params.get("state") or ""),
            "paramId": param_id,
        }
        headers = {"lt": lt, "reqId": req_id, "REQID": req_id}
        if self._protocol != "web":
            headers.update(
                {
                    "Referer": "https://open.e.189.cn/api/logbox/oauth2/unifyAccountLogin.do",
                    "Cookie": f"LT={lt}",
                    "X-Requested-With": "XMLHttpRequest",
                }
            )
        return self._request_json("POST", url, data=data, headers=headers, timeout=15)

    def _login_by_username_password(self, username: str, password: str, captcha_code: str = "") -> bool:
        try:
            self._session.cookies.clear()
        except Exception:
            pass
        try:
            self._session.headers.pop("Cookie", None)
        except Exception:
            pass
        login_params = self._get_login_url_params()
        need = self._need_captcha(login_params, username)
        if need and not captcha_code:
            captcha_token, _, img = self._get_captcha_image(login_params)
            ctx = dict(login_params)
            ctx["captchaToken"] = captcha_token
            ctx["captchaType"] = "1"
            raise Cloud189CaptchaRequired(captcha_token, img, ctx)
        j = self._login_submit(username, password, captcha_code, login_params)
        if isinstance(j, dict) and int(j.get("result", 1)) == 0:
            to_url = j.get("toUrl") or ""
            if to_url:
                self._session.get(to_url, timeout=15)
            return True
        if isinstance(j, dict) and int(j.get("result", 1)) in (-133, -134):
            result = int(j.get("result", 1))
            msg = j.get("msg") or "需要二次设备校验"
            ctx = dict(login_params)
            ctx["second_mode"] = "sms" if result == -133 else "psw"
            for k in ("mobile", "showName", "apToken", "isSystem", "romaSecondAuth"):
                if k in j:
                    ctx[k] = j.get(k)
            raise Cloud189SecondValidRequired(msg, ctx)
        msg = (j or {}).get("msg") if isinstance(j, dict) else ""
        raise RuntimeError(msg or "登录失败")

    def _second_valid_submit_password(self, login_params: Dict[str, Any], ap_token: str, username: str, password: str) -> Dict[str, Any]:
        url = f"{self.AUTH_URL}loginSubmit.do"
        lt = str(login_params.get("lt") or "")
        req_id = str(login_params.get("reqId") or "")
        key = str(login_params.get("pubKey") or login_params.get("j_rsakey") or login_params.get("j_rsaKey") or "")
        if not (lt and req_id and key and ap_token):
            raise RuntimeError("二次校验会话已失效，请重新获取")

        enc_user = self._encrypt_for_login(login_params, username)
        enc_pwd = self._encrypt_for_login(login_params, password)

        return_url = str(login_params.get("returnUrl") or "")
        param_id = str(login_params.get("paramId") or "")
        if not return_url or not param_id:
            raise RuntimeError("二次校验会话已失效，请重新获取")

        data = {
            "version": "v2.0",
            "apToken": ap_token,
            "appKey": str(login_params.get("appKey") or "cloud"),
            "pageKey": str(login_params.get("pageKey") or "normal"),
            "accountType": str(login_params.get("accountType") or "01"),
            "userName": enc_user,
            "epd": enc_pwd,
            "captchaType": "0",
            "validateCode": "",
            "smsValidateCode": "",
            "captchaToken": "",
            "returnUrl": return_url,
            "mailSuffix": str(login_params.get("mailSuffix") or "@189.cn"),
            "dynamicCheck": str(login_params.get("dynamicCheck") or "FALSE"),
            "clientType": str(login_params.get("clientType") or self.PC_CLIENT_TYPE),
            "cb_SaveName": str(login_params.get("cb_SaveName") or "3"),
            "isOauth2": str(login_params.get("isOauth2") or "false").lower(),
            "state": str(login_params.get("state") or ""),
            "paramId": param_id,
        }
        resp = self._session.post(
            url,
            data=data,
            headers={
                "lt": lt,
                "reqId": req_id,
                "REQID": req_id,
                "Referer": "https://open.e.189.cn/api/logbox/oauth2/unifyAccountLogin.do",
                "Cookie": f"LT={lt}",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def _second_valid_send_sms(self, login_params: Dict[str, Any], mobile: str) -> Dict[str, Any]:
        url = f"{self.AUTH_URL}sendSmsCodeForSecondAuth.do"
        lt = str(login_params.get("lt") or "")
        req_id = str(login_params.get("reqId") or "")
        app_key = str(login_params.get("appKey") or self.PC_APP_ID)
        if not (lt and req_id and mobile):
            raise RuntimeError("二次校验会话已失效，请重新登录")
        resp = self._session.post(
            url,
            data={"mobile": mobile, "appKey": app_key},
            headers={"lt": lt, "reqId": req_id},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()

    def _second_valid_submit_sms(self, login_params: Dict[str, Any], mobile: str, username: str, sms_code: str) -> Dict[str, Any]:
        url = f"{self.AUTH_URL}submitForSecondAuth.do"
        lt = str(login_params.get("lt") or "")
        req_id = str(login_params.get("reqId") or "")
        key = str(login_params.get("pubKey") or login_params.get("j_rsakey") or login_params.get("j_rsaKey") or "")
        if not (lt and req_id and key and mobile and sms_code):
            raise RuntimeError("二次校验会话已失效，请重新登录")

        enc_user = self._encrypt_for_login(login_params, username)
        enc_code = self._encrypt_for_login(login_params, sms_code)

        return_url = str(login_params.get("returnUrl") or "")
        param_id = str(login_params.get("paramId") or "")
        if not return_url or not param_id:
            raise RuntimeError("二次校验会话已失效，请重新登录")

        data = {
            "mobile": mobile,
            "appKey": str(login_params.get("appKey") or self.PC_APP_ID),
            "userName": enc_user,
            "epd": enc_code,
            "accountType": str(login_params.get("accountType") or "02"),
            "returnUrl": return_url,
            "isOauth2": str(login_params.get("isOauth2") or "false").lower(),
            "cb_SaveName": str(login_params.get("cb_SaveName") or "3"),
            "state": str(login_params.get("state") or ""),
            "paramId": param_id,
        }
        resp = self._session.post(
            url,
            data=data,
            headers={
                "lt": lt,
                "reqId": req_id,
                "Referer": "https://open.e.189.cn/api/logbox/oauth2/unifyAccountLogin.do",
                "Cookie": f"LT={lt}",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()

    def _apply_saved_cookies(self):
        reserved = {"name", "username", "userName", "password", "passWord", "ssoncookie", "cookiejar", "debug", "protocol"}
        cookiejar = (self._cookie_kv.get("cookiejar") or "").strip()
        if cookiejar:
            self._import_cookiejar_b64(cookiejar)

        for k, v in self._cookie_kv.items():
            if not k or k in reserved:
                continue
            if not v:
                continue
            try:
                self._session.cookies.set(k, v)
            except Exception:
                pass

        if self._ssoncookie:
            try:
                self._session.cookies.set("SSON", self._ssoncookie)
            except Exception:
                pass
        try:
            d = self._session.cookies.get_dict()
            cookie_str = "; ".join([f"{k}={v}" for k, v in d.items() if k and v])
            if cookie_str:
                self._session.headers["Cookie"] = cookie_str
        except Exception:
            pass

    def _check_cookie_login_ok(self) -> bool:
        url = f"{self.HOST_URL}/v2/getUserLevelInfo.action"
        resp = self._session.get(url, timeout=15)
        if resp.status_code != 200:
            return False
        text = resp.text or ""
        if "InvalidSessionKey" in text:
            return False
        return True

    def _login_by_cookie(self) -> bool:
        self._apply_saved_cookies()
        return self._check_cookie_login_ok()

    def _get_logined_infos(self) -> Optional[Dict[str, Any]]:
        url = f"{self.HOST_URL}/v2/getLoginedInfos.action"
        resp = self._session.get(url, timeout=15)
        if resp.status_code != 200:
            return None
        try:
            j = resp.json()
        except Exception:
            return None
        if not isinstance(j, dict) or "userId" not in j:
            return None
        return j

    def _get_user_size_info(self) -> Dict[str, Any]:
        url = f"{self.HOST_URL}/api/portal/getUserSizeInfo.action"
        params = {
            "noCache": str(time.time()),
            "needClassification": "true",
        }
        j = self._request_json("GET", url, params=params, timeout=15)
        if not isinstance(j, dict):
            return {}
        if j.get("res_code", 1) != 0:
            return {}
        return j
        
    def get_account_config(self) -> Dict[str, Any]:
        """获取天翼云盘账户配置/容量信息"""
        size_info: Dict[str, Any] = {}
        account_info: Dict[str, Any] = {}
        
        try:
            self._ensure_login()
            account_info = self._get_logined_infos() or {}
            size_info = self._get_user_size_info() or {}
        except Exception as e:
            account_info = {}
            size_info = {}
        
        nickname = (
            account_info.get("nickname")
            or self._account_name
            or self.nickname
            or self._user_name
            or f"cloud189用户{self.index}"
        )
        if nickname:
            self.nickname = nickname

        username = size_info.get("account") or self._user_name or nickname

        cloud_capacity = size_info.get("cloudCapacityInfo") if isinstance(size_info, dict) else None

        return {
            "drive_type": self.DRIVE_TYPE,
            "drive_name": self.DRIVE_NAME,
            "nickname": nickname,
            "username": username,
            "used_space": int(cloud_capacity.get("usedSize", 0)) if isinstance(cloud_capacity, dict) else None,
            "total_space": int(cloud_capacity.get("totalSize", 0)) if isinstance(cloud_capacity, dict) else None,
            "member_type": "",
            "member_status": {},
            "raw": {
                "account_info": account_info or None,
                "member_info": size_info or None,
            },
        }

    def sign_in(self) -> Dict[str, Any]:
        self._ensure_login()
        url = "https://m.cloud.189.cn/mkt/userSign.action"
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
            "Referer": "https://m.cloud.189.cn/",
            "Accept": "application/json, text/plain, */*",
        }
        resp = self._request("GET", url, params={"noCache": str(time.time())}, headers=headers, timeout=20)
        try:
            data = resp.json()
        except Exception:
            raise RuntimeError((resp.text or "").strip()[:200] or "签到失败")
        if not isinstance(data, dict):
            raise RuntimeError("签到失败")
        is_sign = bool(data.get("isSign"))
        bonus = data.get("netdiskBonus")
        bonus_value = 0
        try:
            bonus_value = int(bonus) if bonus is not None else 0
        except Exception:
            bonus_value = 0
        message = "今日已签到" if is_sign else f"签到成功，获得 {bonus_value}M 空间"
        return {"supported": True, "ok": True, "message": message, "reward": bonus_value, "data": data}

    def init(self) -> Any:
        logger.info(f"[cloud189] adapter init: account={self._account_name}")
        if self._cookie_kv.get("cookiejar") or self._ssoncookie or self._cookie_kv.get("SSON") or self._cookie_kv.get("DEVICEID") or self._cookie_kv.get("OPENINFO"):
            try:
                if self._login_by_cookie():
                    info = self._get_logined_infos() or {}
                    self.is_active = True
                    self.nickname = info.get("nickname") or self._account_name
                    return info
            except Exception as e:
                logger.warning(f"[cloud189] cookie login failed: {e}")

        if not self._user_name or not self._password:
            return False

        try:
            self._login_by_username_password(self._user_name, self._password, "")
        except Cloud189CaptchaRequired as e:
            self._auth_state = {"method": "captcha", "context": dict(e.context or {})}
            raise DriveAuthRequired(
                method="captcha",
                message="cloud189 登录需要验证码",
                payload={"image_base64": base64.b64encode(e.image_bytes or b"").decode("utf-8")},
                adapter=self,
            )
        except Cloud189SecondValidRequired as e:
            ctx = dict(e.context or {})
            self._auth_state = {"method": "sms", "context": ctx}
            raise DriveAuthRequired(
                method="sms",
                message=str(e) or "需要二次设备校验",
                payload={
                    "mobile": self._mask_mobile(str(ctx.get("mobile") or "")),
                    "show_name": str(ctx.get("showName") or ""),
                    "second_mode": str(ctx.get("second_mode") or ""),
                },
                adapter=self,
            )

        return self._finalize_login()

    def _ensure_login(self):
        if getattr(self, "is_active", False):
            return
        self.init()
        if not getattr(self, "is_active", False):
            raise RuntimeError("未登录或 Cookie 无效")

    def _get_cookie_value(self, name: str, domain_hint: str = "") -> str:
        try:
            for c in self._session.cookies:
                if c.name != name:
                    continue
                if domain_hint and domain_hint not in (c.domain or ""):
                    continue
                if c.value:
                    return c.value
        except Exception:
            pass
        try:
            return self._session.cookies.get(name) or ""
        except Exception:
            return ""

    def extract_url(self, url: str) -> Tuple[Optional[str], str, Any, List]:
        if not url:
            return None, "", 0, []
        raw = str(url).strip()
        normalized = raw.replace("？", "?").replace("＆", "&")
        compact = re.sub(r"\s+", "", normalized)
        try:
            compact = unquote(compact)
        except Exception:
            pass

        passcode = ""
        access_patterns = [
            r"[（(]访问码[：:]\s*([a-zA-Z0-9]{4})[)）]",
            r"[（(]提取码[：:]\s*([a-zA-Z0-9]{4})[)）]",
            r"访问码[：:]\s*([a-zA-Z0-9]{4})",
            r"提取码[：:]\s*([a-zA-Z0-9]{4})",
            r"[（(]([a-zA-Z0-9]{4})[)）]",
        ]
        for pat in access_patterns:
            m = re.search(pat, compact)
            if not m:
                continue
            passcode = (m.group(1) or "").strip()
            compact = compact.replace(m.group(0), "", 1)
            break

        extracted_url = ""
        url_patterns = [
            r"(https?://cloud\.189\.cn/web/share\?[^\s]+)",
            r"(https?://cloud\.189\.cn/t/[a-zA-Z0-9]+[^\s]*)",
            r"(https?://h5\.cloud\.189\.cn/share\.html#/t/[a-zA-Z0-9]+[^\s]*)",
            r"(https?://[^/]+/web/share\?[^\s]+)",
            r"(https?://[^/]+/t/[a-zA-Z0-9]+[^\s]*)",
            r"(https?://[^/]+/share\.html[^\s]*)",
            r"(https?://content\.21cn\.com[^\s]+)",
        ]
        for pat in url_patterns:
            m = re.search(pat, compact)
            if m:
                extracted_url = m.group(1)
                break
        if not extracted_url:
            m = re.search(r"(https?://[^\s]+)", normalized)
            if m:
                extracted_url = m.group(1)
        if not extracted_url:
            extracted_url = raw

        parsed = urlparse(extracted_url)
        qs = parse_qs(parsed.query or "")
        if not passcode:
            passcode = (qs.get("pwd") or qs.get("passcode") or qs.get("accessCode") or [""])[0] or ""

        code = ""
        if "content.21cn.com" in (parsed.netloc or ""):
            try:
                frag = parsed.fragment or ""
                if "?" in frag:
                    frag_qs = parse_qs(frag.split("?", 1)[1])
                    code = (frag_qs.get("shareCode") or [""])[0] or ""
            except Exception:
                code = ""
        if not code and (parsed.path or "") == "/web/share":
            code = (qs.get("code") or [""])[0] or ""
        if not code and (parsed.path or "").startswith("/t/"):
            code = (parsed.path or "").split("/")[-1] or ""
        if not code and (parsed.fragment or "") and "/t/" in (parsed.fragment or ""):
            code = (parsed.fragment or "").split("/")[-1] or ""
        if not code and "share.html" in (parsed.path or "") and (parsed.fragment or ""):
            parts = (parsed.fragment or "").split("/")
            code = parts[-1] if parts else ""

        self._last_share_code = code or ""
        pdir_fid = "0"
        frag = (parsed.fragment or "").strip()
        if frag:
            m = re.search(r"(?:^|/)list/share/([^/?#]+)", frag)
            if m:
                pdir_fid = str(m.group(1) or "0")
        return code or None, passcode, pdir_fid, []

    def _fetch_share_page(self, code: str) -> str:
        url = f"{self.HOST_URL}/web/share"
        return self._request_text("GET", url, params={"code": code}, timeout=15, allow_redirects=True)

    def _parse_share_page(self, html: str) -> Dict[str, str]:
        if "您访问的页面地址有误" in html:
            return {"invalid": "1"}
        if "window.fileName" in html:
            m = re.search(r'class="shareId" value="(\w+?)"', html)
            share_id = m.group(1) if m else ""
            return {"is_file": "1", "shareId": share_id}
        m = re.search(r"_shareId = '(\w+?)';", html)
        share_id = m.group(1) if m else ""
        m = re.search(r"_verifyCode = '(\w+?)';", html)
        verify_code = m.group(1) if m else ""
        return {"is_file": "0", "shareId": share_id, "verifyCode": verify_code}

    def _xml_text(self, node: Optional[ET.Element], path: str) -> str:
        if node is None:
            return ""
        found = node.find(path)
        if found is None or found.text is None:
            return ""
        return found.text.strip()

    def _get_share_info_by_code_v2(self, share_code: str) -> Optional[Dict[str, Any]]:
        url = f"{self.HOST_URL}/api/open/share/getShareInfoByCodeV2.action"
        resp = self._session.get(url, params={"noCache": str(time.time()), "shareCode": share_code}, timeout=15)
        if resp.status_code != 200:
            logger.warning(
                "[cloud189] getShareInfoByCodeV2 http_status=%s share=%s",
                int(resp.status_code),
                self._tail(share_code),
            )
            return None
        try:
            j = resp.json()
            if isinstance(j, dict):
                res_code = str(j.get("res_code") or j.get("resCode") or "").strip()
                res_msg = str(j.get("res_message") or j.get("resMessage") or "").strip()
                res_code = str(j.get("res_code") or j.get("resCode") or "").strip()
                ok = res_code in ("0", "") or j.get("res_code") == 0
                file_id = str(j.get("fileId") or "")
                share_mode = str(j.get("shareMode") or "3")
                if ok:
                    share_id = str(j.get("shareId") or "")
                    if not file_id:
                        logger.warning(
                            "[cloud189] getShareInfoByCodeV2 missing fields ok=%s share=%s res_code=%s res_msg=%s share_id=%s file_id=%s",
                            ok,
                            self._tail(share_code),
                            res_code,
                            res_msg,
                            self._tail(share_id),
                            self._tail(file_id),
                        )
                        return None
                    if not share_id:
                        logger.warning(
                            "[cloud189] getShareInfoByCodeV2 share_id_empty ok=%s share=%s res_code=%s res_msg=%s share_mode=%s file_id=%s",
                            ok,
                            self._tail(share_code),
                            res_code,
                            res_msg,
                            share_mode,
                            self._tail(file_id),
                        )
                    return {
                        "shareId": share_id,
                        "fileId": file_id,
                        "shareMode": share_mode,
                        "isFolder": bool(j.get("isFolder")),
                        "fileName": str(j.get("fileName") or ""),
                    }
                if file_id:
                    logger.info(
                        "[cloud189] getShareInfoByCodeV2 non_ok share=%s res_code=%s res_msg=%s share_mode=%s file_id=%s share_id=%s",
                        self._tail(share_code),
                        res_code,
                        res_msg,
                        share_mode,
                        self._tail(file_id),
                        self._tail(str(j.get("shareId") or "")),
                    )
                    return {
                        "shareId": str(j.get("shareId") or ""),
                        "fileId": file_id,
                        "shareMode": share_mode,
                        "isFolder": bool(j.get("isFolder")),
                        "fileName": str(j.get("fileName") or ""),
                    }
                if res_code or res_msg:
                    logger.warning(
                        "[cloud189] getShareInfoByCodeV2 failed share=%s res_code=%s res_msg=%s body=%s",
                        self._tail(share_code),
                        res_code,
                        res_msg,
                        self._snippet(resp.text),
                    )
        except Exception:
            pass

        text = (resp.text or "").strip()
        if not text.startswith("<?xml"):
            logger.warning(
                "[cloud189] getShareInfoByCodeV2 unexpected_body share=%s body=%s",
                self._tail(share_code),
                self._snippet(text),
            )
            return None
        root = ET.fromstring(text)
        share_id = self._xml_text(root, "shareId")
        file_id = self._xml_text(root, "fileId")
        share_mode = self._xml_text(root, "shareMode")
        is_folder = self._xml_text(root, "isFolder").lower() == "true"
        file_name = self._xml_text(root, "fileName")
        if not share_id or not file_id:
            logger.warning(
                "[cloud189] getShareInfoByCodeV2 xml_missing_fields share=%s share_id=%s file_id=%s share_mode=%s",
                self._tail(share_code),
                self._tail(share_id),
                self._tail(file_id),
                share_mode,
            )
            return None
        return {
            "shareId": share_id,
            "fileId": file_id,
            "shareMode": share_mode or "3",
            "isFolder": is_folder,
            "fileName": file_name,
        }

    def _check_access_code(self, share_code: str, access_code: str) -> Optional[str]:
        if not share_code or not access_code:
            return None
        url = f"{self.HOST_URL}/api/open/share/checkAccessCode.action"
        logger.info(
            "[cloud189] checkAccessCode request share=%s passcode=%s",
            self._tail(share_code),
            self._mask_passcode(access_code),
        )
        resp = self._session.get(
            url,
            params={
                "noCache": str(time.time()),
                "shareCode": str(share_code),
                "accessCode": str(access_code),
                "uuid": str(uuid.uuid4()),
            },
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning(
                "[cloud189] checkAccessCode http_status=%s share=%s",
                int(resp.status_code),
                self._tail(share_code),
            )
            return None
        try:
            j = resp.json()
        except Exception:
            logger.warning(
                "[cloud189] checkAccessCode invalid_json share=%s body=%s",
                self._tail(share_code),
                self._snippet(resp.text),
            )
            return None
        if not isinstance(j, dict):
            return None
        res_code = str(j.get("res_code") or j.get("resCode") or "").strip()
        res_msg = str(j.get("res_message") or j.get("resMessage") or "").strip()
        share_id = str(j.get("shareId") or "").strip()
        logger.info(
            "[cloud189] checkAccessCode response share=%s res_code=%s res_msg=%s share_id=%s",
            self._tail(share_code),
            res_code,
            res_msg,
            self._tail(share_id),
        )
        if not share_id:
            logger.warning(
                "[cloud189] checkAccessCode failed share=%s res_code=%s res_msg=%s passcode=%s body=%s",
                self._tail(share_code),
                res_code,
                res_msg,
                self._mask_passcode(access_code),
                self._snippet(resp.text),
            )
        return share_id or None

    def _list_share_dir_by_code_v2(
        self, meta: Dict[str, Any], file_id: str, access_code: str, *, is_folder: bool = True
    ) -> List[Dict[str, Any]]:
        url = f"{self.HOST_URL}/api/open/share/listShareDir.action"
        params: Dict[str, Any] = {
            "noCache": str(time.time()),
            "pageNum": 1,
            "pageSize": 60,
            "fileId": str(file_id),
            "shareDirFileId": str(file_id),
            "isFolder": "true" if is_folder else "false",
            "shareId": str(meta.get("shareId") or ""),
            "shareMode": str(meta.get("shareMode") or "3"),
            "iconOption": 5,
            "orderBy": "lastOpTime",
            "descending": "true",
            "accessCode": access_code or "",
        }
        merged: List[Dict[str, Any]] = []
        page = 1
        while True:
            params["pageNum"] = page
            resp = self._request("GET", url, params=params, timeout=15)
            try:
                j = resp.json()
                if isinstance(j, dict) and int(j.get("res_code", 1)) != 0:
                    logger.warning(
                        "[cloud189] listShareDir failed share_id=%s file_id=%s share_mode=%s res_code=%s res_msg=%s passcode=%s",
                        self._tail(str(meta.get("shareId") or "")),
                        self._tail(str(file_id)),
                        str(meta.get("shareMode") or ""),
                        str(j.get("res_code") or ""),
                        str(j.get("res_message") or ""),
                        self._mask_passcode(access_code),
                    )
                    raise RuntimeError(j.get("res_message") or "解析分享失败")
                ao = j.get("fileListAO") if isinstance(j, dict) else None
                if not isinstance(ao, dict):
                    break
                total = int(ao.get("count") or 0)
                folder_list = ao.get("folderList") or []
                file_list = ao.get("fileList") or []
                batch: List[Dict[str, Any]] = []
                if isinstance(folder_list, list):
                    for it in folder_list:
                        if not isinstance(it, dict):
                            continue
                        batch.append(
                            {
                                "id": str(it.get("id") or ""),
                                "parentId": str(it.get("parentId") or ""),
                                "name": str(it.get("name") or ""),
                                "createDate": it.get("createDate"),
                                "lastOpTime": it.get("lastOpTime"),
                                "size": 0,
                                "isFolder": True,
                            }
                        )
                if isinstance(file_list, list):
                    for it in file_list:
                        if not isinstance(it, dict):
                            continue
                        batch.append(
                            {
                                "id": str(it.get("id") or ""),
                                "parentId": str(it.get("parentId") or ""),
                                "name": str(it.get("name") or ""),
                                "createDate": it.get("createDate"),
                                "lastOpTime": it.get("lastOpTime"),
                                "size": it.get("size") or 0,
                                "isFolder": False,
                            }
                        )
                merged.extend(batch)
                if total and page * 60 >= total:
                    break
                if not batch:
                    break
            except Exception:
                text = (resp.text or "").strip()
                if not text.startswith("<?xml"):
                    logger.warning(
                        "[cloud189] listShareDir unexpected_body share_id=%s file_id=%s share_mode=%s body=%s",
                        self._tail(str(meta.get("shareId") or "")),
                        self._tail(str(file_id)),
                        str(meta.get("shareMode") or ""),
                        self._snippet(text),
                    )
                    raise RuntimeError("解析分享失败")
                root = ET.fromstring(text)
                file_list_node = root.find("fileList")
                if file_list_node is None:
                    break
                count_text = self._xml_text(file_list_node, "count")
                try:
                    total = int(count_text) if count_text else 0
                except Exception:
                    total = 0
                batch = []
                for child in list(file_list_node):
                    if child.tag not in ("folder", "file"):
                        continue
                    item = {
                        "id": self._xml_text(child, "id"),
                        "parentId": self._xml_text(child, "parentId"),
                        "name": self._xml_text(child, "name"),
                        "createDate": self._xml_text(child, "createDate"),
                        "lastOpTime": self._xml_text(child, "lastOpTime"),
                        "size": self._xml_text(child, "size"),
                        "isFolder": child.tag == "folder",
                    }
                    batch.append(item)
                merged.extend(batch)
                if total and page * 60 >= total:
                    break
                if not batch:
                    break
            page += 1
            if page > 200:
                break
            time.sleep(0.2)
        return merged

    def _build_share_full_path_by_code_v2(
        self, share_meta: Dict[str, Any], root_file_id: str, target_file_id: str, access_code: str
    ) -> List[Dict[str, str]]:
        root_id = str(root_file_id or "")
        target_id = str(target_file_id or "")
        if not root_id or not target_id or target_id in ("0", "root", "/") or target_id == root_id:
            return []

        q: List[str] = [root_id]
        idx = 0
        parent: Dict[str, str] = {root_id: ""}
        name: Dict[str, str] = {root_id: str(share_meta.get("fileName") or "")}

        max_nodes = 400
        while idx < len(q) and len(parent) < max_nodes and target_id not in parent:
            cur = q[idx]
            idx += 1
            try:
                items = self._list_share_dir_by_code_v2(share_meta, cur, access_code)
            except Exception:
                continue
            for it in items:
                try:
                    if not it.get("isFolder"):
                        continue
                    cid = str(it.get("id") or "")
                    if not cid or cid in parent:
                        continue
                    parent_id = str(it.get("parentId") or cur)
                    parent[cid] = parent_id
                    name[cid] = str(it.get("name") or "")
                    q.append(cid)
                except Exception:
                    continue

        if target_id not in parent:
            return []

        path: List[Dict[str, str]] = []
        cur = target_id
        guard = 0
        while cur and cur != root_id and guard < 50:
            guard += 1
            path.insert(0, {"fid": cur, "file_name": name.get(cur, "")})
            cur = parent.get(cur, "")
        return path

    def get_stoken(self, pwd_id: str, passcode: str = "") -> Dict:
        if not pwd_id:
            return {"status": 400, "message": "分享链接无效", "data": {}}
        try:
            share_code = pwd_id
            meta2 = self._get_share_info_by_code_v2(share_code)
            if meta2:
                share_mode = str(meta2.get("shareMode") or "3")
                share_id = str(meta2.get("shareId") or "")
                if share_mode == "1":
                    if not passcode:
                        return {"status": 400, "message": "提取码不能为空", "data": {}}
                    checked = self._check_access_code(share_code, passcode or "")
                    if not checked:
                        logger.warning(
                            "[cloud189] get_stoken access_code_invalid share=%s share_mode=%s",
                            self._tail(share_code),
                            share_mode,
                        )
                        return {"status": 403, "message": "提取码错误", "data": {}}
                    share_id = checked
                if not share_id:
                    logger.warning(
                        "[cloud189] get_stoken share_id_empty share=%s share_mode=%s file_id=%s",
                        self._tail(share_code),
                        share_mode,
                        self._tail(str(meta2.get("fileId") or "")),
                    )
                stoken_obj = {
                    "shareId": share_id,
                    "shareMode": share_mode,
                    "rootFileId": meta2.get("fileId"),
                    "isFolder": bool(meta2.get("isFolder")),
                    "accessCode": passcode or "",
                }
                return {"status": 200, "data": {"stoken": json.dumps(stoken_obj, ensure_ascii=False)}}

            logger.warning(
                "[cloud189] get_stoken fallback_web_share share=%s passcode=%s",
                self._tail(share_code),
                self._mask_passcode(passcode),
            )
            html = self._fetch_share_page(pwd_id)
            meta = self._parse_share_page(html)
            if meta.get("invalid") == "1":
                return {"status": 404, "message": "分享不存在或已失效", "data": {}}
            share_id = meta.get("shareId") or ""
            is_file = meta.get("is_file") == "1"
            if not share_id:
                logger.warning(
                    "[cloud189] get_stoken parse_share_page_failed share=%s body=%s",
                    self._tail(share_code),
                    self._snippet(html),
                )
                return {"status": 404, "message": "解析分享失败", "data": {}}
            if is_file:
                ok = self._verify_share_file(share_id, passcode or "")
                if ok:
                    return {"status": 200, "data": {"stoken": passcode or ""}}
                if not passcode:
                    return {"status": 400, "message": "提取码不能为空", "data": {}}
                return {"status": 403, "message": "提取码错误", "data": {}}
            verify_code = meta.get("verifyCode") or ""
            if not verify_code:
                return {"status": 404, "message": "解析分享失败", "data": {}}
            ok, need_pwd = self._verify_share_folder(share_id, verify_code, passcode or "")
            if ok:
                return {"status": 200, "data": {"stoken": passcode or ""}}
            if need_pwd and not passcode:
                return {"status": 400, "message": "提取码不能为空", "data": {}}
            return {"status": 403, "message": "提取码错误", "data": {}}
        except Exception as e:
            return {"status": 500, "message": str(e), "data": {}}

    def _verify_share_file(self, share_id: str, access_code: str) -> bool:
        url = f"{self.HOST_URL}/shareFileVerifyPass.action"
        params = {"fileVO.id": share_id, "accessCode": access_code or ""}
        resp = self._session.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            return False
        try:
            j = resp.json()
        except Exception:
            return False
        return isinstance(j, dict) and bool(j)

    def _verify_share_folder(self, share_id: str, verify_code: str, access_code: str) -> Tuple[bool, bool]:
        url = f"{self.HOST_URL}/v2/listShareDir.action"
        params = {
            "shareId": share_id,
            "verifyCode": verify_code,
            "accessCode": access_code or "undefined",
            "orderBy": 1,
            "order": "ASC",
            "pageNum": 1,
            "pageSize": 1,
        }
        resp = self._session.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            return False, False
        try:
            j = resp.json()
        except Exception:
            return False, False
        if isinstance(j, dict) and "errorVO" in j:
            return False, True
        return True, False

    def get_detail(
        self,
        pwd_id: str,
        stoken: str,
        pdir_fid: str,
        _fetch_share: int = 0,
        fetch_share_full_path: int = 0,
    ) -> Dict:
        if not pwd_id:
            return {"code": 1, "message": "分享链接无效", "data": {"list": []}}
        share_code = pwd_id
        meta2 = self._get_share_info_by_code_v2(share_code)
        if meta2:
            access_code = ""
            share_id = str(meta2.get("shareId") or "")
            share_mode = str(meta2.get("shareMode") or "3")
            root_file_id = str(meta2.get("fileId") or "")
            try:
                st = json.loads(stoken) if stoken and stoken.strip().startswith("{") else {}
                if isinstance(st, dict):
                    access_code = str(st.get("accessCode") or "")
                    token_share_id = str(st.get("shareId") or "").strip()
                    token_share_mode = str(st.get("shareMode") or "").strip()
                    token_root_file_id = str(st.get("rootFileId") or "").strip()
                    if token_share_id and not share_id:
                        share_id = token_share_id
                    if token_share_mode:
                        share_mode = token_share_mode
                    if token_root_file_id and not root_file_id:
                        root_file_id = token_root_file_id
            except Exception:
                access_code = ""
            file_id = root_file_id if not pdir_fid or str(pdir_fid) in ("0", "root", "/") else str(pdir_fid)
            resolved_pdir_fid: str | None = None
            try:
                share_meta = {"shareId": share_id, "shareMode": share_mode}
                items = self._list_share_dir_by_code_v2(share_meta, file_id, access_code, is_folder=True)
                if (not items) and file_id and (file_id != root_file_id) and str(file_id) not in ("0", "root", "/"):
                    file_items = self._list_share_dir_by_code_v2(share_meta, file_id, access_code, is_folder=False)
                    if file_items:
                        parent_id = str(file_items[0].get("parentId") or "").strip()
                        if parent_id and parent_id != file_id:
                            resolved_pdir_fid = parent_id
                            file_id = parent_id
                            items = self._list_share_dir_by_code_v2(share_meta, file_id, access_code, is_folder=True)
            except Exception as e:
                return {"code": 1, "message": str(e) or "解析分享失败", "data": {"list": []}}
            parent_id = str(file_id)
            data_list: List[Dict[str, Any]] = []
            for it in items:
                name = it.get("name") or ""
                is_folder = bool(it.get("isFolder"))
                pid = str(it.get("parentId") or parent_id)
                token = json.dumps({"pid": pid, "dir": 1 if is_folder else 0, "name": name}, ensure_ascii=False)
                try:
                    size = int(it.get("size") or 0)
                except Exception:
                    size = 0
                data_list.append(
                    {
                        "fid": str(it.get("id", "")),
                        "file_name": name,
                        "dir": bool(is_folder),
                        "size": size,
                        "updated_at": self._parse_time_to_ts(it.get("lastOpTime") or it.get("createDate")),
                        "share_fid_token": token,
                    }
                )
            full_path: List[Dict[str, str]] = []
            if fetch_share_full_path:
                try:
                    share_meta = {"shareId": share_id, "shareMode": share_mode, "fileName": str(meta2.get("fileName") or "")}
                    full_path = self._build_share_full_path_by_code_v2(share_meta, root_file_id, file_id, access_code)
                except Exception:
                    full_path = []
            data: Dict[str, Any] = {"list": data_list, "full_path": full_path}
            if resolved_pdir_fid:
                data["resolved_pdir_fid"] = resolved_pdir_fid
            return {"code": 0, "message": "success", "data": data}

        html = self._fetch_share_page(pwd_id)
        meta = self._parse_share_page(html)
        if meta.get("invalid") == "1":
            return {"code": 1, "message": "分享不存在或已失效", "data": {"list": []}}
        share_id = meta.get("shareId") or ""
        if not share_id:
            return {"code": 1, "message": "解析分享失败", "data": {"list": []}}
        if meta.get("is_file") == "1":
            info = self._get_share_file_info(share_id, stoken or "")
            if not info:
                return {"code": 1, "message": "提取码错误或资源不可访问", "data": {"list": []}}
            item = {
                "fid": str(info.get("fileId", "")),
                "file_name": info.get("fileName", "") or "",
                "dir": False,
                "size": info.get("fileSize", 0) or 0,
                "updated_at": 0,
                "share_fid_token": json.dumps(
                    {"pid": "0", "dir": 0, "name": info.get("fileName", "") or ""},
                    ensure_ascii=False,
                ),
            }
            return {"code": 0, "message": "success", "data": {"list": [item], "full_path": []}}
        verify_code = meta.get("verifyCode") or ""
        if not verify_code:
            return {"code": 1, "message": "解析分享失败", "data": {"list": []}}
        try:
            parent_id = str(pdir_fid or "0")
        except Exception:
            parent_id = "0"
        items = self._list_share_dir(share_id, verify_code, stoken or "", parent_id)
        data_list: List[Dict[str, Any]] = []
        for it in items:
            name = it.get("fileName") or ""
            is_folder = bool(it.get("isFolder")) or str(it.get("isFolder", "")).strip() == "1"
            token = json.dumps({"pid": parent_id, "dir": 1 if is_folder else 0, "name": name})
            data_list.append(
                {
                    "fid": str(it.get("fileId", "")),
                    "file_name": name,
                    "dir": bool(is_folder),
                    "size": it.get("fileSize", 0) or 0,
                    "updated_at": self._parse_time_to_ts(it.get("lastOpTime") or it.get("createTime")),
                    "share_fid_token": token,
                }
            )
        return {"code": 0, "message": "success", "data": {"list": data_list, "full_path": []}}

    def _get_share_file_info(self, share_id: str, access_code: str) -> Optional[Dict[str, Any]]:
        url = f"{self.HOST_URL}/shareFileVerifyPass.action"
        params = {"fileVO.id": share_id, "accessCode": access_code or ""}
        resp = self._session.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            return None
        try:
            j = resp.json()
        except Exception:
            return None
        if not isinstance(j, dict) or not j:
            return None
        return j

    def _list_share_dir(
        self,
        share_id: str,
        verify_code: str,
        access_code: str,
        parent_id: str,
    ) -> List[Dict[str, Any]]:
        url = f"{self.HOST_URL}/v2/listShareDir.action"
        merged: List[Dict[str, Any]] = []
        page = 1
        while True:
            params: Dict[str, Any] = {
                "shareId": share_id,
                "verifyCode": verify_code,
                "accessCode": access_code or "undefined",
                "orderBy": 1,
                "order": "ASC",
                "pageNum": page,
                "pageSize": 60,
            }
            if parent_id not in ("0", "", None):
                params["fileId"] = parent_id
            j = self._request_json("GET", url, params=params, timeout=15)
            if isinstance(j, dict) and "errorVO" in j:
                raise RuntimeError("提取码错误或资源不可访问")
            data = (j or {}).get("data") if isinstance(j, dict) else None
            if not isinstance(data, list):
                data = []
            merged.extend(data)
            record_count = (j or {}).get("recordCount") if isinstance(j, dict) else None
            page_size = (j or {}).get("pageSize") if isinstance(j, dict) else None
            page_num = (j or {}).get("pageNum") if isinstance(j, dict) else None
            if isinstance(record_count, int) and isinstance(page_size, int) and isinstance(page_num, int):
                if record_count <= page_size * page_num:
                    break
            if not data:
                break
            page += 1
            if page > 100:
                break
        return merged

    def _map_root_fid(self, fid: str) -> str:
        if not fid or str(fid) in ("0", "root", "/"):
            return "-11"
        return str(fid)

    def ls_dir(self, pdir_fid: str, max_items: int = 0, **kwargs) -> Dict:
        try:
            self._ensure_login()
            fid = self._map_root_fid(pdir_fid)
            if str(fid) == "-11":
                url = f"{self.HOST_URL}/api/portal/listFiles.action"
                merged: List[Dict[str, Any]] = []
                page = 1
                while True:
                    j = self._request_json("GET", url, params={"fileId": "-11", "noCache": str(time.time())}, timeout=15)
                    if not isinstance(j, dict) or "errorCode" in j:
                        raise RuntimeError("获取目录列表失败")
                    data = j.get("data") or []
                    if not isinstance(data, list):
                        data = []
                    for it in data:
                        is_folder = bool(it.get("isFolder"))
                        merged.append(
                            {
                                "fid": str(it.get("fileId", "")),
                                "file_name": it.get("fileName", "") or "",
                                "dir": bool(is_folder),
                                "size": it.get("fileSize", 0) or 0,
                                "updated_at": self._parse_time_to_ts(it.get("lastOpTime") or it.get("createTime")),
                                "share_fid_token": "",
                            }
                        )
                    record_count = j.get("recordCount")
                    page_size = j.get("pageSize")
                    page_num = j.get("pageNum")
                    if isinstance(record_count, int) and isinstance(page_size, int) and isinstance(page_num, int):
                        if record_count <= page_size * page_num:
                            break
                    if not data:
                        break
                    page += 1
                    if page > 100:
                        break
                    time.sleep(0.2)
                if max_items > 0 and len(merged) > max_items:
                    merged = merged[:max_items]
                return {"code": 0, "message": "success", "data": {"list": merged}}

            url = f"{self.HOST_URL}/api/open/file/listFiles.action"
            merged: List[Dict[str, Any]] = []
            page = 1
            while True:
                params = {
                    "folderId": str(fid),
                    "orderBy": "lastOpTime",
                    "descending": "true",
                    "pageNum": page,
                    "pageSize": 60,
                    "iconOption": 5,
                    "mediaType": 0,
                    "noCache": str(time.time()),
                }
                j = self._request_json("GET", url, params=params, timeout=15)
                if not isinstance(j, dict) or "errorCode" in j:
                    raise RuntimeError("获取目录列表失败")
                ao = j.get("fileListAO") or {}
                folder_list = ao.get("folderList") or []
                file_list = ao.get("fileList") or []
                batch = []
                if isinstance(folder_list, list):
                    batch.extend(folder_list)
                if isinstance(file_list, list):
                    batch.extend(file_list)
                for it in batch:
                    is_folder = "fileCount" in it or bool(it.get("isFolder"))
                    merged.append(
                        {
                            "fid": str(it.get("id", "")),
                            "file_name": it.get("name", "") or "",
                            "dir": bool(is_folder),
                            "size": it.get("size", 0) or 0,
                            "updated_at": self._parse_time_to_ts(it.get("lastOpTime") or it.get("createDate")),
                            "share_fid_token": "",
                        }
                    )
                if max_items > 0 and len(merged) >= max_items:
                    merged = merged[:max_items]
                    break
                count = ao.get("count")
                page_size = 60
                if isinstance(count, int) and page * page_size >= count:
                    break
                if not batch:
                    break
                page += 1
                if page > 200:
                    break
                time.sleep(0.2)
            return {"code": 0, "message": "success", "data": {"list": merged}}
        except Exception as e:
            return {"code": 1, "message": str(e), "data": {"list": []}}

    def mkdir(self, dir_path: str) -> Dict:
        if not dir_path:
            return {"code": 1, "message": "目录不能为空", "data": {}}
        try:
            self._ensure_login()
        except Exception as e:
            return {"code": 1, "message": str(e), "data": {}}
        p = re.sub(r"/{2,}", "/", f"/{dir_path}".strip())
        if p == "/":
            return {"code": 0, "message": "success", "data": {"fid": "0"}}
        parts = [x for x in p.split("/") if x]
        parent_id = "-11"
        for name in parts:
            found = self._find_child_folder(parent_id, name)
            if found:
                parent_id = found
                continue
            url = f"{self.HOST_URL}/v2/createFolder.action"
            j = self._request_json("GET", url, params={"parentId": str(parent_id), "fileName": name}, timeout=15)
            fid = j.get("fileId") if isinstance(j, dict) else None
            if not fid:
                return {"code": 1, "message": "创建目录失败", "data": {}}
            parent_id = str(fid)
            time.sleep(0.1)
        return {"code": 0, "message": "success", "data": {"fid": str(parent_id)}}

    def _find_child_folder(self, parent_id: str, folder_name: str) -> str:
        try:
            self._ensure_login()
        except Exception:
            return ""
        url = f"{self.HOST_URL}/api/open/file/listFiles.action"
        page = 1
        while True:
            params = {
                "folderId": str(parent_id),
                "orderBy": "lastOpTime",
                "descending": "true",
                "pageNum": page,
                "pageSize": 60,
                "iconOption": 5,
                "mediaType": 0,
                "noCache": str(time.time()),
            }
            resp = self._session.get(url, params=params, timeout=15)
            if resp.status_code != 200:
                return ""
            try:
                j = resp.json()
            except Exception:
                return ""
            ao = j.get("fileListAO") or {}
            folder_list = ao.get("folderList") or []
            if isinstance(folder_list, list):
                for it in folder_list:
                    if (it.get("name") or "") == folder_name:
                        return str(it.get("id", ""))
            count = ao.get("count")
            if isinstance(count, int) and page * 60 >= count:
                break
            if not folder_list:
                break
            page += 1
            if page > 50:
                break
            time.sleep(0.1)
        return ""

    def rename(self, fid: str, file_name: str) -> Dict:
        try:
            self._ensure_login()
            url = f"{self.HOST_URL}/api/open/file/renameFile.action"
            new_name = str(file_name or "").replace("/", "_").strip()
            if not new_name:
                return {"code": 1, "message": "文件名不能为空", "data": {}}
            resp = self._session.post(
                url,
                data={"fileId": str(fid), "destFileName": new_name, "noCache": str(time.time())},
                headers={"Referer": "https://cloud.189.cn/", "Origin": "https://cloud.189.cn"},
                timeout=15,
            )
            resp.raise_for_status()
            j = resp.json()
            if isinstance(j, dict):
                if int(j.get("res_code", 1)) == 0:
                    return {"code": 0, "message": "success", "data": {}}
                if j.get("success") is True:
                    return {"code": 0, "message": "success", "data": {}}
                msg = j.get("res_message") or j.get("msg") or j.get("message") or ""
                return {"code": 1, "message": str(msg or "重命名失败"), "data": {}}
            return {"code": 1, "message": "重命名失败", "data": {}}
        except Exception as e:
            return {"code": 1, "message": str(e), "data": {}}

    def delete(self, filelist: List[str]) -> Dict:
        try:
            self._ensure_login()
            if not filelist:
                return {"code": 0, "message": "success", "data": {}}
            task_infos: List[Dict[str, Any]] = []
            for fid in filelist:
                info = self._get_file_info(fid)
                if not info:
                    continue
                task_infos.append(
                    {
                        "fileId": str(info.get("fileId", fid)),
                        "fileName": info.get("fileName", "") or "",
                        "isFolder": 1 if info.get("isFolder") else 0,
                    }
                )
            if not task_infos:
                return {"code": 0, "message": "success", "data": {}}

            task_id = self._open_batch_create_task("DELETE", task_infos, "")
            tries = 0
            last_j: Any = None
            while True:
                j = self._open_batch_check_task("DELETE", task_id)
                last_j = j
                status = j.get("taskStatus")
                if self._debug:
                    try:
                        logger.info(f"[cloud189] delete poll: taskId={task_id} try={tries} status={status}")
                    except Exception:
                        pass
                if status in (4, "4"):
                    break
                if status in (5, "5", -1, "-1"):
                    msg = j.get("taskErrorMsg") or j.get("res_message") or j.get("msg") or ""
                    raise RuntimeError(str(msg or "删除失败"))
                tries += 1
                if tries > 120:
                    raise RuntimeError("删除超时")
                time.sleep(0.5)

            remaining: List[str] = []
            for it in task_infos:
                fid = str(it.get("fileId") or "")
                if not fid:
                    continue
                tries2 = 0
                while tries2 < 6:
                    if not self._get_file_info(fid):
                        break
                    tries2 += 1
                    time.sleep(0.6)
                if self._get_file_info(fid):
                    remaining.append(fid)
            if remaining and self._debug:
                try:
                    msg = json.dumps(last_j, ensure_ascii=False)
                except Exception:
                    msg = str(last_j)
                try:
                    logger.info(f"[cloud189] delete verify remaining={remaining[:20]} task={msg[:800]}")
                except Exception:
                    pass
            return {"code": 0, "message": "success", "data": {}}
        except Exception as e:
            return {"code": 1, "message": str(e), "data": {}}

    def _get_file_info(self, file_id: str) -> Optional[Dict[str, Any]]:
        try:
            self._ensure_login()
        except Exception:
            return None
        url = f"{self.HOST_URL}/v2/getFileInfo.action"
        resp = self._session.get(url, params={"fileId": str(file_id)}, timeout=15)
        if resp.status_code != 200:
            return None
        try:
            j = resp.json()
        except Exception:
            return None
        if not isinstance(j, dict):
            return None
        if j.get("errorCode") or j.get("errorMsg") or j.get("res_code") not in (None, 0, "0"):
            return None
        if j.get("success") is False:
            return None
        if "fileId" not in j:
            return None
        j["isFolder"] = bool(j.get("isFolder")) or str(j.get("isFolder", "")).strip() == "1"
        return j

    def get_fids(self, file_paths: List[str]) -> List[Dict]:
        try:
            self._ensure_login()
        except Exception:
            return []
        result: List[Dict[str, str]] = []
        for p in file_paths:
            p_norm = re.sub(r"/{2,}", "/", f"/{p}".strip())
            if p_norm == "/":
                result.append({"file_path": "/", "fid": "0"})
                continue
            parts = [x for x in p_norm.split("/") if x]
            parent_id = "-11"
            ok = True
            for name in parts:
                found = self._find_child_folder(parent_id, name)
                if not found:
                    ok = False
                    break
                parent_id = found
            if ok:
                result.append({"file_path": p_norm, "fid": str(parent_id)})
        return result

    def _create_batch_task(self, task_type: str, task_infos: List[Dict[str, Any]], target_folder_id: str, share_id: str = "") -> str:
        self._ensure_login()
        url = f"{self.HOST_URL}/createBatchTask.action"
        data: Dict[str, Any] = {"type": task_type, "taskInfos": json.dumps(task_infos, ensure_ascii=False)}
        if target_folder_id:
            data["targetFolderId"] = str(target_folder_id)
        if share_id:
            data["shareId"] = str(share_id)
        resp = self._request("POST", url, data=data, timeout=15)
        task_id = (resp.text or "").strip().strip('"').strip("'")
        try:
            j = json.loads(task_id)
        except Exception:
            j = None
        if isinstance(j, dict) and "taskId" in j:
            task_id = j["taskId"]
        if not task_id:
            raise RuntimeError("创建任务失败")
        if self._debug:
            try:
                logger.info(
                    f"[cloud189] createBatchTask ok: type={task_type} taskId={task_id} "
                    f"items={len(task_infos)} target={target_folder_id} shareId={share_id}"
                )
            except Exception:
                pass
        return task_id

    def _check_batch_task(self, task_type: str, task_id: str) -> Dict[str, Any]:
        self._ensure_login()
        url = f"{self.HOST_URL}/checkBatchTask.action"
        j = self._request_json("POST", url, data={"type": task_type, "taskId": task_id}, timeout=15)
        if self._debug:
            logger.info(f"checkBatchTask resp: {j}")
        if not isinstance(j, dict):
            raise RuntimeError("查询任务失败")
        return j

    def _open_batch_create_task(self, task_type: str, task_infos: List[Dict[str, Any]], target_folder_id: str = "") -> str:
        self._ensure_login()
        url = f"{self.HOST_URL}/api/open/batch/createBatchTask.action"
        data: Dict[str, Any] = {"type": task_type, "taskInfos": json.dumps(task_infos, ensure_ascii=False)}
        if target_folder_id:
            data["targetFolderId"] = str(target_folder_id)
        resp = self._request("POST", url, data=data, timeout=15, raise_status=False)
        if self._debug:
            try:
                t = (resp.text or "").replace("\r", " ").replace("\n", " ").strip()
                logger.info(f"[cloud189] openBatchCreate: type={task_type} http={resp.status_code} body={t[:800]}")
            except Exception:
                pass
        resp.raise_for_status()
        try:
            j = resp.json()
        except Exception:
            j = None
        if isinstance(j, dict):
            if int(j.get("res_code", 1)) != 0:
                raise RuntimeError(str(j.get("res_message") or j.get("msg") or "创建任务失败"))
            task_id = str(j.get("taskId") or j.get("task_id") or j.get("data") or "")
            if task_id:
                return task_id
        task_id = (resp.text or "").strip().strip('"').strip("'")
        if not task_id:
            raise RuntimeError("创建任务失败")
        return task_id

    def _open_batch_check_task(self, task_type: str, task_id: str) -> Dict[str, Any]:
        self._ensure_login()
        url = f"{self.HOST_URL}/api/open/batch/checkBatchTask.action"
        resp = self._request("POST", url, data={"type": task_type, "taskId": task_id}, timeout=15, raise_status=False)
        if self._debug:
            try:
                t = (resp.text or "").replace("\r", " ").replace("\n", " ").strip()
                logger.info(f"[cloud189] openBatchCheck: type={task_type} taskId={task_id} http={resp.status_code} body={t[:800]}")
            except Exception:
                pass
        resp.raise_for_status()
        j = resp.json()
        if not isinstance(j, dict):
            raise RuntimeError("查询任务失败")
        if int(j.get("res_code", 0) or 0) not in (0,):
            raise RuntimeError(str(j.get("res_message") or j.get("msg") or "查询任务失败"))
        return j

    def save_file(
        self,
        fid_list: List[str],
        fid_token_list: List[str],
        to_pdir_fid: str,
        pwd_id: str,
        stoken: str,
        file_names: List[str] = None,
    ) -> Dict:
        try:
            self._ensure_login()
            if not fid_list:
                return {"code": 0, "message": "success", "data": {"task_id": ""}}
            access_code = ""
            st_share_id = ""
            st_share_mode = ""
            st_root_file_id = ""
            try:
                st = json.loads(stoken) if stoken and stoken.strip().startswith("{") else {}
                if isinstance(st, dict):
                    access_code = str(st.get("accessCode") or "")
                    st_share_id = str(st.get("shareId") or "")
                    st_share_mode = str(st.get("shareMode") or "")
                    st_root_file_id = str(st.get("rootFileId") or "")
            except Exception:
                access_code = ""
            if not access_code:
                access_code = (stoken or "").strip()

            share_id = ""
            share_mode = "3"
            root_file_id = ""
            if st_share_id:
                share_id = st_share_id
            if st_share_mode:
                share_mode = st_share_mode
            if st_root_file_id:
                root_file_id = st_root_file_id

            meta2 = None
            if not share_mode or not root_file_id:
                meta2 = self._get_share_info_by_code_v2(pwd_id)
                if meta2:
                    share_mode = str(meta2.get("shareMode") or share_mode or "3")
                    root_file_id = str(meta2.get("fileId") or root_file_id or "")
                    if not share_id:
                        share_id = str(meta2.get("shareId") or "")

            if share_mode == "1" and access_code and not share_id:
                checked = self._check_access_code(pwd_id, access_code)
                if checked:
                    share_id = checked
            if not share_id:
                html = self._fetch_share_page(pwd_id)
                meta = self._parse_share_page(html)
                share_id = meta.get("shareId") or ""
            if not share_id:
                return {"code": 1, "message": "解析分享失败", "data": {}}

            if root_file_id:
                try:
                    _ = self._list_share_dir_by_code_v2({"shareId": share_id, "shareMode": share_mode}, root_file_id, access_code)
                except Exception as e:
                    return {"code": 1, "message": str(e) or "解析分享失败", "data": {}}
            target = self._map_root_fid(to_pdir_fid)

            before_items: Dict[str, str] = {}
            if file_names:
                try:
                    before_dir = self.ls_dir(target, max_items=1000)
                    if isinstance(before_dir, dict) and before_dir.get("code") == 0:
                        for it in before_dir.get("data", {}).get("list", []) or []:
                            if not isinstance(it, dict):
                                continue
                            fid0 = str(it.get("fid") or "")
                            name0 = str(it.get("file_name") or "")
                            if fid0:
                                before_items[fid0] = name0
                except Exception:
                    before_items = {}

            task_infos: List[Dict[str, Any]] = []
            for i, fid in enumerate(fid_list):
                token = (fid_token_list[i] if fid_token_list and i < len(fid_token_list) else "") or ""
                pid = "0"
                is_folder = 0
                name = ""
                if token:
                    try:
                        t = json.loads(token)
                        if isinstance(t, dict):
                            pid = str(t.get("pid", "0"))
                            is_folder = 1 if int(t.get("dir", 0) or 0) else 0
                            name = str(t.get("name") or "")
                    except Exception:
                        pid = "0"
                task_infos.append(
                    {
                        "fileId": str(fid),
                        "srcParentId": str(pid),
                        "fileName": name,
                        "isFolder": int(is_folder),
                    }
                )
            task_id = self._create_batch_task("SHARE_SAVE", task_infos, target, share_id=share_id)

            if not file_names:
                return {"code": 0, "message": "success", "data": {"task_id": task_id}}

            def _clean_name(s: str) -> str:
                try:
                    return re.sub(r"[^\w\s\.]", "", str(s or ""))
                except Exception:
                    return str(s or "")

            name_to_fids: Dict[str, List[str]] = {}
            deadline = time.time() + 120
            while time.time() < deadline:
                try:
                    after_dir = self.ls_dir(target, max_items=1000)
                    if not isinstance(after_dir, dict) or after_dir.get("code") != 0:
                        time.sleep(1)
                        continue
                    items = after_dir.get("data", {}).get("list", []) or []
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        fid0 = str(it.get("fid") or "")
                        name0 = str(it.get("file_name") or "")
                        if not fid0 or fid0 in before_items:
                            continue
                        if not name0:
                            continue
                        name_to_fids.setdefault(name0, [])
                        if fid0 not in name_to_fids[name0]:
                            name_to_fids[name0].append(fid0)
                    total_new = sum(len(v) for v in name_to_fids.values())
                    if total_new >= len(file_names):
                        break
                except Exception:
                    pass
                time.sleep(2)

            aligned: List[str] = []
            used: set = set()
            for fname in file_names:
                fid0 = ""
                lst = name_to_fids.get(fname) or []
                for cand in lst:
                    if cand and cand not in used:
                        fid0 = cand
                        break
                if not fid0:
                    fname_clean = _clean_name(fname)
                    for k, lst2 in name_to_fids.items():
                        if _clean_name(k) != fname_clean:
                            continue
                        for cand in lst2:
                            if cand and cand not in used:
                                fid0 = cand
                                break
                        if fid0:
                            break
                if fid0:
                    used.add(fid0)
                aligned.append(fid0)

            return {
                "code": 0,
                "message": "success",
                "data": {"task_id": task_id, "save_as_top_fids": aligned, "_sync": True},
            }
        except Exception as e:
            return {"code": 1, "message": str(e), "data": {}}

    def query_task(self, task_id: str) -> Dict:
        try:
            self._ensure_login()
            if not task_id:
                return {"code": 0, "message": "ok", "data": {"save_as": {"save_as_top_fids": []}}}
            tries = 0
            last_status = None
            last_j: Any = None

            def _snip_obj(obj: Any, n: int = 600) -> str:
                try:
                    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
                except Exception:
                    s = str(obj)
                s = (s or "").replace("\r", " ").replace("\n", " ").strip()
                return s[:n]

            while True:
                j = self._check_batch_task("SHARE_SAVE", task_id)
                if isinstance(j, dict) and (j.get("success") is False):
                    err = str(j.get("errorMsg") or j.get("error_msg") or j.get("res_message") or "任务失败")
                    code = str(j.get("errorCode") or j.get("error_code") or "").strip()
                    if code.lower() == "invalidargument" or "无法识别的任务" in err:
                        try:
                            j = self._open_batch_check_task("SHARE_SAVE", task_id)
                        except Exception:
                            raise RuntimeError(err)
                    else:
                        raise RuntimeError(err)
                status = j.get("taskStatus")
                last_status = status
                last_j = j
                if self._debug and tries % 10 == 0:
                    try:
                        logger.info(f"[cloud189] checkBatchTask: taskId={task_id} try={tries} status={status} body={_snip_obj(j)}")
                    except Exception:
                        pass
                if status in (4, "4"):
                    break
                if status in (5, "5", -1, "-1"):
                    raise RuntimeError(f"任务失败 status={status} detail={_snip_obj(j)}")
                tries += 1
                if tries > 200:
                    raise RuntimeError(f"任务超时 status={last_status} detail={_snip_obj(last_j)}")
                time.sleep(0.5)
            ids = j.get("successedFileIdList") or j.get("successedFileIdList".lower()) or []
            if not isinstance(ids, list):
                ids = []
            save_as_top_fids = [str(x) for x in ids if str(x)]
            return {"code": 0, "message": "ok", "data": {"save_as": {"save_as_top_fids": save_as_top_fids}}}
        except Exception as e:
            return {"code": 1, "message": str(e), "data": {"save_as": {"save_as_top_fids": []}}}
