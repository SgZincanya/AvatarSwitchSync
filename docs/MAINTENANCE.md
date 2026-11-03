# Avatar Switch Sync 0.8.1 · 源码维护包

这份包可以独立修改、测试、构建 Windows 程序和安装包，不依赖开发者的原项目目录。程序源码与 0.8.1 安装版一致。配置、模型 ID、共享记录、参数快照、运行日志、个人界面截图和历史备份均不随包提供。

## 环境准备

使用 Windows 10/11 64 位、带 Tcl/Tk 的 Python 3.12，以及 Inno Setup。当前交付验证环境为 Python 3.12.14、Inno Setup 6.7.3。Python 需能打开 Tk 窗口。

在此目录打开 PowerShell，依次运行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe src\avatar_sync.py
```

只运行程序可仅安装 `requirements.txt`；开发、重建界面资源和打包使用 `requirements-dev.txt`。依赖通过 pip 获取，维护包不包含虚拟环境，首次准备依赖需要网络或自行提供对应 wheel。

## 测试与构建

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py'
.\build.ps1
```

`build.ps1` 会先执行 95 项测试，再生成 `dist/AvatarSwitchSync/` 程序目录与 `dist/AvatarSwitchSync-0.8.1-Setup.exe` 安装包。版本取自 `src/config_store.py` 的 `VERSION`，之后升级只需先修改该版本值。

可显式指定工具路径，或仅构建程序：

```powershell
.\build.ps1 -Python 'D:\Python312\python.exe' -InnoCompiler 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
.\build.ps1 -SkipInstaller
```

若本机策略不允许运行 `.ps1`，也可以直接使用脚本中的 Python 和 Inno Setup 命令，不需要修改系统安全设置。

常规测试使用临时资料和模拟游戏连接，不需要自己的 VRChat 模型缓存。少量界面测试会短暂打开测试窗口。另有独立本机网络测试：

```powershell
.\.venv\Scripts\python.exe tools\network_smoke.py
```

该测试使用本机模拟 HTTP/UDP 服务和独立 OSC 接收端口，参数写入只发给模拟服务；可能通过 mDNS 收到真实游戏通知，但不会向真实游戏发送参数。

## 修改位置

| 文件 | 用途 |
| --- | --- |
| `src/desktop_ui.py` | 窗口布局、分组编辑、参数表与菜单 |
| `src/ui_theme.py` | 颜色、字体、控件样式与原生标题栏 |
| `src/ui_artwork.py` | 已生成的界面图形资源，运行时无需 Pillow |
| `tools/generate_ui_artwork.py` | 生成圆角控件和图标；修改后运行一次再构建 |
| `src/avatar_sync.py` | OSCQuery/UDP 连接、后台共享流程和入口参数 |
| `src/sync_core.py` | 参数校验、恢复确认、共享值记录与实时追踪保护 |
| `src/calibration_guard.py` | 校准、批量归零与状态稳定筛选 |
| `src/enrollment.py` | 添加模式的成员检查 |
| `src/config_store.py` | 配置校验与版本号 |
| `src/model_discovery.py` | 本地模型发现 |
| `src/parameter_snapshots.py` | 只读参数快照与启动前备份 |
| `src/steamvr_startup.py` | SteamVR 启动项和已有窗口启动通知 |
| `src/updates.py` | GitHub 版本检查、Windows 原生 HTTPS、文件校验与更新线程 |
| `tools/UpdateHelper.cs` | 独立更新助手：等待退出、二次校验、原目录安装与恢复共享 |
| `src/runtime_diagnostics.py` | 本机进程资源统计 |
| `installer/AvatarSwitchSync.iss` | 安装目录、快捷方式、升级、卸载和可选 SteamVR 启动项 |

重新生成界面资源：

```powershell
.\.venv\Scripts\python.exe tools\generate_ui_artwork.py
```

## 维护时保留的行为

- 手动“开始共享”先保存当前游戏参数；SteamVR 自动启动恢复已有记录，无记录的参数跳过。
- 添加模式使用已有共享值，目标组固定；其他组成员不会自动移组。
- 分组支持单个参考模型；参数仅在全组兼容时共享，历史选择和记录保留。
- 校准与批量归零会暂停记录；眼球、表情等实时数据受到保护。
- 程序独立分配 OSC 端口，不绑定 9000/9001，不修改眼追软件配置。
- 普通打开程序不自动开始共享。`--start-sharing` 代表自动恢复启动；`--diagnose-connection` 仅检查连接。
- `--steamvr-enable-autostart` / `--steamvr-disable-autostart` 设置 SteamVR 启动项，需要本机安装并运行过 SteamVR。

## 数据与分发

运行源码与安装版默认共用当前用户的 `%LOCALAPPDATA%\AvatarSwitchSync`。调试真实设置前请先备份；需要隔离运行时，可在独立源码副本的 `src/` 下自行创建 `portable.flag`，数据将写入该副本的 `src/data/`。不要把个人数据重新装进公共包。

分发 `dist/AvatarSwitchSync/` 时要保留 `_internal/`；也可直接分发安装程序。安装和卸载保留个人分组、共享值与快照，卸载会关闭对应 SteamVR 自动启动。

第三方组件说明和许可位于 `THIRD_PARTY_NOTICES.md` 与 `licenses/`，重新分发时请保留。软件使用说明位于 `docs/README.md`。

## 更新发布约定

每个正式版本需要上传命名为 `AvatarSwitchSync-版本-Setup.exe` 的原始安装程序，且 GitHub 资产的 `digest` 提供 SHA-256；软件不从源码 ZIP 或维护包安装。发布版本标签为 `v主版本.次版本.修订号`，草稿、预发布和不完整安装资产不会作为自动更新目标。更新走公开 API，无账号令牌。

构建更新助手需要 Windows 自带的 .NET Framework 4.x C# 编译器，脚本从 Windows 目录检测 `Framework64/v4.0.30319/csc.exe`。`UpdateHelper.exe` 随程序分发，安装前复制到用户数据的 updates 目录运行，避免覆盖正在使用的程序。保持 AppId 和共享启动参数稳定，不要删除个人数据目录。

公开更新索引为仓库根目录的 `update.json`，结构与 GitHub Release 元数据兼容，仅包含正式版本、更新说明和原始 Setup.exe 的公开地址、大小及 SHA-256。程序读取 raw.githubusercontent.com 上的索引，不消耗 GitHub REST 匿名额度。发布时先完成 Release 附件上传与校验，最后更新 main 分支上的 update.json，避免用户看到尚未准备好的安装包。
