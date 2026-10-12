from io import BytesIO
import pandas as pd

LABELS = {
    "reference_unit": "参考单价", "reference_unit_starting": "参考起价（单价）",
    "reference_unit_range": "参考单价区间", "reference_total": "参考总价",
    "reference_total_starting": "参考起价（总价）", "reference_total_range": "参考总价区间",
    "available_count": "可售住宅套数", "available_area": "可售住宅面积",
    "unsold_count": "未售住宅套数", "unsold_area": "未售住宅面积",
    "signed_count": "住宅网签套数", "signed_area": "住宅网签面积",
    "new_index_mom": "广州新房环比指数", "new_index_yoy": "广州新房同比指数",
    "new_index_year_average": "广州新房年内平均指数",
    "resale_index_mom": "广州二手房环比指数", "resale_index_yoy": "广州二手房同比指数",
    "resale_index_year_average": "广州二手房年内平均指数", "unknown": "未确认口径",
}
SOURCES = {"fang": "房天下", "lianjia": "链家", "official": "广州住建局", "nbs": "国家统计局"}


def frame(store, region=None):
    return pd.DataFrame(store.observations(region))


def paired_changes(df):
    """相邻观察日同来源、同口径、同项目样本；日期断档不称为日环比。"""
    if df.empty:
        return pd.DataFrame()
    work = df[(df.granularity == "snapshot") & (df.kind == "reference_unit") & df.value.notna()]
    results = []
    for source, part in work.groupby("source"):
        days = sorted(part.period.unique())
        for previous, current in zip(days, days[1:]):
            a = part[part.period == previous].set_index(["region_id", "source_id"])["value"]
            b = part[part.period == current].set_index(["region_id", "source_id"])["value"]
            pair = pd.concat([a.rename("before"), b.rename("after")], axis=1).dropna()
            pair = pair[pair.before > 0]
            if not pair.empty:
                results.append({"source": source, "previous": previous, "period": current,
                                "sample_count": len(pair), "change_pct": float(((pair.after / pair.before - 1) * 100).mean())})
    return pd.DataFrame(results)


def safe_export(df):
    result = df.copy()
    # Excel/CSV 文本不得作为公式执行，网页源内容不能成为可执行公式。
    for column in result.select_dtypes(include=["object", "string"]).columns:
        result[column] = result[column].map(lambda v: "'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v)
    return result


def csv_bytes(df):
    return safe_export(df).to_csv(index=False).encode("utf-8-sig")


def excel_bytes(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        safe_export(df).to_excel(writer, index=False, sheet_name="观察记录")
    return output.getvalue()
