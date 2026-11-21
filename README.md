# 造五活动助手

基于 Python + Tkinter 的《造梦西游5》日常与活动辅助工具，包含一键日常、联盟、竞技场、宠物培养、活动副本等模块。

## 近期更新

- 乱斗商店：在“挂机斗神/灵宠乱斗”下新增三个折叠面板（乱斗商店、符箓商店、天赋商店），显示乱斗币/灵魂/兽印余额及日/周/总限购，支持勾选购买；账号已设置二级密码时可填写后购买，密码错误（502）会明确提示并停止，不扣费。
- 十绝阵/蛮荒组队：某个成员次数为 0 时不再整队跳过，该成员继续跟队但不领奖；连续执行中途有人归零，其余成员照常打完剩余局数，只有全员不足才停止。
- 配置表读取与更新：配置表读取统一走“运行目录 → 模块目录 → 最新完整 cg1”查找，不再写死日期目录；`app/feature_config` 缺失时不再启动闪退。打包版和源码版启动前都会先检查，缺配置或本地配置超过 8 天（以配置日期当天中午 12 点起算）时先下载、解包、校验，完成后再进入主界面；服务器本周暂无新包时暂停到下一个配置日中午，失败则继续使用本地配置并由界面后台重试。升级安装会保留账号、已下载配置、队伍/界面设置与日志。
- 打包：`tools/build_exe.py` 会把顶层 JSON 与 `feature_config` 同时复制到 `_internal`，修复打包版按 `__file__` 找不到 `app\feature_config` 的问题。
- 玉珠商店：新增“剩余玉珠”和“刷新余额”（45 秒超时保护），查询后显示每件商品的限购、已购与剩余数量；购买日志会说明因限购或玉珠不足导致的购买数量调整。
- 万兽秘境：新增首通补关与第 6 关每日免费重复挑战（`app/pet_pve_daily.py`），日常页两个开关独立执行。
- 挑战牛魔王：活动可用性接入 `Activity` 配置，普通/噩梦共享 2 次免费；新配置 `cg_config_out_cg1_20261116_1` 已包含活动 2080（2026/11/10–12/7），按表自动判定开放，11-17 的临时放行已移除。
- 邪角色：按最新本地 cg1 的 `Activity` 表判断当前开放角色（邪唐僧等 8 个），不再按版本号推算。
- 每日活跃：先查任务列表，只提交 990001~990032 中已完成待领（status==2）的任务；里程碑按活跃点与已领档位筛选，领完任务后刷新活跃点。
- 幻兽喂养：活动期基础次数取 `feedDayNum_Activity`，邪唐僧周基础 20 次，VIP2+ 共 30 次。
- 妖王帖：我的日常改为自动抽完当天剩余免费次数。
- 斗神大会：默认真人加载完成后 3–6 秒投降、机器人判胜；真人场数默认 7（机器人不计）；原仓库“等对手退出”保留为备用方案1。

## 免责声明

- 本项目仅用于个人学习与本地辅助，请遵守游戏用户协议与当地法律。
- 仓库不包含游戏客户端、反编译代码、游戏配置数据或账号信息。
- 游戏名称、素材与相关权利归原厂商所有。

## 目录结构

```text
.
├─ app/                 # 运行目录（模块保持扁平，便于现有导入与子进程启动）
├─ tools/               # 打包/构建脚本
├─ tests/               # 离线回归测试
├─ data/                # 本地数据占位（配置表不提交）
├─ run.py               # 启动入口
├─ requirements.txt
├─ account.example.json
└─ .gitignore
```

`app/` 目前包含 187 个 Python 文件，采用扁平导入与“同目录脚本”启动方式，因此不要把模块拆进多层包；需要重构时先补路径常量，再分批移动。

## 环境

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 首次配置

1. 复制 `account.example.json` 为 `app/account.local.json`，填入自己的 Cookie 与存档槽位。
2. 配置表无需手动准备：启动时会先检查本地配置；没有完整配置或配置超过 8 天时，自动从 4399 官方资源服下载本周 `cg1_*.swf` 并解包为 `app/cg_config_out_cg1_*`，完成后才进入主界面。也可在“配置更新”页手动点“检查并更新配置”。服务器本周暂无新包时，会暂停到下一个配置日中午再检查。
3. 也可手动放入配置目录，程序会自动选择最新的完整 cg1 目录，例如 `app/cg_config_out_cg1_YYYYMMDD_N/`；仓库不提供配置数据。
4. `app/account.local.json`、`app/accounts/` 已在 `.gitignore` 中忽略，不要提交。

## 运行

```powershell
python run.py
```

`run.py` 会把 `app/` 加入 `sys.path` 并切换工作目录，然后启动 `app/gui.py`。

## 测试

```powershell
python -m unittest discover -s tests
```

覆盖抓宠/早停升级工具箱、按钮参数、二级密码传递、商店限购、配置读取等离线用例。部分历史用例仍在适配已移除的旧接口（当前为 15 errors + 1 failure），不影响主程序运行。

## AS 路由对照说明

用 FFdec 反编译的 `scripts`（2026-08-25 版本）与服务端 788 条路由做过一次对照：

- AS 有、服务端没有：36 条
  - 31 条只在 `ServerConst`、`RouteConst`、`QCConst`、`TeamConst` 里定义，没有调用点，属于历史常量；
  - 1 条是拼写错误：`cene.petPvpHandler.addSysPetLv`，正确为 `scene.petPvpHandler.addSysPetLv`；
  - 4 条是 `TeamOperateCmd` 里的旧组队路由。
- 服务端有、AS 没引用：140 条，主要是版本差（GM、联盟战、迷宫、宠物竞技等新增接口）。

工具箱的组队流程（`halo_solo.py`、`halo_team.py`）已经使用新路由：

- `room.waitingRoomHandler.prepareCreateOnlineCopy`
- `room.waitingRoomHandler.loadingProgress`

因此不为上述 4 条旧路由增加兼容逻辑，也不为那 31 条历史常量补实现。若以后要复刻旧客户端的组队行为，可按下表映射：

| 旧路由 | 当前路由 |
|---|---|
| `room.waitingRoomHandler.createOnlineCopy` | `room.waitingRoomHandler.prepareCreateOnlineCopy` |
| `scene.copyHandler.ping` | `copy.copyHandler.ping` 或 `room.waitingRoomHandler.ping` |
| `scene.copyHandler.broadcastMessagePingTime` | `room.waitingRoomHandler.broadcastMessagePingTime` |
| `copy.copyHandler.getServerTime` | `scene.userHandler.getCurDateTime` |

表中的“当前路由”只是服务端实际注册的替代接口，不代表旧客户端的调用参数可以直接复用。

## 打包

```powershell
pip install pyinstaller
python tools/build_exe.py
```

构建脚本从 `app/gui.py` 开始收集运行依赖，产物输出到 `tools/exe_*`，不会复制账号与 Cookie。

## 提交前检查

```powershell
git status --short
```

确认没有以下内容进入版本库：

- `app/account.local.json`、`app/accounts/`、任何 `*.private.py`；
- `app/cg_config_out_*/`、`app/feature_config/`、反编译目录；
- 发布包、EXE、RAR、日志和运行报告。

## 后续整理

1. 把一次性探针、修复、审计脚本移出 `app/`，只保留运行模块。
2. 修复历史离线测试（当前 15 errors + 1 failure），恢复全绿。
3. 把打包输出目录从固定日期改为动态目录，并继续按 `core/ui/features` 拆分模块。
