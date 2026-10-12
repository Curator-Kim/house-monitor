import argparse
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from filelock import Timeout
from .config import load_config
from .service import collect
from .schedule import tick, daily_target
from .storage import Store
from .analytics import frame, csv_bytes, excel_bytes


def main():
    parser = argparse.ArgumentParser(description="住宅报价采集与调度")
    parser.add_argument("--config", help="配置文件路径")
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("collect", help="手动采集（当日同来源同指标去重）")
    c.add_argument("--region")
    sub.add_parser("tick", help="检查当日随机时刻，到期采集")
    sub.add_parser("status", help="查看运行及验证阶段")
    sub.add_parser("plan-day", help="生成并查看当天持久化随机时刻")
    replay_parser = sub.add_parser("replay", help="重新解析原始响应，保留真实抓取时间")
    replay_parser.add_argument("--raw-run", type=int, required=True)
    replay_parser.add_argument("--region", required=True)
    e = sub.add_parser("export")
    e.add_argument("--region")
    e.add_argument("--output", default="exports/observations.xlsx")
    q = sub.add_parser("check", help="核对原页面后记录一项人工抽查")
    q.add_argument("--source", required=True, choices=["fang", "lianjia", "official", "nbs"])
    q.add_argument("--region", required=True)
    q.add_argument("--source-id", required=True)
    q.add_argument("--note", required=True)
    args = parser.parse_args()
    config = load_config(args.config)
    store = Store(config["data_dir"])
    try:
        if args.command == "collect":
            result = collect(config, args.region)
        elif args.command == "tick":
            result = tick(config)
        elif args.command == "plan-day":
            from filelock import FileLock
            with FileLock(str(Path(config["data_dir"]) / "collect.lock"), timeout=0):
                result = daily_target(store, config, datetime.now(ZoneInfo(config["timezone"])))
        elif args.command == "status":
            result = {"runs": store.rows("SELECT * FROM runs ORDER BY id DESC LIMIT 10"),
                      "sources": store.rows("SELECT * FROM source_runs ORDER BY run_id DESC LIMIT 20"),
                      "validation": store.gates(), "schedules": store.rows("SELECT * FROM schedules ORDER BY day DESC LIMIT 7")}
        elif args.command == "replay":
            from .replay import replay
            result = replay(config, args.raw_run, args.region)
        elif args.command == "check":
            if not store.rows("SELECT * FROM source_projects WHERE source=? AND region_id=? AND source_id=?", (args.source, args.region, args.source_id)):
                parser.error("没有找到该来源项目")
            with store.connect() as db:
                db.execute("INSERT OR REPLACE INTO quality_checks VALUES (?,?,?,?,?)", (args.source, args.region, args.source_id,
                    datetime.now(ZoneInfo(config["timezone"])).isoformat(), args.note))
            result = store.gates()
        else:
            data = frame(store, args.region)
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            if output.suffix.lower() not in (".csv", ".xlsx"):
                parser.error("导出仅支持 .csv 或 .xlsx")
            output.write_bytes(csv_bytes(data) if output.suffix.lower() == ".csv" else excel_bytes(data))
            result = {"output": str(output.resolve()), "rows": len(data)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Timeout:
        print("其他采集进程正在运行，本次跳过")


if __name__ == "__main__":
    main()
