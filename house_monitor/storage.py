import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
 id INTEGER PRIMARY KEY, started TEXT NOT NULL, finished TEXT, mode TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'running', message TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS source_runs (
 run_id INTEGER, source TEXT, region_id TEXT, day TEXT, status TEXT, message TEXT,
 discovered INTEGER, eligible INTEGER, parsed INTEGER, missing INTEGER,
 pages INTEGER, complete INTEGER, warnings TEXT,
 PRIMARY KEY(run_id, source, region_id));
CREATE TABLE IF NOT EXISTS projects (
 id INTEGER PRIMARY KEY, region_id TEXT, name TEXT, address TEXT, official_id TEXT,
 presell TEXT, match_status TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS source_projects (
 source TEXT, source_id TEXT, region_id TEXT, project_id INTEGER,
 name TEXT, address TEXT, property_type TEXT, sale_status TEXT, url TEXT,
 last_seen TEXT, PRIMARY KEY(source, source_id, region_id));
CREATE TABLE IF NOT EXISTS observations (
 id INTEGER PRIMARY KEY, run_id INTEGER, project_id INTEGER, region_id TEXT,
 source TEXT, source_id TEXT, name TEXT, kind TEXT, value REAL, value_high REAL,
 unit TEXT, raw_price TEXT, observed_at TEXT, source_updated TEXT,
 period TEXT, granularity TEXT, missing_reason TEXT, url TEXT, extra TEXT,
 UNIQUE(region_id, source, source_id, kind, period, granularity));
CREATE TABLE IF NOT EXISTS observation_revisions (
 id INTEGER PRIMARY KEY, observation_id INTEGER, replaced_at TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS schedules (
 day TEXT PRIMARY KEY, target TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
 attempts INTEGER NOT NULL DEFAULT 0, run_id INTEGER, finished TEXT);
CREATE TABLE IF NOT EXISTS quality_checks (
 source TEXT, region_id TEXT, source_id TEXT, checked_at TEXT, note TEXT,
 PRIMARY KEY(source, region_id, source_id));
CREATE INDEX IF NOT EXISTS obs_filter ON observations(region_id, granularity, period, source);
"""


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "houses.sqlite3"
        with self.connect() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA journal_mode=WAL")
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def rows(self, sql, params=()):
        with self.connect() as c:
            return [dict(r) for r in c.execute(sql, params).fetchall()]

    def begin(self, started, mode):
        with self.connect() as c:
            # 上次进程在持有锁时退出，日志不能永远显示运行中。
            c.execute("UPDATE runs SET status='interrupted', finished=? WHERE status='running'", (started,))
            return c.execute("INSERT INTO runs(started,mode) VALUES (?,?)", (started, mode)).lastrowid

    def finish(self, run_id, finished, status, message):
        with self.connect() as c:
            c.execute("UPDATE runs SET finished=?,status=?,message=? WHERE id=?", (finished, status, message, run_id))

    def _project(self, c, o, now):
        existing = c.execute("SELECT project_id FROM source_projects WHERE source=? AND source_id=? AND region_id=?",
                             (o.source, o.source_id, o.region_id)).fetchone()
        if existing:
            project_id = existing[0]
        else:
            # 不按同名或模糊地址自动合并，避免期次与别名误合并。
            match = None
            for field in ("official_id", "presell"):
                value = getattr(o, field)
                if value:
                    matches = c.execute(f"SELECT id FROM projects WHERE region_id=? AND {field}=?", (o.region_id, value)).fetchall()
                    if len(matches) == 1:
                        match = matches[0][0]
                        break
            project_id = match or c.execute(
                "INSERT INTO projects(region_id,name,address,official_id,presell,match_status,created) VALUES (?,?,?,?,?,?,?)",
                (o.region_id, o.name, o.address, o.official_id, o.presell,
                 "official" if o.official_id or o.presell else "source_only", now)).lastrowid
        c.execute("""INSERT INTO source_projects VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source,source_id,region_id) DO UPDATE SET name=excluded.name,
            address=excluded.address,property_type=excluded.property_type,sale_status=excluded.sale_status,
            url=excluded.url,last_seen=excluded.last_seen""",
                  (o.source, o.source_id, o.region_id, project_id, o.name, o.address,
                   o.property_type, o.sale_status, o.url, now))
        return project_id

    def save_result(self, run_id, result, now):
        with self.connect() as c:
            for o in result.records:
                project_id = self._project(c, o, now)
                period = o.period or now[:10]
                existing = c.execute("SELECT * FROM observations WHERE region_id=? AND source=? AND source_id=? AND kind=? AND period=? AND granularity=?",
                                     (o.region_id, o.source, o.source_id, o.kind, period, o.granularity)).fetchone()
                if existing and existing["value"] is not None and o.value is None:
                    continue
                payload = (run_id, project_id, o.region_id, o.source, o.source_id, o.name, o.kind,
                           o.value, o.value_high, o.unit, o.raw_price, now, o.source_updated, period,
                           o.granularity, o.missing_reason, o.url, json.dumps(o.extra, ensure_ascii=False))
                if existing:
                    c.execute("INSERT INTO observation_revisions(observation_id,replaced_at,payload) VALUES (?,?,?)",
                              (existing["id"], now, json.dumps(dict(existing), ensure_ascii=False)))
                    c.execute("DELETE FROM observations WHERE id=?", (existing["id"],))
                c.execute("""INSERT INTO observations(run_id,project_id,region_id,source,source_id,name,kind,
                    value,value_high,unit,raw_price,observed_at,source_updated,period,granularity,missing_reason,url,extra)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", payload)
            c.execute("INSERT OR REPLACE INTO source_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (run_id, result.source, result.region_id, now[:10], result.status, result.message,
                       result.discovered, result.eligible,
                       len({o.source_id for o in result.records if o.granularity == 'snapshot'}),
                       len({o.source_id for o in result.records if o.granularity == 'snapshot' and o.value is None}),
                       result.pages, int(result.complete), json.dumps(result.warnings, ensure_ascii=False)))

    def observations(self, region_id=None):
        sql = """SELECT o.*,p.match_status,p.official_id AS official_id,p.presell AS presell,s.address,s.property_type,s.sale_status FROM observations o
                 JOIN projects p ON p.id=o.project_id
                 JOIN source_projects s ON s.source=o.source AND s.source_id=o.source_id AND s.region_id=o.region_id"""
        return self.rows(sql + (" WHERE o.region_id=?" if region_id else ""), (region_id,) if region_id else ())

    def gates(self):
        # 连续三天完整采集 + 至少10个独立项目人工抽查通过（不足则全查）。
        from datetime import date, timedelta
        results = []
        for item in self.rows("SELECT DISTINCT source,region_id FROM source_runs"):
            source, region = item["source"], item["region_id"]
            days = self.rows("SELECT DISTINCT day FROM source_runs WHERE source=? AND region_id=? AND status='ok' AND complete=1 ORDER BY day DESC", (source, region))
            count = 0
            if days:
                latest = date.fromisoformat(days[0]["day"])
                day_set = {d["day"] for d in days}
                while (latest - timedelta(days=count)).isoformat() in day_set:
                    count += 1
            project_count = self.rows("SELECT count(*) n FROM source_projects WHERE source=? AND region_id=?", (source, region))[0]["n"]
            checked = self.rows("SELECT count(*) n FROM quality_checks WHERE source=? AND region_id=?", (source, region))[0]["n"]
            required = min(10, project_count)
            ready = count >= 3 and (source not in ("fang", "lianjia") or required > 0 and checked >= required)
            results.append({**item, "consecutive_days": count, "checked": checked,
                            "required": required, "stage": "verified" if ready else "provisional",
                            "seven_day_ready": ready and count >= 7})
        return results
