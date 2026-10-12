import re
import json
from datetime import datetime, timedelta
from time import sleep
from zoneinfo import ZoneInfo
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
from .models import SourceResult
from .http import SourceError
from .parsers import fang_list, fang_history, lianjia_list, official_stats, official_json, nbs_indices, ygjy_records, text
from .browser import BrowserSession


def collect_list(source, url, region, client, config, store):
    result = SourceResult(source, region["id"])
    visited, ids, expected_pages = set(), set(), None
    next_url = url
    parser = fang_list if source == "fang" else lianjia_list
    try:
        while next_url:
            if next_url in visited or len(visited) >= config["max_pages"]:
                raise SourceError("分页循环或超过分页上限，结果仅部分覆盖", "partial")
            if urlsplit(next_url).netloc != urlsplit(url).netloc:
                raise SourceError("下一页链接跨域", "schema_changed")
            visited.add(next_url)
            html = client.get(next_url)
            rows, page_ids, next_url, total = parser(html, next_url, region)
            if ids and page_ids.issubset(ids):
                raise SourceError("不同分页返回相同项目，停止采集", "partial")
            ids |= page_ids
            result.records.extend(rows)
            result.pages += 1
            expected_pages = total or expected_pages
        unique = {o.source_id: o for o in result.records}
        result.records = list(unique.values())
        if expected_pages and result.pages != expected_pages:
            raise SourceError("采集页数与来源分页总数不一致", "partial")
        result.complete = True
    except SourceError as exc:
        result.status = "partial" if result.records else exc.status
        result.message = str(exc)
    result.discovered = len(ids)
    result.eligible = len({o.source_id for o in result.records})
    if result.complete and not result.records:
        result.status, result.message = "schema_changed", "未发现符合筛选的住宅，需人工核对"
        result.complete = False
    if source == "fang" and result.records and config.get("history_enabled"):
        snapshot = list(result.records)
        for o in snapshot:
            last = store.rows("SELECT max(observed_at) latest FROM observations WHERE source='fang' AND source_id=? AND region_id=? AND granularity='event'", (o.source_id, region["id"]))[0]["latest"]
            if last and datetime.fromisoformat(last) > datetime.now(datetime.fromisoformat(last).tzinfo) - timedelta(days=config["history_refresh_days"]):
                continue
            history_url = urljoin(url, f"/loupan/{o.source_id}/fangjia.htm")
            try:
                events = fang_history(client.get(history_url), o.source_id, o.name, history_url, region["id"])
                if events:
                    o.source_updated = max(e.period for e in events)
                    result.records.extend(events)
            except SourceError as exc:
                result.warnings.append(f"{o.name}历史：{exc}")
                if exc.status == "blocked":
                    result.warnings.append("该站历史请求遇访问限制，本轮不再请求其他历史页面")
                    break
    if not result.message:
        result.message = "参考报价；成交价未公开验证。来源完整分页不等于全区绝对覆盖。"
    return result


def collect_nbs(url, region, client):
    result = SourceResult("nbs", region["id"])
    html = client.get(url)
    if "70个大中城市商品住宅销售价格变动情况" not in text(BeautifulSoup(html, "html.parser").find("title")):
        soup = BeautifulSoup(html, "html.parser")
        candidates = []
        for a in soup.select("a[href]"):
            match = re.search(r"(\d{4})年(\d{1,2})月份70个大中城市商品住宅销售价格变动情况", text(a))
            if match:
                candidates.append((int(match[1]), int(match[2]), urljoin(url, a["href"])))
        if not candidates:
            raise SourceError("统计局最新发布列表未发现价格指数文章", "schema_changed")
        url = max(candidates)[2]
        html = client.get(url)
    result.records = nbs_indices(html, url, region)
    result.discovered = result.eligible = 1
    result.complete = True
    result.pages = 1
    result.message = "城市月度指数，不能替代区县或楼盘成交价"
    return result


