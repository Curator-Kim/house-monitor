import json
from pathlib import Path
from datetime import time
from zoneinfo import ZoneInfo
from .cities import build_region

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

def save_config(config, path=None):
    path = Path(path or config["config_path"]).resolve()
    payload = {key: value for key, value in config.items() if key not in ("data_dir", "config_path")}
    data_dir = Path(config["data_dir"])
    try:
        payload["data_dir"] = str(data_dir.relative_to(path.parent))
    except ValueError:
        payload["data_dir"] = str(data_dir)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(path)


def add_region(config_path, city, district="", enabled=True):
    config = load_config(config_path)
    region = build_region(city, district)
    region["enabled"] = bool(enabled)
    for existing in config["regions"]:
        if existing["city"] == region["city"] and existing["district"] == region["district"]:
            return {"region": existing, "created": False, "config_path": config["config_path"]}
    config["regions"].append(region)
    save_config(config)
    return {"region": region, "created": True, "config_path": config["config_path"]}