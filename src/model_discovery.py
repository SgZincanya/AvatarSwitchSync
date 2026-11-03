"""Watch local cache changes without requiring the sync engine to be running."""
import threading
import ctypes
import os
import time
from pathlib import Path
import avatar_sync as backend


def cache_signature(root):
    root = Path(root)
    result = []
    files = list(root.glob('*/Avatars/*.json'))
    saved_root = root.parent / 'LocalAvatarData'
    if saved_root.exists():
        files.extend(p for p in saved_root.glob('*/*') if p.is_file())
    for path in files:
        try:
            stat = path.stat()
            result.append((str(path), stat.st_mtime_ns, stat.st_size))
        except OSError:
            continue
    return tuple(sorted(result))


class InventoryMonitor(threading.Thread):
    def __init__(self, events, root=None, interval=10):
        super().__init__(daemon=True)
        self.events = events
        self.root = Path(root) if root is not None else backend.CACHE
        self.interval = interval
        self.stop_event = threading.Event()
        self.refresh_event = threading.Event()

    def request_refresh(self):
        self.refresh_event.set()

    def run(self):
        previous = None
        watches=DirectoryWatches([self.root,self.root.parent/'LocalAvatarData'])
        next_fallback=0
        try:
            while not self.stop_event.is_set():
                manual=self.refresh_event.is_set();self.refresh_event.clear()
                changed=watches.changed()
                now=time.monotonic()
                if previous is None or manual or changed or (not watches.complete and now>=next_fallback):
                    try:
                        signature=cache_signature(self.root)
                        if manual or signature!=previous:
                            avatars=backend.inventory(self.root)
                            previous=signature
                            self.events.put(('inventory',{'avatars':avatars,'manual':manual}))
                    except OSError as exc:self.events.put(('discovery_error',str(exc)))
                    watches.add_missing()
                    next_fallback=now+self.interval
                self.stop_event.wait(min(.25,self.interval))
        finally:watches.close()


class DirectoryWatches:
    """Watch only avatar cache/saved-data directories, never the active game log."""
    def __init__(self,paths):
        self.paths=list(paths);self.handles={};self.api=None
        if os.name=='nt':
            self.api=ctypes.WinDLL('kernel32',use_last_error=True)
            self.api.FindFirstChangeNotificationW.argtypes=[ctypes.c_wchar_p,ctypes.c_bool,ctypes.c_uint32]
            self.api.FindFirstChangeNotificationW.restype=ctypes.c_void_p
            self.api.FindNextChangeNotification.argtypes=[ctypes.c_void_p]
            self.api.FindNextChangeNotification.restype=ctypes.c_bool
            self.api.FindCloseChangeNotification.argtypes=[ctypes.c_void_p]
            self.api.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32]
            self.api.WaitForSingleObject.restype=ctypes.c_uint32
        self.add_missing()
    @property
    def complete(self):return len(self.handles)==len(self.paths)
    def add_missing(self):
        if not self.api:return
        for path in self.paths:
            if path not in self.handles and path.is_dir():
                handle=self.api.FindFirstChangeNotificationW(str(path),True,0x1|0x2|0x8|0x10)
                if handle and handle!=ctypes.c_void_p(-1).value:self.handles[path]=handle
    def changed(self):
        changed=False
        for path,handle in list(self.handles.items()):
            result=self.api.WaitForSingleObject(handle,0)
            if result==0:
                changed=True
                if not self.api.FindNextChangeNotification(handle):
                    self.api.FindCloseChangeNotification(handle);del self.handles[path]
            elif result==0xFFFFFFFF:
                self.api.FindCloseChangeNotification(handle);del self.handles[path]
        return changed
    def close(self):
        for handle in self.handles.values():self.api.FindCloseChangeNotification(handle)
        self.handles.clear()
