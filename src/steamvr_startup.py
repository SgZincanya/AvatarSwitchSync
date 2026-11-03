"""Optional SteamVR registration and local single-instance start requests."""
import ctypes
import json
import os
from pathlib import Path
import time

APP_KEY = 'local.avatarswitchsync'
EVENT_NAME = 'Local\\AvatarSwitchSync.StartSharing'


def manifest(executable):
    executable = Path(executable).resolve(strict=True)
    return {'source':'builtin','applications':[{
        'app_key':APP_KEY,'launch_type':'binary',
        'binary_path_windows':str(executable),'arguments':'--start-sharing',
        'working_directory':str(executable.parent),'is_dashboard_overlay':True,
        'strings':{'en_us':{'name':'Avatar Switch Sync','description':'Share avatar settings automatically with SteamVR.'}}}]}


class Applications:
    def __enter__(self):
        paths=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData/Local')))/'openvr/openvrpaths.vrpath'
        runtimes=json.loads(paths.read_text(encoding='utf-8-sig')).get('runtime',[])
        dll=next((Path(p)/'bin/win64/openvr_api.dll' for p in runtimes if (Path(p)/'bin/win64/openvr_api.dll').is_file()),None)
        if dll is None:raise FileNotFoundError('未找到 SteamVR，请先安装并运行一次 SteamVR。')
        self.api=ctypes.CDLL(str(dll))
        self.api.VR_InitInternal.argtypes=[ctypes.POINTER(ctypes.c_int),ctypes.c_int]
        self.api.VR_InitInternal.restype=ctypes.c_uint32
        self.api.VR_GetGenericInterface.argtypes=[ctypes.c_char_p,ctypes.POINTER(ctypes.c_int)]
        self.api.VR_GetGenericInterface.restype=ctypes.c_void_p
        self.api.VR_ShutdownInternal.argtypes=[]
        self.api.VR_ShutdownInternal.restype=None
        error=ctypes.c_int()
        # Utility accesses settings without loading hardware drivers or starting VR.
        self.api.VR_InitInternal(ctypes.byref(error),4)
        if error.value:raise RuntimeError(f'SteamVR 初始化失败：{error.value}')
        pointer=self.api.VR_GetGenericInterface(b'FnTable:IVRApplications_008',ctypes.byref(error))
        if error.value or not pointer:
            self.api.VR_ShutdownInternal()
            raise RuntimeError(f'SteamVR 应用接口不可用：{error.value}')
        self.table=ctypes.cast(pointer,ctypes.POINTER(ctypes.c_void_p))
        return self

    def call(self,index,result,args,*values):
        return ctypes.WINFUNCTYPE(result,*args)(self.table[index])(*values)

    def installed(self):return bool(self.call(2,ctypes.c_bool,[ctypes.c_char_p],APP_KEY.encode()))
    def enabled(self):return bool(self.call(18,ctypes.c_bool,[ctypes.c_char_p],APP_KEY.encode()))

    def configure(self,path,enabled):
        if enabled:
            code=self.call(0,ctypes.c_int,[ctypes.c_char_p,ctypes.c_bool],str(path).encode('utf-8'),False)
            if code:raise RuntimeError(f'SteamVR 应用注册失败：{code}')
        if self.installed():
            code=self.call(17,ctypes.c_int,[ctypes.c_char_p,ctypes.c_bool],APP_KEY.encode(),enabled)
            if code:raise RuntimeError(f'SteamVR 自动启动设置失败：{code}')
        if self.enabled()!=enabled:raise RuntimeError('SteamVR 自动启动设置未生效')

    def __exit__(self,*_):self.api.VR_ShutdownInternal()


def configure(executable,enabled):
    path=Path(executable).parent/'AvatarSwitchSync.vrmanifest'
    if enabled:
        path.write_text(json.dumps(manifest(executable),ensure_ascii=False,indent=2),encoding='utf-8')
    with Applications() as apps:
        apps.configure(path,enabled)
        return {'installed':apps.installed(),'auto_launch':apps.enabled(),'manifest':str(path)}


def kernel():
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.CreateEventW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_bool,ctypes.c_wchar_p]
    api.CreateEventW.restype=ctypes.c_void_p
    api.OpenEventW.argtypes=[ctypes.c_uint32,ctypes.c_bool,ctypes.c_wchar_p]
    api.OpenEventW.restype=ctypes.c_void_p
    api.SetEvent.argtypes=[ctypes.c_void_p]
    api.SetEvent.restype=ctypes.c_bool
    api.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32]
    api.WaitForSingleObject.restype=ctypes.c_uint32
    api.CloseHandle.argtypes=[ctypes.c_void_p]
    return api


def create_event(name=EVENT_NAME):
    handle=kernel().CreateEventW(None,False,False,name)
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    return handle


def request_start(name=EVENT_NAME):
    api=kernel()
    for _ in range(15):
        handle=api.OpenEventW(2,False,name)
        if handle:
            try:return bool(api.SetEvent(handle))
            finally:api.CloseHandle(handle)
        time.sleep(.1)
    return False


def poll_start(root,app,handle):
    if app.closing:return
    if kernel().WaitForSingleObject(handle,0)==0 and not app.running:
        app.start(capture_current=False)
    root.after(500,lambda:poll_start(root,app,handle))
