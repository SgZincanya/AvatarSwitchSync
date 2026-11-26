"""Per-user VRChat launch following, independent of SteamVR."""
import os
from pathlib import Path
import subprocess

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
VALUE_NAME = 'AvatarSwitchSync.VRChat'


def command(executable):
    helper = Path(executable).resolve().parent / 'VRChatLauncher.exe'
    if not helper.is_file():
        raise FileNotFoundError('未找到 VRChat 启动助手，请重新安装软件。')
    return str(helper), subprocess.list2cmdline([str(helper)])


def registered_command():
    if os.name != 'nt':
        return ''
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, kind = winreg.QueryValueEx(key, VALUE_NAME)
            return value if kind == winreg.REG_SZ else ''
    except FileNotFoundError:
        return ''


def set_registration(value):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if value:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, value)
        else:
            try:winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:pass


def stop_helper(helper):
    result = subprocess.run([str(helper), '--stop'], timeout=12, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=False)
    if result.returncode:
        raise RuntimeError('VRChat 启动助手未能退出，请稍后重试。')


def configure(executable, enabled):
    helper, value = command(executable)
    previous = registered_command()
    stop_helper(helper)
    if not enabled:
        set_registration('')
        return {'enabled':False, 'helper':helper}
    try:
        set_registration(value)
        subprocess.Popen([helper], cwd=str(Path(helper).parent), creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except Exception:
        set_registration(previous)
        if previous:
            try:subprocess.Popen(previous, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except OSError:pass
        raise
    return {'enabled':True, 'helper':helper}
