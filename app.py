from collections import deque
from datetime import date
from pathlib import Path
import pandas as pd
import streamlit as st
from filelock import Timeout
from house_monitor.config import add_region, load_config
from house_monitor.storage import Store
from house_monitor.service import collect
from house_monitor.auth import clear_auth, load_auth, save_auth
from house_monitor.cities import CITY_CATALOG
from house_monitor.analytics import frame, paired_changes, csv_bytes, excel_bytes, LABELS, SOURCES

st.set_page_config(page_title="住宅价格观察", page_icon="🏠", layout="wide")
config = load_config()
store = Store(config["data_dir"])
st.title("住宅价格观察")
st.caption("每天北京时间09:00–12:00随机采集一次 · 免费公开来源 · 个人研究")
regions = [r for r in config["regions"] if r.get("enabled")]
if not regions:
    st.warning("尚未配置已支持地区")
    st.stop()
region = st.sidebar.selectbox("地区", regions, format_func=lambda r: f"{r['city']} · {r['district']}区")
st.sidebar.caption("只有已接入并配置的数据源对应地区可选。其他城市可先添加地区。")
with st.sidebar.expander("城市管理", expanded=False):
    st.caption("从预置清单添加城市；链家仍需在下方保存登录会话。")
    city_labels = [f"{city['name']} · {city['province']}" for city in CITY_CATALOG]
    city_options = city_labels + ["自定义城市"]
    city_choice = st.selectbox("添加城市", city_options, key="city_choice")
    if city_choice == "自定义城市":
        custom_name = st.text_input("城市名称", key="custom_city_name")
        custom_slug = st.text_input("城市域名标识", placeholder="例如 sz、hz、cd", key="custom_city_slug")
        new_city = {"name": custom_name.strip(), "slug": custom_slug.strip().lower()}
    else:
        catalog_index = city_labels.index(city_choice)
        new_city = CITY_CATALOG[catalog_index]
    new_district = st.text_input("行政区或关键词（留空为全市）", key="new_city_district")
    if st.button("添加并启用", key="add_city_region"):
        try:
            result = add_region(config["config_path"], new_city, new_district)
            if result["created"]:
                st.session_state["region_notice"] = f"已添加并启用：{result['region']['city']} · {result['region']['district']}"
            else:
                st.session_state["region_notice"] = f"该地区已存在：{result['region']['city']} · {result['region']['district']}"
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    region_notice = st.session_state.pop("region_notice", None)
    if region_notice:
        st.success(region_notice)
    enabled_regions = [f"{r['city']} · {r['district']}" for r in config["regions"] if r.get("enabled")]
    st.caption("已启用：" + "；".join(enabled_regions))
login_sources = [s for s in region.get("sources", {}) if s in ("lianjia",)]
if login_sources:
    with st.sidebar.expander("登录会话", expanded=False):
        st.caption("仅在本机保存 Cookie 或 Authorization 令牌；不保存账号密码。")
        source = st.selectbox("数据源", login_sources, format_func=lambda s: SOURCES.get(s, s))
        try:
            auth = load_auth(config["data_dir"], source)
        except Exception:
            auth = None
        if auth:
            st.success(f"已保存：{len(auth.get('cookies', {}))} 个 Cookie，{len(auth.get('headers', {}))} 个请求头")
        else:
            st.info("尚未保存登录会话")
        cookie = st.text_input("Cookie", type="password", key=f"cookie_{source}")
        token = st.text_input("Authorization", type="password", key=f"token_{source}")
        if st.button("保存登录会话", key=f"save_auth_{source}"):
            try:
                info = save_auth(config["data_dir"], source, cookie=cookie, token=token)
                st.session_state[f"cookie_{source}"] = ""
                st.session_state[f"token_{source}"] = ""
                st.session_state["auth_notice"] = f"已保存 {source} 登录会话：{info['cookies']} 个 Cookie、{len(info['headers'])} 个请求头"
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        if auth and st.button("清除登录会话", key=f"clear_auth_{source}"):
            clear_auth(config["data_dir"], source)
            st.session_state["auth_notice"] = f"已清除 {source} 登录会话"
            st.rerun()
        notice = st.session_state.pop("auth_notice", None)
        if notice:
            st.success(notice)
if st.sidebar.button("立即采集", type="primary"):
    try:
        with st.spinner("正在采集公开数据，历史回补可能需要数分钟…"):
            result = collect(config, region["id"])
        st.sidebar.success("采集结束：" + result["status"])
    except Timeout:
        st.sidebar.info("已有采集任务在运行，请稍后刷新")
    except Exception as exc:
        st.sidebar.error(str(exc))
