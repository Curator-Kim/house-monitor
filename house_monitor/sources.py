import re
import json
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
from .models import SourceResult
from .http import SourceError
from .parsers import fang_list, fang_history, lianjia_list, official_stats, official_json, nbs_indices, text


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


def collect_source(source, url, region, client, config, store):
    try:
        if source in ("fang", "lianjia"):
            return collect_list(source, url, region, client, config, store)
        if source == "nbs":
            return collect_nbs(url, region, client)
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
