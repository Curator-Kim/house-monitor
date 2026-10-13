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

## 多城市管理

网页侧栏的“城市管理”提供预置城市下拉清单，也可以选择“自定义城市”填写城市名称和域名标识。

- 添加地区时留空行政区，表示监控全市。
- 填写行政区或关键词，则该地区只保留匹配该关键词的在售住宅。
- 房天下和链家地址按城市域名标识自动生成。
- 国家统计局月度指数按城市名称匹配。
- 广州的行政区会额外启用阳光家缘和广州住建局来源。
- 新添加城市的数据源仍需实际运行验证；采集失败会按来源记录原因，不会伪造数据。

配置会写入 `config.json` 的 `regions` 列表，之后可在“地区”下拉框中直接选择。
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

## 环境要求

项目需要 Python 3.11 或更高版本，并建议使用项目根目录下的 `.venv`。

先检查本机 Python：

```powershell
py -0p
```

如果只有 Python 3.10 或更低版本，先安装 Python 3.11：

```powershell
winget install -e --id Python.Python.3.11
```

安装完成后关闭并重新打开 PowerShell，再执行：

```powershell
py -0p
```

### Windows 首次创建环境

```powershell
cd D:\OverlordShampoo\房价数据采集
py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m ensurepip --upgrade
& .\.venv\Scripts\python.exe -m pip install -e ".[captcha,test]"
& .\.venv\Scripts\python.exe -m pytest -q
```

如果项目已经存在 `.venv`，先检查它的 Python 版本：

```powershell
& .\.venv\Scripts\python.exe -c "import sys; print(sys.version)"
```

如果低于 3.11，请停止前端后重建环境。旧环境先改名保留，不要直接删除：

```powershell
Rename-Item .venv .venv-old
py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m ensurepip --upgrade
& .\.venv\Scripts\python.exe -m pip install -e ".[captcha,test]"
```

### Ubuntu 首次创建环境

```bash
cd ~/house-monitor
python3.11 -m venv .venv
.venv/bin/python -m pip install -e '.[captcha,test]'
.venv/bin/python -m pytest -q
```
## 日常启动前端

### Windows

进入项目目录后启动：

```powershell
cd D:\OverlordShampoo\房价数据采集
& .\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

也可以使用项目脚本：

```powershell
cd D:\OverlordShampoo\房价数据采集
powershell -ExecutionPolicy Bypass -File .\scripts\start_web.ps1
```

指定端口：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_web.ps1 -Port 8502
```

浏览器访问：

```text
http://127.0.0.1:8501
```

如果 `8501` 已占用，改用其他端口：

```powershell
& .\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502
```

### Ubuntu

```bash
cd ~/house-monitor
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

前端主要页面：

- `关注楼盘`：选择当前地区的报价楼盘加入关注，展示关注楼盘的历史参考单价变化。
- `覆盖与运行`：查看来源验证阶段、覆盖率和任务记录。
- `运行日志`：查看最近一次来源采集结果、历史运行记录以及 `data/monitor.log` 的最近 300 行，并可下载完整日志。
验证码流程需要本机可启动 Chrome/Chromium；Selenium 会使用对应的浏览器驱动。

## 每日调度

每日调度不是常驻 Python 进程。系统计划任务每分钟调用一次 `tick`，程序在当天北京时间 `09:00–12:00` 的随机时刻执行采集。同一日期重启不会重新抽取；错过时补采一次；不会连续补跑遗漏日期。

手动执行一次到期检查：

```powershell
& .\.venv\Scripts\python.exe -m house_monitor.cli tick
```

立即执行一次完整采集：

```powershell
& .\.venv\Scripts\python.exe -m house_monitor.cli collect --region 440112
```

### Windows 定时采集

安装并启用 Windows 计划任务：

```powershell
cd D:\OverlordShampoo\房价数据采集
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_task.ps1
```

查看任务状态：

```powershell
Get-ScheduledTask -TaskName HuangpuHouseMonitor
Get-ScheduledTaskInfo -TaskName HuangpuHouseMonitor
```

任务名称为 `HuangpuHouseMonitor`，安装后每分钟检查一次，到期时通过 `pythonw.exe` 运行 `house_monitor.cli tick`，不会弹出命令行黑框。已经安装过旧版本任务时，重新运行安装脚本即可更新任务动作。

### Ubuntu 定时采集

安装用户级 systemd 服务：

```bash
cd ~/house-monitor
mkdir -p ~/.config/systemd/user
cp scripts/house-monitor.service scripts/house-monitor.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now house-monitor.timer
```

查看状态：

```bash
systemctl --user status house-monitor.timer
systemctl --user list-timers house-monitor.timer
```

如果项目不在 `~/house-monitor`，先修改 `scripts/house-monitor.service` 中的 `WorkingDirectory` 和 `ExecStart`。
## 停止与卸载

前端服务和每日调度是两套独立机制：停止网页不会自动停止定时采集；禁用定时任务也不会关闭网页。

### Windows

前台启动的 Streamlit 会显示日志，直接在终端按 `Ctrl+C` 即可停止。

后台启动时，停止由本项目启动的 Streamlit 进程：

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -like '*streamlit*run*app.py*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

查看计划任务状态：

```powershell
Get-ScheduledTask -TaskName HuangpuHouseMonitor
Get-ScheduledTaskInfo -TaskName HuangpuHouseMonitor
```

暂时停止未来的自动采集，但保留任务配置：

```powershell
Disable-ScheduledTask -TaskName HuangpuHouseMonitor
```

重新启用：

```powershell
Enable-ScheduledTask -TaskName HuangpuHouseMonitor
```

停止当前正在运行的采集实例：

```powershell
Stop-ScheduledTask -TaskName HuangpuHouseMonitor
```

彻底删除计划任务：

```powershell
Unregister-ScheduledTask -TaskName HuangpuHouseMonitor -Confirm:$false
```

如果手动在后台运行了采集命令，可停止匹配的采集进程：

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -like '*house_monitor.cli*collect*' -or $_.CommandLine -like '*house_monitor.cli*tick*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

### Ubuntu

前台 Streamlit 按 `Ctrl+C`；后台进程可使用：

```bash
pkill -f 'streamlit run app.py'
```

停止并禁止用户级定时器：

```bash
systemctl --user stop house-monitor.timer house-monitor.service
systemctl --user disable house-monitor.timer house-monitor.service
```

重新启用：

```bash
systemctl --user enable --now house-monitor.timer
```

如果服务安装在系统级 systemd 中，将上述命令中的 `systemctl --user` 改为 `sudo systemctl`。

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