st.sidebar.button("刷新页面")
df = frame(store, region["id"])
tabs = st.tabs(["楼盘报价", "官方指标与月度指数", "关注楼盘", "覆盖与运行", "运行日志", "数据导出"])
filtered = df.copy()
with tabs[0]:
    st.info("平台参考报价与成交价分别记录。当前尚未验证可获取可靠的楼盘每日成交价。")
    st.caption("验证期数据会显示，但不视为已通过三天连续采集验收。起价、总价和价格区间不进入参考均价趋势。")
    if df.empty:
        st.warning("还没有有效观察记录。点击“立即采集”开始；受阻来源可在“覆盖与运行”查看原因。")
    else:
        quote = df[df.source.isin(["fang", "lianjia"])].copy()
        if not quote.empty:
            sources = st.multiselect("报价来源", list(quote.source.unique()), default=list(quote.source.unique()), format_func=lambda s: SOURCES.get(s,s))
            names = st.multiselect("楼盘", sorted(quote.name.unique()))
            kinds = st.multiselect("价格口径", list(quote.kind.unique()), default=list(quote.kind.unique()), format_func=lambda k: LABELS.get(k,k))
            minimum, maximum = date.fromisoformat(quote.period.min()), date.fromisoformat(quote.period.max())
            dates = st.date_input("观察日期或历史记录日期", value=(minimum,maximum), min_value=minimum, max_value=maximum)
            quote = quote[quote.source.isin(sources) & quote.kind.isin(kinds)]
            if names:
                quote = quote[quote.name.isin(names)]
            if len(dates) == 2:
                quote = quote[quote.period.between(dates[0].isoformat(), dates[1].isoformat())]
            filtered = quote
            snapshot = quote[quote.granularity == "snapshot"]
            daily = snapshot[snapshot.kind == "reference_unit"].copy()
            daily["series"] = daily.name + " · " + daily.source.map(SOURCES)
            if not daily.empty:
                st.subheader("同楼盘、同来源参考单价")
                st.line_chart(daily.pivot_table(index="period", columns="series", values="value", aggfunc="first"), y_label="元/平方米")
                changes = paired_changes(daily)
                st.subheader("同样本报价变化")
                st.caption("相邻观察日共同楼盘的单价变化百分比平均值，同时展示样本数；断档时不是日环比。")
                if changes.empty:
                    st.caption("至少两个观察日后计算。")
                else:
                    st.dataframe(changes, hide_index=True, width="stretch")
            st.dataframe(quote[["name","source","kind","value","value_high","unit","period","granularity","raw_price","source_updated","missing_reason","url"]], hide_index=True, width="stretch")
            st.caption("snapshot为实际采集快照；event为来源公布的历史价格记录，未填充到其他日期。售罄及退出销售项目的历史仍保留。")
        else:
            st.warning("暂未采集到楼盘报价，请查看来源状态。")
with tabs[1]:
    if df.empty:
        st.caption("尚无官方数据。")
    else:
        official = df[df.source == "official"]
        ygjy = df[df.source == "ygjy"]
        monthly = df[df.source == "nbs"]
        st.subheader("区级住宅指标")
        st.dataframe(official, hide_index=True, width="stretch")
        st.caption("可售为纳入预售且可供签约的单元；未售包括可售、抵押、查封及未纳入预售的单元；签约为每日网上签约量。三者均不包含可靠成交金额，不能据此推算成交均价。")
        st.subheader("阳光家缘项目住宅销控")
        if not ygjy.empty:
            detail = ygjy.copy()
            detail["口径"] = detail.kind.map(LABELS)
            st.dataframe(detail[["period","name","source_id","presell","口径","value","unit","address","url"]], hide_index=True, width="stretch")
        else:
            st.caption("尚未取得阳光家缘项目底册；查询验证码流程失败时不会伪造项目数据。")
        st.caption("已售与未售均为住宅套数，用于官方项目底册和销控核对，不能换算成交均价。")
        st.subheader("广州月度价格指数")
        if not monthly.empty:
            monthly = monthly.copy()
            monthly["metric"] = monthly.kind.map(LABELS)
            st.line_chart(monthly.pivot_table(index="period",columns="metric",values="value",aggfunc="first"))
            st.dataframe(monthly[["period","metric","value","unit","source_updated","url"]],hide_index=True,width="stretch")
        else:
            st.caption("尚未取得月度指数，不能以报价代替。")
