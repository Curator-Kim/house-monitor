"""预置城市清单；数据源地址基于城市域名标识动态生成。"""
import re
from .http import SourceError

NBS_URL = "https://www.stats.gov.cn/sj/zxfb/"

CITY_CATALOG = [
    {"name": "广州", "slug": "gz", "province": "广东"},
    {"name": "深圳", "slug": "sz", "province": "广东"},
    {"name": "北京", "slug": "bj", "province": "北京"},
    {"name": "上海", "slug": "sh", "province": "上海"},
    {"name": "杭州", "slug": "hz", "province": "浙江"},
    {"name": "南京", "slug": "nj", "province": "江苏"},
    {"name": "苏州", "slug": "su", "province": "江苏"},
    {"name": "成都", "slug": "cd", "province": "四川"},
    {"name": "重庆", "slug": "cq", "province": "重庆"},
    {"name": "武汉", "slug": "wh", "province": "湖北"},
    {"name": "长沙", "slug": "cs", "province": "湖南"},
    {"name": "郑州", "slug": "zz", "province": "河南"},
    {"name": "天津", "slug": "tj", "province": "天津"},
    {"name": "西安", "slug": "xa", "province": "陕西"},
    {"name": "青岛", "slug": "qd", "province": "山东"},
    {"name": "济南", "slug": "jn", "province": "山东"},
    {"name": "合肥", "slug": "hf", "province": "安徽"},
    {"name": "厦门", "slug": "xm", "province": "福建"},
    {"name": "福州", "slug": "fz", "province": "福建"},
    {"name": "昆明", "slug": "km", "province": "云南"},
    {"name": "南昌", "slug": "nc", "province": "江西"},
    {"name": "贵阳", "slug": "gy", "province": "贵州"},
    {"name": "南宁", "slug": "nn", "province": "广西"},
    {"name": "海口", "slug": "hk", "province": "海南"},
    {"name": "大连", "slug": "dl", "province": "辽宁"},
    {"name": "沈阳", "slug": "sy", "province": "辽宁"},
    {"name": "宁波", "slug": "nb", "province": "浙江"},
    {"name": "无锡", "slug": "wx", "province": "江苏"},
    {"name": "佛山", "slug": "fs", "province": "广东"},
    {"name": "东莞", "slug": "dg", "province": "广东"},
    {"name": "珠海", "slug": "zh", "province": "广东"},
    {"name": "中山", "slug": "zs", "province": "广东"},
]


def city_by_name(name):
    for city in CITY_CATALOG:
        if city["name"] == name:
            return dict(city)
    raise SourceError(f"城市清单中没有 {name}", "config_invalid")


def build_region(city, district=""):
    if isinstance(city, str):
        city = city_by_name(city)
    slug = str(city.get("slug") or "").strip().lower()
    name = str(city.get("name") or "").strip()
    if not name or not re.fullmatch(r"[a-z0-9-]+", slug):
        raise SourceError("城市名称不能为空，域名标识只能包含小写字母、数字和连字符", "config_invalid")
    district = (district or "").strip() or "全市"
    sources = {
        "fang": f"https://{slug}.newhouse.fang.com/house/s/",
        "lianjia": f"https://{slug}.fang.lianjia.com/loupan/",
        "nbs": NBS_URL,
    }
    if slug == "gz" and district != "全市":
        sources["ygjy"] = "https://zfcj.gz.gov.cn/zfcj/fyxx/fdcxmxx/index.html"
        sources["official"] = "https://zfcj.gz.gov.cn/zfcj/tjxx/spfxstjxx/"
    return {"id": f"{slug}-{district}", "city": name, "district": district,
            "enabled": True, "sources": sources}