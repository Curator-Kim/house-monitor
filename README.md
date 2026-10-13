# house-monitor

广州黄埔区在售新建商品住宅的每日观察系统。程序采集公开来源，保存可追溯快照，并提供本地 Streamlit 网页、趋势变化、覆盖率检查和 Excel/CSV 导出。

## 当前范围

- 地区：广州市黄埔区（地区与来源均为配置驱动）。
- 物业：新建商品住宅；商业、办公、车位和无法确认物业类型的项目不进入住宅统计。
- 官方项目底册：阳光家缘提供项目编号、开发商、预售证、地址、住宅已售与未售套数。
- 官方统计：广州住建局公开接口提供区级可售、未售、签约套数与面积。
- 报价：房天下和链家作为候选来源，分别保存，不混成单一价格。
- 城市指数：国家统计局广州新房与二手房月度指数独立展示。
- 成交价：当前没有确认稳定公开的楼盘每日成交价，缺失时留空，不以报价代替。
- 二手房：新房连续七天通过验收后再接入。

## 验证码策略

- 阳光家缘：使用 ddddocr 本地识别查询页验证码；识别失败时读取页面当前生成的验证码值。
- 房天下：检测到简单拖动验证时，用受控无头浏览器完成拖动并复用验证 Cookie。
- 图片验证码：`CaptchaSolver` 使用本地 ddddocr，不调用第三方识别服务。
- 链家：网页侧栏“登录会话”可粘贴官方站点的 Cookie 或 Authorization 令牌，本地保存后复用；不保存账号密码，也不绕过短信或行为验证。
- 所有验证码处理均保留原始响应，限制重试次数并进行页间节流。

## 数据原则

- 每日快照从开始运行日积累，公开历史记录按来源原始粒度单独保存。
- 区分采集时间、来源更新时间和统计期间。
- 区分参考均价、起价、区间价、总价、备案价和成交价。
- 缺失值不填零；没有可靠面积时不把总价换算成单价。
- 保留原始 HTTP 响应和请求元数据，可按真实抓取时间离线回放。
- 同项目匹配优先使用官方编号和预售证；不确定时保持独立并标记待核对。

## 快速开始

### Windows

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[captcha,test]"
.\.venv\Scripts\python.exe -m pytest -q
.\scripts\start_web.ps1
```

网页默认仅监听 `127.0.0.1:8501`。验证码流程需要本机可启动 Chrome；Selenium 会自动准备匹配的驱动。

### Ubuntu

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e '.[captcha,test]'
.venv/bin/python -m pytest -q
.venv/bin/python -m streamlit run app.py
```

Ubuntu 无图形环境运行浏览器验证时，需要安装 Chrome/Chromium 及对应系统依赖。

## 每日调度

北京时间 `09:00–12:00` 之间为每天持久化一个随机采集时刻。同一日期重启不会重新抽取；错过时补采一次；不会连续补跑遗漏日期。调度入口为：

```bash
python -m house_monitor.cli tick
```

- Windows：运行 `scripts/install_windows_task.ps1` 注册每分钟检查的计划任务。
- Ubuntu：安装 `scripts/house-monitor.service` 和 `scripts/house-monitor.timer` 到 systemd。

## 常用命令

```bash
python -m house_monitor.cli login --source lianjia --cookie "name=value; name2=value2"
python -m house_monitor.cli login --source lianjia --header "Authorization: Bearer TOKEN"
python -m house_monitor.cli collect --region 440112
python -m house_monitor.cli tick
python -m house_monitor.cli status
python -m house_monitor.cli plan-day
python -m house_monitor.cli replay --raw-run 5 --region 440112
python -m house_monitor.cli check --source ygjy --region 440112 --source-id PROJECT_ID --note "已核对"
python -m house_monitor.cli export --region 440112 --output exports/observations.xlsx
```

运行时数据、SQLite、原始响应和导出目录均由 `.gitignore` 排除，不进入代码仓库。

## 验收门槛

来源只有在以下条件满足后才标记为已验证：

1. 完整分页或完整接口采集成功。
2. 连续三个日历日采集完成。
3. 至少抽查 10 个楼盘；不足 10 个时全部核对。
4. 抽查覆盖区域、住宅类型、名称、价格口径和单位。
5. 连续七天稳定运行后，才进入二手房来源评估。

当前真实来源状态与已知阻塞见 `docs/data-source-status.md`。

## 项目结构

```text
app.py                     Streamlit 网页
house_monitor/             采集、解析、验证码、存储、调度和导出
tests/                     离线回归测试
scripts/                   Windows 与 systemd 运行脚本
config.json                地区、来源和时间窗口配置
data/                      运行数据（不提交）
```

## 私有仓库

代码托管于 `https://github.com/Curator-Kim/house-monitor`（私有）。