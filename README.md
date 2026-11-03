# Avatar Switch Sync

用于 VRChat 的 Windows 模型设置共享工具。为同一角色的不同模型保留选定参数，换模型后自动恢复。

## 下载 0.7.0

- [安装包](https://github.com/SgZincanya/AvatarSwitchSync/releases/download/v0.7.0/AvatarSwitchSync-0.7.0-Installer.zip)
- [源码维护包](https://github.com/SgZincanya/AvatarSwitchSync/releases/download/v0.7.0/AvatarSwitchSync-0.7.0-Source.zip)

## 使用

1. 在 VRChat 中启用 OSC，加载参考模型。
2. 新建共享组，可以先只选择一个模型，检查要共享的参数。
3. 手动点击“开始共享”，保存当前模型的参考设置。
4. 开启“添加模式”，依次使用新模型，准备好后自动入组并同步已有设置。

SteamVR 自动启动时恢复已有共享记录；手动开始共享时先保存当前游戏值。软件已打开时，SteamVR 启动通知会交给现有窗口处理。

成员默认折叠、展开后一行一个。支持参数快照、本机模型自动发现、共享范围筛选、深浅界面和运行诊断。校准与批量归零保护会暂停异常状态的记录，实时眼追和表情参数受保护。

## 维护与构建

完整可维护源码位于 `src/`；测试位于 `tests/`；构建入口为 `build.ps1`。当前版本通过 79 项测试，并已从独立维护目录重新构建程序和安装包。

请参阅[维护指南](docs/MAINTENANCE.md)准备 Python 3.12 和构建依赖，再运行测试、生成界面资源或重新打包。软件详细说明见[使用说明](docs/README.md)。

## 数据与第三方组件

仓库及版本附件不包含个人分组、模型 ID、共享记录、参数快照、日志或个人截图。运行数据保存在本机用户目录；升级与卸载保留这些数据。第三方许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 和 `licenses/`。