def collect_ygjy(url, region, client, config):
    result = SourceResult("ygjy", region["id"])
    try:
        # 先通过普通客户端核实 robots 并留存查询入口。
        client.get(url)
        api_url = urljoin(url, "/ysqgk/Api/WebApi/fdcxmxxlb.ashx")
        period = datetime.now(ZoneInfo(config["timezone"])).date().isoformat()
        page = 1
        total_pages = 1
        total_num = 0
        seen = set()
        max_pages = config.get("max_pages", 30)
        with BrowserSession(config) as browser:
            browser.ygjy_search(url, region["district"])
            while page <= total_pages:
                if page > max_pages:
                    result.warnings.append(f"分页超过上限 {max_pages}，本次仅部分覆盖")
                    break
                params = {"sProjectAddress": region["district"], "page": page, "pageSize": 99}
                raw = browser.fetch_json(api_url, params, method="POST")
                client.save_raw(api_url, raw, method="POST", content_type="application/json; charset=utf-8")
                payload = json.loads(raw)
                status = payload.get("status")
                if status not in (None, 0, 1, "0", "1"):
                    raise SourceError(f"阳光家缘接口状态异常：{status} {payload.get('message', '')}", "schema_changed")
                total_pages = int(payload.get("totalPage") or total_pages or 1)
                total_num = max(total_num, int(payload.get("totalNum") or 0))
                rows = ygjy_records(payload, api_url, region, period)
                if total_num and not rows:
                    raise SourceError("阳光家缘分页没有返回项目记录", "schema_changed")
                seen.update(o.source_id for o in rows)
                result.records.extend(rows)
                result.pages = page
                result.discovered = max(total_num, len(seen))
                result.eligible = len(seen)
                page += 1
                if page <= total_pages:
                    sleep(max(0.5, config.get("request_interval_seconds", 2)))
        result.pages = page - 1
        result.discovered = total_num
        result.eligible = len(seen)
        result.complete = page - 1 == total_pages and total_pages <= max_pages
        if result.complete and result.records:
            result.status = "ok"
            result.message = "阳光家缘项目住宅已售/未售套数；查询验证码已在浏览器流程中处理"
        elif result.records:
            result.status = "partial"
            result.message = "阳光家缘项目记录部分完成，不能宣称全区完整覆盖"
        else:
            raise SourceError("阳光家缘未返回可用项目记录", "schema_changed")
    except SourceError as exc:
        result.status = "partial" if result.records else exc.status
        result.message = str(exc)
    except Exception as exc:
        result.status = "partial" if result.records else "error"
        result.message = f"{type(exc).__name__}: {exc}"
    return result

def collect_source(source, url, region, client, config, store):
    try:
        if source in ("fang", "lianjia"):
            return collect_list(source, url, region, client, config, store)
        if source == "nbs":
            return collect_nbs(url, region, client)
        if source == "ygjy":
            return collect_ygjy(url, region, client, config)
        result = SourceResult(source, region["id"])
        html = client.get(url)
        endpoints = re.findall(r"url\s*:\s*['\"](/ysqgk/Api/WebApi/mrxjspf(?:ks|ws|qy)xx\.ashx)['\"]", html)
        if endpoints:
            for endpoint in dict.fromkeys(endpoints):
                api_url = urljoin(url, endpoint)
                label = 'available' if 'ksxx' in endpoint else 'unsold' if 'wsxx' in endpoint else 'signed'
                try:
                    result.records.extend(official_json(json.loads(client.get(api_url, method='POST')),label,api_url,region))
                except SourceError as exc:
                    result.status, result.message = 'partial' if result.records else exc.status, str(exc)
                    result.warnings.append(str(exc))
                    if exc.status == 'blocked':
                        break
            if result.status != 'ok':
                return result
        else:
            result.records = official_stats(html, url, region)
        result.complete, result.pages = True, 1
        result.discovered = result.eligible = 1
        result.message = "区级住宅数量与面积，无可靠成交金额时不计算成交价"
        return result
    except SourceError as exc:
        return SourceResult(source, region["id"], exc.status, str(exc))
    except Exception as exc:
        return SourceResult(source, region["id"], "error", f"{type(exc).__name__}: {exc}")
