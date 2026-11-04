# 造五活动助手

基于 Python + Tkinter 的《造梦西游5》日常与活动辅助工具，包含一键日常、联盟、竞技场、宠物培养、活动副本等模块。

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

`app/` 目前包含 160 个运行模块，采用扁平导入与“同目录脚本”启动方式，因此不要把模块拆进多层包；需要重构时先补路径常量，再分批移动。

## 环境

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 首次配置

1. 复制 `account.example.json` 为 `app/account.local.json`，填入自己的 Cookie 与存档槽位。
2. 将游戏配置表目录放到 `app/`，例如 `app/cg_config_out_cg1_20261026_1/`；部分模块还会读取 `app/feature_config/`。
3. 仓库不提供上述数据；缺少配置时，对应功能会在运行时提示找不到文件。
4. `app/account.local.json`、`app/accounts/` 已在 `.gitignore` 中忽略，不要提交。

## 运行

```powershell
python run.py
```

`run.py` 会把 `app/` 加入 `sys.path` 并切换工作目录，然后启动 `app/gui.py`。

## 测试

```powershell
python tests/test_pet_training_toolbox_offline.py
```

当前保留的离线测试覆盖：抓宠/早停升级工具箱构建、按钮参数、二级密码传递、页签可见性。

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
2. 将配置目录收敛为环境变量或统一常量，避免按日期硬编码多个版本。
3. 在补齐路径常量后，再按 `core/ui/features` 拆分 `app/`，并逐个模块回归。
