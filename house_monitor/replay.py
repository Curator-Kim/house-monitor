"""重新解析已保存的 HTTP 响应；保持原始抓取时间，不伪造历史快照。"""
import json
from pathlib import Path
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from filelock import FileLock
from .http import decode, SourceError
from .models import SourceResult
from .parsers import fang_list, fang_history, lianjia_list, official_json, ygjy_records, nbs_indices
from .storage import Store


def _official_label(url):
    if "ksxx" in url:
        return "available"
    if "wsxx" in url:
        return "unsold"
    return "signed"


def _finalize(result, message):
    if result.source in ("fang", "lianjia"):
        result.discovered = result.discovered or result.eligible
        if result.complete and not result.records:
            result.status = "schema_changed"
            result.message = "未发现符合筛选的住宅，需人工核对"
            result.complete = False
        elif not result.complete and not result.records and result.status in ("blocked", "schema_changed", "error"):
            result.message = result.message or message
        else:
            result.status = "ok" if result.complete else "partial"
            result.message = message
    elif result.source == "ygjy":
        result.status = "ok" if result.complete and result.records else "partial" if result.records else "schema_changed"
        result.message = "阳光家缘项目住宅已售/未售套数，从原始响应重新解析"
    elif result.source == "official":
        result.discovered = result.eligible = 1 if result.records else 0
        result.status = "ok" if result.records else "schema_changed"
        result.message = "官方住宅数量与面积，无可靠成交金额时不计算成交价"
        result.complete = bool(result.records)
    elif result.source == "nbs":
        result.discovered = result.eligible = 1 if result.records else 0
        result.status = "ok" if result.records else "schema_changed"
        result.message = "城市月度指数，不能替代区县或楼盘成交价"
        result.complete = bool(result.records)


def replay(config, raw_run, region_id):
    store = Store(config["data_dir"])
    region = next(r for r in config["regions"] if r["id"] == region_id)
    root = Path(config["data_dir"]) / "raw" / str(int(raw_run))
    metadata = []
    for path in sorted(root.glob("*.json")):
        meta = json.loads(path.read_text(encoding="utf-8"))
        meta["body"] = decode(path.with_suffix(".body").read_bytes())
        metadata.append(meta)
    if not metadata:
        raise ValueError("没有找到原始响应")

    results = {}
    stamps = {}
    fang_rows = {}
    fang_ids = set()
    lianjia_rows = {}
    lianjia_ids = set()
    ygjy_rows = {}
    ygjy_ids = set()
    ygjy_pages = set()
    ygjy_total_pages = 0
    expected_fang_pages = None

    for meta in metadata:
        url = meta["requested_url"]
        if meta["status"] != 200 or meta["final_url"] != url:
            continue
        source = None
        try:
            path = urlsplit(url).path
            if "/house/s/" in path:
                source = "fang"
                result = results.setdefault(source, SourceResult(source, region_id))
                rows, ids, nxt, total = fang_list(meta["body"], url, region)
                fang_rows.update({o.source_id: o for o in rows})
                fang_ids |= ids
                result.pages += 1
                expected_fang_pages = total or expected_fang_pages
                result.complete = nxt is None and (not expected_fang_pages or result.pages == expected_fang_pages)
            elif "/fangjia.htm" in path:
                source = "fang"
                result = results.setdefault(source, SourceResult(source, region_id))
                source_id = url.split("/")[-2]
                if source_id in fang_rows:
                    result.records.extend(fang_history(meta["body"], source_id, fang_rows[source_id].name, url, region_id))
            elif "gz.fang.lianjia.com" in url and "/loupan" in path:
                source = "lianjia"
                result = results.setdefault(source, SourceResult(source, region_id))
                rows, ids, nxt, total = lianjia_list(meta["body"], url, region)
                lianjia_rows.update({o.source_id: o for o in rows})
                lianjia_ids |= ids
                result.pages += 1
                result.complete = nxt is None and (not total or result.pages == total)
            elif path.endswith("/fdcxmxxlb.ashx"):
                source = "ygjy"
                result = results.setdefault(source, SourceResult(source, region_id))
                payload = json.loads(meta["body"])
                fetched = datetime.fromisoformat(meta["fetched_at"]).astimezone(ZoneInfo(config["timezone"]))
                rows = ygjy_records(payload, url, region, fetched.date().isoformat())
                ygjy_rows.update({(o.source_id, o.kind, o.period): o for o in rows})
                ygjy_ids.update(o.source_id for o in rows)
                ygjy_pages.add(int(payload.get("currentPage") or 1))
                ygjy_total_pages = max(ygjy_total_pages, int(payload.get("totalPage") or 0))
                result.pages = len(ygjy_pages)
                result.complete = bool(ygjy_total_pages and len(ygjy_pages) >= ygjy_total_pages)
            elif "/ysqgk/Api/WebApi/mrxjspf" in path and path.endswith(".ashx"):
                source = "official"
                result = results.setdefault(source, SourceResult(source, region_id))
                rows = official_json(json.loads(meta["body"]), _official_label(url), url, region)
                result.records.extend(rows)
                result.pages += 1
                result.complete = True
            elif "stats.gov.cn" in url and "/t20" in path:
                source = "nbs"
                result = results.setdefault(source, SourceResult(source, region_id))
                result.records = nbs_indices(meta["body"], url, region)
                result.pages = 1
                result.complete = True
            if source:
                stamp = datetime.fromisoformat(meta["fetched_at"]).astimezone(ZoneInfo(config["timezone"])).isoformat(timespec="seconds")
                if source not in stamps or stamp > stamps[source]:
                    stamps[source] = stamp
        except SourceError as exc:
            if source in results:
                results[source].complete = False
                results[source].status = exc.status
                results[source].message = str(exc)
            if source:
                stamp = datetime.fromisoformat(meta["fetched_at"]).astimezone(ZoneInfo(config["timezone"])).isoformat(timespec="seconds")
                if source not in stamps or stamp > stamps[source]:
                    stamps[source] = stamp

    if "fang" in results:
        result = results["fang"]
        result.records = list(fang_rows.values()) + result.records
        result.discovered = len(fang_ids)
        result.eligible = len(fang_rows)
    if "lianjia" in results:
        result = results["lianjia"]
        result.records = list(lianjia_rows.values())
        result.discovered = len(lianjia_ids)
        result.eligible = len(lianjia_rows)
    if "ygjy" in results:
        result = results["ygjy"]
        result.records = list(ygjy_rows.values())
        result.discovered = result.eligible = len(ygjy_ids)

    for result in results.values():
        _finalize(result, "从原始响应重新解析，保留原始抓取时间；缺失分页不视为全量")

    with FileLock(str(store.directory / "collect.lock"), timeout=0):
        current = datetime.now(ZoneInfo(config["timezone"])).isoformat(timespec="seconds")
        run_id = store.begin(current, "replay")
        for source, result in results.items():
            store.save_result(run_id, result, stamps[source])
        status = "ok" if results and all(r.complete for r in results.values()) else "partial"
        store.finish(run_id, current, status, f"重新解析原始响应 {raw_run}")
    return {"run_id": run_id, "sources": store.rows("SELECT * FROM source_runs WHERE run_id=?", (run_id,))}