with tabs[2]:
    st.subheader("关注楼盘")
    quote_projects = df[df.source.isin(["fang", "lianjia"])][["source", "region_id", "source_id", "name"]].drop_duplicates()
    if quote_projects.empty:
        st.caption("当前地区尚无可关注的报价楼盘。")
    else:
        quote_projects = quote_projects.copy()
        quote_projects["option"] = quote_projects["source"] + "|" + quote_projects["region_id"] + "|" + quote_projects["source_id"]
        project_labels = quote_projects.set_index("option")["name"].to_dict()
        selected = st.multiselect("添加关注楼盘", options=list(project_labels), format_func=lambda key: project_labels.get(key, key))
        if st.button("添加关注", key="add_watch"):
            for option in selected:
                row = quote_projects[quote_projects.option == option].iloc[0]
                store.add_watch(row["source"], row["region_id"], row["source_id"], row["name"], pd.Timestamp.now(tz="Asia/Shanghai").isoformat())
            st.success("已更新关注列表")
            st.rerun()
    watched = store.watchlist()
    if watched:
        watch = pd.DataFrame(watched).rename(columns={"name": "watch_name"})
        region_labels = {r["id"]: f"{r['city']} · {r['district']}" for r in config["regions"]}
        watch["region_label"] = watch.region_id.map(region_labels).fillna(watch.region_id)
        history = frame(store).merge(watch[["source", "region_id", "source_id", "watch_name", "region_label"]],
                                     on=["source", "region_id", "source_id"], how="inner")
        history = history[(history.kind == "reference_unit") & history.value.notna()].copy()
        history["series"] = history.watch_name + " · " + history.region_label + " · " + history.source.map(SOURCES)
        if history.empty:
            st.caption("关注楼盘尚无参考单价历史；运行采集后会自动补齐。")
        else:
            st.subheader("历史参考单价")
            st.line_chart(history.pivot_table(index="period", columns="series", values="value", aggfunc="mean"), y_label="元/平方米")
            st.dataframe(history[["series", "period", "value", "unit", "granularity", "url"]].sort_values(["series", "period"]),
                         hide_index=True, width="stretch")
        st.subheader("管理关注")
        watch_options = watch["source"] + "|" + watch["region_id"] + "|" + watch["source_id"]
        watch_labels = dict(zip(watch_options, watch["watch_name"]))
        remove = st.multiselect("移除关注楼盘", options=list(watch_labels), format_func=lambda key: watch_labels.get(key, key))
        if st.button("移除关注", key="remove_watch"):
            for option in remove:
                source, region_id, source_id = option.split("|", 2)
                store.remove_watch(source, region_id, source_id)
            st.success("已移除关注")
            st.rerun()
    else:
        st.caption("尚未添加关注楼盘。")
with tabs[3]:
    st.subheader("来源覆盖与验证阶段")
    gates = pd.DataFrame(store.gates())
    st.dataframe(gates, hide_index=True, width="stretch")
    st.caption("provisional：验证中；verified：完整采集连续三天且报价项目抽查通过。七天条件满足后才进入二手房接入验收阶段。")
    coverage = pd.DataFrame(store.rows("SELECT * FROM source_runs WHERE region_id=? ORDER BY run_id DESC LIMIT 40", (region["id"],)))
    if not coverage.empty:
        coverage["missing_pct"] = coverage.apply(lambda r: round(r["missing"] / r["parsed"] * 100, 2) if r["parsed"] else None, axis=1)
    st.dataframe(coverage,hide_index=True,width="stretch")
    st.caption("discovered：列表发现项目；eligible：符合在售住宅筛选；parsed：保存的快照项目；缺失率基于本轮采集。完整分页不代表全区绝对覆盖。")
    st.subheader("任务记录")
    st.dataframe(store.rows("SELECT * FROM runs ORDER BY id DESC LIMIT 20"),hide_index=True,width="stretch")
    st.subheader("每日随机时刻")
    st.dataframe(store.rows("SELECT * FROM schedules ORDER BY day DESC LIMIT 7"),hide_index=True,width="stretch")
with tabs[4]:
    st.subheader("最近一次采集")
    runs = store.rows("SELECT * FROM runs ORDER BY id DESC LIMIT 1")
    if runs:
        latest = runs[0]
        st.write(f"运行编号 {latest['id']} · 状态 {latest['status']} · 开始 {latest['started']} · 结束 {latest['finished']}")
        source_logs = store.rows("""SELECT source,status,discovered,eligible,parsed,missing,pages,complete,message,warnings
                                     FROM source_runs WHERE run_id=? ORDER BY source""", (latest["id"],))
        if source_logs:
            st.dataframe(pd.DataFrame(source_logs), hide_index=True, width="stretch")
        st.caption("发现数为列表或接口发现的项目数；合格数是通过住宅筛选的项目数；完整分页不代表全区绝对覆盖。")
    else:
        st.caption("尚无运行记录。")
    st.subheader("历史运行记录")
    st.dataframe(store.rows("SELECT id,started,finished,status,message FROM runs ORDER BY id DESC LIMIT 50"), hide_index=True, width="stretch")
    st.subheader("运行日志文件")
    log_path = Path(config["data_dir"]) / "monitor.log"
    if log_path.exists():
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            recent = "".join(deque(handle, maxlen=300))
        st.caption("显示最后 300 行；下载按钮保留完整日志。")
        st.text_area("采集日志", recent, height=420, disabled=True)
        st.download_button("下载完整运行日志", log_path.read_bytes(), "monitor.log", "text/plain")
    else:
        st.caption("尚未生成 data/monitor.log。")
with tabs[5]:
    st.caption("导出内容与当前选择一致，含来源、原始价格、缺失原因和真实采集时间。")
    export_scope = st.radio("导出范围", ["当前报价筛选", "当前地区全部数据"], horizontal=True)
    export = filtered if export_scope == "当前报价筛选" else df
    st.write(f"共 {len(export)} 条观察记录")
    st.download_button("下载 CSV", csv_bytes(export), "house_observations.csv", "text/csv")
    st.download_button("下载 Excel", excel_bytes(export), "house_observations.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
