import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from .models import Observation
from .http import SourceError


def price(raw):
    compact = re.sub(r"\s+", "", raw).replace(",", "").replace("，", "")
    base = {"kind": "reference_unit", "value": None, "value_high": None,
            "unit": "元/平方米", "raw_price": raw, "missing_reason": None}
    if not compact or any(x in compact for x in ("待定", "暂无", "面议", "已售完")):
        base["missing_reason"] = "来源未提供价格"
        return base
    total = "元/套" in compact or "总价" in compact
    per_area = any(x in compact for x in ("/㎡", "/平方米", "/平", "/m²", "/m2", "/m²"))
    if not total and not per_area:
        base["kind"] = "unknown"
        base["unit"] = "未知"
        base["missing_reason"] = "无法确认价格单位"
        return base
    numbers = re.search(r"(\d+(?:\.\d+)?)(?:[~～\-–至](\d+(?:\.\d+)?))?", compact)
    if not numbers:
        base["missing_reason"] = "无法解析价格"
        return base
    low, high = float(numbers[1]), float(numbers[2]) if numbers[2] else None
    multiplier = 10000 if "万" in compact[numbers.end():] else 1
    base.update(value=low * multiplier, value_high=high * multiplier if high is not None else None,
                unit="元/套" if total else "元/平方米")
    base["kind"] = ("reference_total" if total else "reference_unit") + ("_range" if high is not None else "_starting" if "起" in compact else "")
    if low <= 0 or high is not None and high < low:
        base.update(value=None, value_high=None, missing_reason="价格数值异常")
    return base


def text(node):
    return node.get_text(" ", strip=True) if node else ""


def fang_list(html, url, region):
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("#newhouse_loupan_list > ul > li[id^=lp_]")
    if not cards:
        raise SourceError("房天下列表结构变化或没有可验证的项目列表", "schema_changed")
    records, seen = [], set()
    for card in cards:
        source_id = card["id"][3:]
        if source_id in seen:
            continue
        seen.add(source_id)
        name_node = card.select_one(".nlcd_name a")
        address = text(card.select_one(".address"))
        tags = text(card.select_one(".fangyuan"))
        if not name_node or not address or not tags:
            raise SourceError(f"项目 {source_id} 缺少必要字段", "schema_changed")
        if f"[{region['district']}]" not in address.replace(" ", ""):
            continue
        if not card.select_one(".inSale") or "在售" not in tags or not any(t in tags for t in ("住宅", "别墅", "洋房", "叠拼", "联排", "独栋")):
            continue
        primary = card.select_one(".nhouse_price")
        raw = text(primary)
        props = [text(a) for a in card.select(".fangyuan a")]
        addr_link = card.select_one(".address a")
        address = addr_link.get("title", address) if addr_link else address
        records.append(Observation("fang", source_id, text(name_node), urljoin(url, name_node["href"]), region["id"],
                                   address=address, property_type="、".join(props),
                                   extra={"tags": tags, "total_price_text": text(card.select_one(".zj_price")), "list_url": url}, **price(raw)))
    page_links = []
    for a in soup.select("a[href]"):
        if text(a) in ("下一页", ">", "›", "下一页 >"):
            link = urljoin(url, a["href"])
            if "/house/s/" in link:
                page_links.append(link)
    pagination = re.search(r"(\d+)\s*/\s*(\d+)", text(soup))
    current, total = (int(pagination[1]), int(pagination[2])) if pagination else (None, None)
    if total and current < total and not page_links:
        raise SourceError("分页存在但下一页链接缺失", "schema_changed")
    return records, seen, page_links[0] if page_links else None, total


def fang_history(html, source_id, name, url, region_id):
    soup = BeautifulSoup(html, "html.parser")
    records = []
    # 仅解析日期所在行，避免把区域/推荐楼盘价格混入该项目。
    for date_node in soup.find_all(string=re.compile(r"^\s*\d{4}-\d{2}-\d{2}\s*$")):
        node = date_node.parent
        for _ in range(5):
            if node is None:
                break
            content = text(node)
            if "元/" in content and len(re.findall(r"\d{4}-\d{2}-\d{2}", content)) == 1:
                date = re.search(r"\d{4}-\d{2}-\d{2}", content)[0]
                match = re.search(r"\d[\d,.]*(?:[~～\-]\d[\d,.]*)?\s*(?:万)?元/(?:平方米|㎡|套)(?:起)?", content)
                if match:
                    records.append(Observation("fang", source_id, name, url, region_id,
                                               period=date, source_updated=date, granularity="event",
                                               extra={"description": content}, **price(match[0])))
                break
            node = node.parent
    unique = {(r.period, r.kind): r for r in records}
    return list(unique.values())


