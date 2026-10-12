import json
from pathlib import Path
from datetime import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent


def load_config(path=None):
    path = Path(path or ROOT / "config.json").resolve()
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    config["data_dir"] = str((path.parent / config["data_dir"]).resolve())
    config["config_path"] = str(path)
    ZoneInfo(config["timezone"])
    if time.fromisoformat(config["schedule_start"]) > time.fromisoformat(config["schedule_end"]):
        raise ValueError("采集时间窗口不能跨日")
    if len({r["id"] for r in config["regions"]}) != len(config["regions"]):
        raise ValueError("地区编号重复")
    for region in config["regions"]:
        if region.get("enabled") and set(region["sources"]) - {"fang", "lianjia", "official", "nbs", "ygjy"}:
            raise ValueError("配置包含尚未实现的数据源")
    return config
