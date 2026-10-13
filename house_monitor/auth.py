"""本地登录会话管理；只保存用户提供的令牌或 Cookie，不保存账号密码。"""
import json
from datetime import datetime
from pathlib import Path
from .http import SourceError


def _directory(data_dir):
    directory = Path(data_dir) / "auth"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _path(data_dir, source):
    return _directory(data_dir) / f"{source}.json"


def parse_cookie_header(value):
    cookies = {}
    for part in (value or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, content = part.split("=", 1)
        name = name.strip()
        if name:
            cookies[name] = content.strip()
    return cookies


def save_auth(data_dir, source, cookie=None, token=None, headers=None, auth_file=None):
    payload = {"source": source, "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
               "cookies": {}, "headers": {}}
    if auth_file:
        loaded = json.loads(Path(auth_file).read_text(encoding="utf-8-sig"))
        payload["cookies"].update(loaded.get("cookies") or {})
        payload["headers"].update(loaded.get("headers") or {})
    payload["cookies"].update(parse_cookie_header(cookie))
    if token:
        payload["headers"]["Authorization"] = token
    for header in headers or []:
        if ":" not in header:
            raise SourceError(f"请求头格式错误：{header}", "auth_invalid")
        name, value = header.split(":", 1)
        payload["headers"][name.strip()] = value.strip()
    if not payload["cookies"] and not payload["headers"]:
        raise SourceError("没有可保存的 Cookie 或令牌", "auth_invalid")
    path = _path(data_dir, source)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return {"source": source, "auth_file": str(path.resolve()),
            "cookies": len(payload["cookies"]), "headers": sorted(payload["headers"])}


def load_auth(data_dir, source):
    path = _path(data_dir, source)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload.get("cookies"), dict) or not isinstance(payload.get("headers"), dict):
        raise SourceError(f"{source} 登录会话文件结构错误", "auth_invalid")
    return payload


def apply_auth(client, source):
    payload = load_auth(client.config["data_dir"], source)
    if not payload:
        return False
    for name, value in payload["cookies"].items():
        client.session.cookies.set(name, value)
    client.session.headers.update(payload["headers"])
    return True

def clear_auth(data_dir, source):
    path = _path(data_dir, source)
    if path.exists():
        path.unlink()
        return True
    return False