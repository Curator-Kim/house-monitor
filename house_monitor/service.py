import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from filelock import FileLock
from .http import Client
from .storage import Store
from .sources import collect_source


def now(config):
    return datetime.now(ZoneInfo(config["timezone"]))


def collect(config, region_id=None, mode="manual", locked=False):
    root = Path(config["data_dir"])
    root.mkdir(parents=True, exist_ok=True)
    if not locked:
        with FileLock(str(root / "collect.lock"), timeout=0):
            return collect(config, region_id, mode, locked=True)
    store = Store(root)
    stamp = now(config).isoformat(timespec="seconds")
    run_id = store.begin(stamp, mode)
    results = []
    client = Client(config, run_id)
    logging.basicConfig(filename=root / "monitor.log", encoding="utf-8", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    try:
        regions = [r for r in config["regions"] if r.get("enabled") and (not region_id or r["id"] == region_id)]
        if not regions:
            raise ValueError("没有启用的地区")
        for region in regions:
            for source, url in region["sources"].items():
                logging.info("开始采集 %s %s", region["id"], source)
                result = collect_source(source, url, region, client, config, store)
                store.save_result(run_id, result, now(config).isoformat(timespec="seconds"))
                results.append(result)
                logging.info("采集结果 %s %s %s %s", region["id"], source, result.status, result.message)
        statuses = [r.status for r in results]
        status = "ok" if all(s == "ok" for s in statuses) else "partial" if any(r.records for r in results) else "failed"
        message = "; ".join(f"{r.region_id}/{r.source}: {r.status}, {r.eligible}个符合条件的项目" for r in results)
        store.finish(run_id, now(config).isoformat(timespec="seconds"), status, message)
    except Exception as exc:
        store.finish(run_id, now(config).isoformat(timespec="seconds"), "failed", str(exc))
        raise
    report = {"run_id": run_id, "status": status, "message": message,
              "sources": store.rows("SELECT * FROM source_runs WHERE run_id=?", (run_id,)),
              "validation": store.gates()}
    (root / "latest_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