def lianjia_list(html, url, region):
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(".resblock-list")
    if not cards:
        raise SourceError("链家列表结构未通过验证", "schema_changed")
    records, seen = [], set()
    for card in cards:
        a = card.select_one(".resblock-name a")
        if not a:
            raise SourceError("链家楼盘名称缺失", "schema_changed")
        m = re.search(r"/loupan/(p_[^/]+)/", a.get("href", ""))
        if not m:
            continue
        seen.add(m[1])
        location = text(card.select_one(".resblock-location"))
        kind = text(card.select_one(".resblock-type"))
        sale = text(card.select_one(".sale-status"))
        if region["district"] not in location or sale != "在售" or kind not in ("住宅", "别墅"):
            continue
        main = card.select_one(".main-price")
        records.append(Observation("lianjia", m[1], text(a), urljoin(url, a["href"]), region["id"],
                                   address=location, property_type=kind, extra={"list_url": url}, **price(text(main))))
    pages = soup.select(".page-box a[href]")
    nxt = next((urljoin(url, a["href"]) for a in pages if "下一页" in text(a)), None)
    # 动态分页必须先验证，不能把第一页冒充全量。
    if soup.select_one(".page-box") and not pages:
        raise SourceError("链家动态分页未接入，不宣称完整覆盖", "schema_changed")
    return records, seen, nxt, None


def official_stats(html, url, region):
    soup = BeautifulSoup(html, "html.parser")
    records = []
    for table in soup.select("table"):
        context = text(table.find_previous(["h2", "h3", "h4"]))
        if not any(t in context for t in ("可售", "未售", "签约")):
            continue
        for tr in table.select("tr"):
            cells = [text(c) for c in tr.find_all(["td", "th"])]
            if len(cells) >= 3 and cells[0].rstrip("区") == region["district"].rstrip("区"):
                for i, suffix, unit in ((1, "count", "套"), (2, "area", "平方米")):
                    try:
                        value = float(cells[i].replace(",", ""))
                    except ValueError:
                        continue
                    label = "available" if "可售" in context else "unsold" if "未售" in context else "signed"
                    records.append(Observation("official", "district:" + region["id"], region["city"] + region["district"] + "区",
                                               url, region["id"], kind=f"{label}_{suffix}", value=value, unit=unit,
                                               raw_price=cells[i], extra={"heading": context}))
    if not records:
        raise SourceError("官方页面为动态模板，未取得真实统计值；需核实公开接口后接入", "schema_changed")
    return records


def nbs_indices(html, url, region):
    soup = BeautifulSoup(html, "html.parser")
    title = text(soup.find("h1")) or text(soup.find("title"))
    date = re.search(r"(\d{4})年(\d{1,2})月份", title)
    if not date:
        raise SourceError("统计局文章标题无法确认统计月份", "schema_changed")
    period = f"{date[1]}-{int(date[2]):02d}"
    content = text(soup)
    publication = re.search(r"\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}", content)
    records = []
    for table in soup.select("table"):
        # 表标题通常在 table 外；依据前方最近的“表N”确定新房/二手房。
        before = table.find_previous(lambda tag: tag.name == 'p' and len(text(tag)) < 200
                                     and re.match(r"表\s*[1-4]\s*[：:]", text(tag)))
        labels = re.findall(r"表\s*([1-4])\s*[：:]", text(before))
        number = labels[-1] if labels else None
        if number not in ("1", "2"):
            continue
        for tr in table.select("tr"):
            cells = [re.sub(r"\s+", "", text(c)) for c in tr.find_all(["td", "th"])]
            for i, cell in enumerate(cells):
                if cell != region["city"] or i + 3 >= len(cells):
                    continue
                for j, metric in enumerate(("mom", "yoy", "year_average"), 1):
                    try:
                        value = float(cells[i + j])
                    except ValueError:
                        continue
                    records.append(Observation("nbs", "city:" + region["city"], region["city"], url, region["id"],
                                               kind=f"{'new' if number == '1' else 'resale'}_index_{metric}", value=value,
                                               unit="指数（比较期=100）", raw_price=cells[i + j],
                                               period=period, granularity="month", source_updated=publication[0] if publication else None))
    if not records:
        raise SourceError("未解析到广州月度指数", "schema_changed")
    return records


def official_json(payload, label, url, region):
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise SourceError("官方统计接口返回结构不符", "schema_changed")
    records = []
    for row in payload['data']:
        if row.get('sectionName', '').rstrip('区') != region['district'].rstrip('区'):
            continue
        date = str(row.get('createTime') or '')
        # 接口同时出现 yyyy-mm-dd 与 yyyy/mm/dd。
        match = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", date)
        if not match:
            raise SourceError("官方统计缺少可核实的数据日期", "schema_changed")
        period = f"{int(match[1]):04d}-{int(match[2]):02d}-{int(match[3]):02d}"
        for field, suffix, unit in [('zhuZaiTaoShu','count','套'),('zhuZaiArea','area','平方米')]:
            try:
                value = float(row[field])
            except (KeyError,TypeError,ValueError):
                raise SourceError("官方住宅指标字段缺失", "schema_changed")
            records.append(Observation('official','district:'+region['id'],region['city']+region['district']+'区',url,region['id'],
                                       kind=f'{label}_{suffix}',value=value,unit=unit,raw_price=str(row[field]),
                                       period=period,granularity='day',source_updated=date))
    if not records:
        raise SourceError("官方统计接口未返回目标地区", "schema_changed")
    return records
