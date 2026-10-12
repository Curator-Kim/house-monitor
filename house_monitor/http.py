"""有节流、原始响应和 robots 检查的普通 HTTP 客户端；验证码流程由上层显式处理。"""
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urljoin

import requests

UA = "HouseResearchMonitor/0.1 (personal research; daily snapshots)"


class SourceError(RuntimeError):
    def __init__(self, message, status="error"):
        super().__init__(message)
        self.status = status


def decode(body):
    # 部分页面的 meta 标记与实际 UTF-8 字节不一致。
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return body.decode("gb18030", errors="replace")


def blocked(response):
    text = decode(response.content)
    return (response.status_code in (401, 403, 429)
            or any(s in response.url.lower() for s in ("captcha", "forbidden", "verify", "login", "check.3g.fang.com"))
            or bool(re.search(r"<title[^>]*>\s*(?:403|验证码|Forbidden|安全验证)", text, re.I))
            or any(s in text for s in ("请求未能通过我们的安全检查", "访问过于频繁", "请完成安全验证", "请完成下列验证后继续")))


def robots_allowed(text, url):
    """支持 robots 的 * 和 $，只应用匹配的最具体 User-agent 组。"""
    groups, agents, rules = [], [], []
    for line in text.splitlines() + ["User-agent: __end__"]:
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (s.strip() for s in line.split(":", 1))
        if key.lower() == "user-agent":
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(value.lower())
        elif key.lower() in ("allow", "disallow") and agents:
            rules.append((key.lower(), value))
    candidates = [(max((len(a) if a != "*" else 0) for a in aa if a == "*" or a in UA.lower()), rr)
                  for aa, rr in groups if any(a == "*" or a in UA.lower() for a in aa)]
    if not candidates:
        return True
    specificity = max(n for n, _ in candidates)
    parts = urlsplit(url)
    path = parts.path + ("?" + parts.query if parts.query else "")
    matches = []
    for n, rr in candidates:
        if n != specificity:
            continue
        for rule, pattern in rr:
            if not pattern or not pattern.startswith("/"):
                continue
            end = pattern.endswith("$")
            expression = "^" + re.escape(pattern[:-1] if end else pattern).replace(r"\*", ".*") + ("$" if end else "")
            if re.search(expression, path):
                matches.append((len(pattern.replace("*", "")), rule == "allow"))
    return max(matches)[1] if matches else True


class Client:
    def __init__(self, config, run_id):
        self.config = config
        self.session = requests.Session()
        self.session.headers["User-Agent"] = UA
        self.root = Path(config["data_dir"]) / "raw" / str(run_id)
        self.root.mkdir(parents=True, exist_ok=True)
        self.last_request = 0
        self.policies = {}
        self.counter = 0

    def save_raw(self, url, content, method="GET", final_url=None, status=200, content_type=None):
        """保存浏览器或接口取得的原始响应，保持与 HTTP 请求相同的可追溯格式。"""
        body = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        self.counter += 1
        stem = f"{self.counter:04d}-{hashlib.sha256(url.encode()).hexdigest()[:12]}"
        (self.root / (stem + ".body")).write_bytes(body)
        (self.root / (stem + ".json")).write_text(json.dumps({
            "requested_url": url, "method": method, "final_url": final_url or url, "status": status,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "content_type": content_type,
            "sha256": hashlib.sha256(body).hexdigest()
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return stem

    def _solve_slider(self, challenge_url):
        """用受控浏览器通过来源的简单拖动验证，并把 Cookie 带回普通会话。"""
        from .browser import BrowserSession
        with BrowserSession(self.config) as browser:
            cookies = browser.drag_slider_to_end(challenge_url)
        for cookie in cookies:
            self.session.cookies.set(cookie["name"], cookie["value"], domain=cookie.get("domain"),
                                     path=cookie.get("path", "/"))
        self.last_request = time.monotonic()

    def _request(self, url, method="GET"):
        for attempt in range(3):
            time.sleep(max(0, self.config["request_interval_seconds"] - (time.monotonic() - self.last_request)))
            try:
                request = self.session.get if method == "GET" else self.session.post
                r = request(url, timeout=self.config["request_timeout_seconds"])
                self.last_request = time.monotonic()
                self.save_raw(url, r.content, method=method, final_url=r.url, status=r.status_code,
                              content_type=r.headers.get("Content-Type"))
                if blocked(r):
                    if ("check.3g.fang.com" in r.url and attempt < 2
                            and self.config.get("captcha_browser_enabled", True)):
                        self._solve_slider(r.url)
                        continue
                    raise SourceError(f"访问限制：HTTP {r.status_code}，{r.url}", "blocked")
                if r.status_code >= 500 and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                return r
            except (requests.Timeout, requests.ConnectionError) as exc:
                self.last_request = time.monotonic()
                if attempt == 2:
                    raise SourceError(f"网络请求失败：{url}：{exc}") from exc
                time.sleep(2 ** attempt)

    def get(self, url, method="GET"):
        parts = urlsplit(url)
        if parts.scheme != "https":
            raise SourceError("只采集 HTTPS 来源")
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self.policies:
            r = self._request(urljoin(origin, "/robots.txt"))
            if r.status_code == 404:
                self.policies[origin] = ""
            elif r.status_code == 200 and not decode(r.content).lstrip().startswith("<"):
                self.policies[origin] = decode(r.content)
            else:
                raise SourceError("robots.txt 无法核实，暂停自动采集", "blocked")
        if not robots_allowed(self.policies[origin], url):
            raise SourceError(f"robots.txt 不允许采集：{url}", "blocked")
        r = self._request(url, method)
        if r.status_code != 200:
            raise SourceError(f"HTTP {r.status_code}：{url}")
        if urlsplit(r.url).netloc != parts.netloc:
            raise SourceError("来源跳转到其他站点，暂停解析", "blocked")
        return decode(r.content)
