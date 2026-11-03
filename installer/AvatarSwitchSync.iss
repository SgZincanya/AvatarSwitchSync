#ifndef AppVersion
#define AppVersion "0.7.0"
#endif
[Setup]
AppId={{A74FB19B-8178-40A6-B93C-7643B63EE979}
AppName=Avatar Switch Sync
AppVersion={#AppVersion}
AppVerName=Avatar Switch Sync {#AppVersion}
AppComments=VRChat 模型设置共享工具
DefaultDirName={localappdata}\Programs\AvatarSwitchSync
DefaultGroupName=Avatar Switch Sync
DisableProgramGroupPage=yes
DisableWelcomePage=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=AvatarSwitchSync-{#AppVersion}-Setup
SetupIconFile=..\src\app.ico
UninstallDisplayIcon={app}\AvatarSwitchSync.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
AppMutex=Local\AvatarSwitchSync
CloseApplications=no
RestartApplications=no
VersionInfoVersion={#AppVersion}.0
VersionInfoProductName=Avatar Switch Sync

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: unchecked
Name: "steamvrstartup"; Description: "SteamVR 启动时自动打开并开始共享"; Flags: unchecked

[Files]
Source: "..\dist\AvatarSwitchSync\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__,*.pyc,portable.flag,data,.backups"

[Icons]
Name: "{group}\Avatar Switch Sync"; Filename: "{app}\AvatarSwitchSync.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Avatar Switch Sync"; Filename: "{app}\AvatarSwitchSync.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\AvatarSwitchSync.exe"; Parameters: "--steamvr-enable-autostart"; Tasks: steamvrstartup; Flags: runhidden waituntilterminated
Filename: "{app}\AvatarSwitchSync.exe"; Description: "打开 Avatar Switch Sync"; Flags: nowait postinstall skipifsilent unchecked

[UninstallRun]
Filename: "{app}\AvatarSwitchSync.exe"; Parameters: "--steamvr-disable-autostart"; Flags: runhidden waituntilterminated skipifdoesntexist

[Messages]
chinesesimplified.FinishedLabel=Avatar Switch Sync 已安装完成。%n%n已有的分组、共享记录和参数快照会继续保留。请在游戏中启用 OSC 后开始共享。
