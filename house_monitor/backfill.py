"""历史数据回补：只写入来源真实提供的历史记录，不生成虚构日期。"""
import re
from datetime import datetime
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from filelock import FileLock

from .http import Client, SourceError
from .models import SourceResult
from .parsers import fang_history, nbs_indices
from .storage import Store

NBS_TITLE = re.compile(r"(\d{4})年(\d{1,2})月份70个大中城市商品住宅销售价格变动情况")


def _now(config):
    return datetime.now(ZoneInfo(config["timezone"]))


def _nbs_links(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    links = {}
    for anchor in soup.select("a[href]"):
        match = NBS_TITLE.search(anchor.get_text(" ", strip=True))
        if match:
            links[(int(match[1]), int(match[2]))] = urljoin(base_url, anchor["href"])
    return links


def _nbs_existing(store, region_id):
    rows = store.rows("SELECT DISTINCT period FROM observations WHERE source='nbs' AND region_id=?", (region_id,))
    return {row["period"] for row in rows}


def backfill_nbs(config, regions, months=36, pages=120):
    store = Store(config["data_dir"])
    regions = [r for r in regions if r.get("sources", {}).get("nbs")]
    if not regions:
        raise SourceError("没有可用于回补的统计局来源配置", "config_invalid")
    lock = FileLock(str(store.directory / "collect.lock"), timeout=0)
    with lock:
        started = _now(config)
        run_id = store.begin(started.isoformat(timespec="seconds"), "backfill-nbs")
        client = Client(config, run_id)
        total_records = 0
        fetched_articles = 0
        warnings = []
        collected = {region["id"]: [] for region in regions}
        try:
            base_url = regions[0]["sources"]["nbs"]
            current = (started.year, started.month)
            target_index = current[0] * 12 + current[1] - 1 - months
            links = {}
            for page in range(max(1, pages)):
                page_url = base_url if page == 0 else urljoin(base_url, f"index_{page}.html")
                links.update(_nbs_links(client.get(page_url), page_url))
                if links and min(links)[0] * 12 + min(links)[1] - 1 <= target_index:
                    break
            selected = sorted(((key, url) for key, url in links.items()
                               if key[0] * 12 + key[1] - 1 >= target_index), reverse=True)
            existing = {region["id"]: _nbs_existing(store, region["id"]) for region in regions}
            for (year, month), article_url in selected[:months]:
                period = f"{year}-{month:02d}"
                pending = [region for region in regions if period not in existing[region["id"]]]
                if not pending:
                    continue
                try:
                    html = client.get(article_url)
                except SourceError as exc:
                    warnings.append(f"{period} 文章获取失败：{exc}")
                    continue
                fetched_articles += 1
                for region in pending:
                    try:
                        records = nbs_indices(html, article_url, region)
                    except SourceError as exc:
                        warnings.append(f"{period} {region['city']} 解析失败：{exc}")
                        continue
                    collected[region["id"]].extend(records)
            stamp = _now(config).isoformat(timespec="seconds")
            for region in regions:
                records = collected[region["id"]]
                result = SourceResult("nbs", region["id"], records=records, discovered=1, eligible=1,
                                      pages=fetched_articles, complete=not warnings,
                                      message=f"历史回补统计局月度指数：{len(records)} 条")
                result.warnings = list(warnings)
                result.status = "ok" if records and not warnings else ("partial" if records else "error")
                store.save_result(run_id, result, stamp)
                total_records += len(records)
            message = f"统计局历史回补完成：写入 {total_records} 条月度指数，文章 {fetched_articles} 篇，警告 {len(warnings)} 条"
            store.finish(run_id, _now(config).isoformat(timespec="seconds"), "ok" if total_records else "failed", message)
        except Exception as exc:
            store.finish(run_id, _now(config).isoformat(timespec="seconds"), "failed", str(exc))
            raise
    return {"run_id": run_id, "status": "ok" if total_records else "failed", "records": total_records,
            "articles": fetched_articles, "warnings": warnings, "message": message}


def backfill_fang_history(config, regions, limit=None):
    store = Store(config["data_dir"])
    lock = FileLock(str(store.directory / "collect.lock"), timeout=0)
    with lock:
        started = _now(config)
        run_id = store.begin(started.isoformat(timespec="seconds"), "backfill-fang")
        client = Client(config, run_id)
        summary = []
        try:
            for region in regions:
                source_url = region.get("sources", {}).get("fang")
                if not source_url:
                    continue
                pending = store.rows("""SELECT source_id,name FROM source_projects
                    WHERE source='fang' AND region_id=? AND NOT EXISTS (
                      SELECT 1 FROM observations o WHERE o.source='fang' AND o.region_id=source_projects.region_id
                      AND o.source_id=source_projects.source_id AND o.granularity='event')
                    ORDER BY source_id""", (region["id"],))
                if limit:
                    pending = pending[:limit]
                parts = urlsplit(source_url)
                origin = f"{parts.scheme}://{parts.netloc}"
                records, warnings, blocked_streak, with_events = [], [], 0, 0
                for item in pending:
                    history_url = urljoin(origin, f"/loupan/{item['source_id']}/fangjia.htm")
                    try:
                        events = fang_history(client.get(history_url), item["source_id"], item["name"],
                                              history_url, region["id"])
                    except SourceError as exc:
                        warnings.append(f"{item['name']}：{exc}")
                        blocked_streak = blocked_streak + 1 if exc.status in ("blocked", "captcha_failed") else 0
                        if blocked_streak >= 5:
                            warnings.append("连续访问受限，停止该地区剩余项目的回补")
                            break
                        continue
                    blocked_streak = 0
                    if events:
                        with_events += 1
                        records.extend(events)
                result = SourceResult("fang", region["id"], records=records, discovered=len(pending),
                                      eligible=with_events, pages=len(pending), complete=not warnings,
                                      message=f"房天下历史价格回补：检查 {len(pending)} 个项目，{with_events} 个取得历史记录")
                result.warnings = warnings
                result.status = "ok" if not warnings else ("partial" if records else "error")
                store.save_result(run_id, result, _now(config).isoformat(timespec="seconds"))
                summary.append({"region_id": region["id"], "projects": len(pending),
                                "projects_with_events": with_events, "records": len(records),
                                "warnings": warnings})
            message = "房天下历史回补完成"
            store.finish(run_id, _now(config).isoformat(timespec="seconds"), "ok", message)
        except Exception as exc:
            store.finish(run_id, _now(config).isoformat(timespec="seconds"), "failed", str(exc))
            raise
    return {"run_id": run_id, "status": "ok", "summary": summary, "message": message}