import json

import pytest
from house_monitor.config import add_region, load_config
from house_monitor.cities import build_region
from house_monitor.http import SourceError


def _config(path):
    path.write_text(json.dumps({
        "data_dir": "data",
        "timezone": "Asia/Shanghai",
        "schedule_start": "09:00:00",
        "schedule_end": "12:00:00",
        "request_interval_seconds": 2,
        "request_timeout_seconds": 20,
        "max_pages": 120,
        "history_enabled": False,
        "regions": [],
    }, ensure_ascii=False), encoding="utf-8")


def test_add_region_builds_city_sources(tmp_path):
    path = tmp_path / "config.json"
    _config(path)
    result = add_region(path, "深圳", "南山区")
    assert result["created"] is True
    config = load_config(path)
    region = config["regions"][0]
    assert region["id"] == "sz-南山区"
    assert region["sources"]["fang"] == "https://sz.newhouse.fang.com/house/s/"
    assert region["sources"]["lianjia"] == "https://sz.fang.lianjia.com/loupan/"
    assert "ygjy" not in region["sources"]
    assert add_region(path, "深圳", "南山区")["created"] is False
    assert len(load_config(path)["regions"]) == 1


def test_add_guangzhou_district_adds_official_sources(tmp_path):
    path = tmp_path / "config.json"
    _config(path)
    add_region(path, "广州", "天河")
    region = load_config(path)["regions"][0]
    assert region["sources"]["ygjy"].endswith("/zfcj/fyxx/fdcxmxx/index.html")
    assert region["sources"]["official"].endswith("/zfcj/tjxx/spfxstjxx/")

def test_city_slug_validation():
    with pytest.raises(SourceError):
        build_region({"name": "测试", "slug": "bad/path"})