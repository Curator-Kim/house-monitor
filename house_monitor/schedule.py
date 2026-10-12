import secrets
from datetime import datetime, timedelta, time
from pathlib import Path
from zoneinfo import ZoneInfo
from filelock import FileLock
from .storage import Store
from .service import collect


def daily_target(store, config, current, chooser=secrets.randbelow):
    current = current.astimezone(ZoneInfo(config["timezone"]))
    day = current.date().isoformat()
    with store.connect() as c:
        existing = c.execute("SELECT * FROM schedules WHERE day=?", (day,)).fetchone()
        if existing:
            return dict(existing)
        start = datetime.combine(current.date(), time.fromisoformat(config["schedule_start"]), current.tzinfo)
        end = datetime.combine(current.date(), time.fromisoformat(config["schedule_end"]), current.tzinfo)
        target = start + timedelta(seconds=chooser(int((end - start).total_seconds()) + 1))
        c.execute("INSERT INTO schedules(day,target) VALUES (?,?)", (day, target.isoformat()))
        return dict(c.execute("SELECT * FROM schedules WHERE day=?", (day,)).fetchone())


def tick(config, current=None, collector=collect):
    root = Path(config["data_dir"])
    root.mkdir(parents=True, exist_ok=True)
    with FileLock(str(root / "collect.lock"), timeout=0):
        store = Store(root)
        current = current or datetime.now(ZoneInfo(config["timezone"]))
        current = current.astimezone(ZoneInfo(config["timezone"]))
        row = daily_target(store, config, current)
        if row["state"] in ("done", "failed"):
            return {"state": row["state"], "target": row["target"], "run_id": row["run_id"]}
        if current < datetime.fromisoformat(row["target"]):
            return {"state": "waiting", "target": row["target"]}
        # 每天最多两次整轮尝试；来源部分成功当天结束，失败需手动重试。
        if row["attempts"] >= 2:
            with store.connect() as c:
                c.execute("UPDATE schedules SET state='failed',finished=? WHERE day=?", (current.isoformat(), row["day"]))
            return {"state": "failed", "target": row["target"]}
        with store.connect() as c:
            c.execute("UPDATE schedules SET state='running',attempts=attempts+1 WHERE day=?", (row["day"],))
        try:
            result = collector(config, mode="scheduled", locked=True)
        except Exception:
            with store.connect() as c:
                c.execute("UPDATE schedules SET state=? WHERE day=?", ("pending" if row["attempts"] == 0 else "failed", row["day"]))
            raise
        with store.connect() as c:
            c.execute("UPDATE schedules SET state='done',run_id=?,finished=? WHERE day=?",
                      (result["run_id"], current.isoformat(), row["day"]))
        return {"state": "done", "target": row["target"], **result}
