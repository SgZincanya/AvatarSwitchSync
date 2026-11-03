"""Watch local cache changes without requiring the sync engine to be running."""
import threading
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
    def __init__(self, events, root=None, interval=2):
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
        while not self.stop_event.is_set():
            manual = self.refresh_event.is_set()
            self.refresh_event.clear()
            try:
                signature = cache_signature(self.root)
                if manual or signature != previous:
                    avatars = backend.inventory(self.root)
                    previous = signature
                    self.events.put(('inventory', {'avatars':avatars, 'manual':manual}))
            except OSError as exc:
                self.events.put(('discovery_error', str(exc)))
            # Wake quickly on a user-requested refresh, or exit promptly on close.
            ticks = max(1, int(self.interval / .1))
            for _ in range(ticks):
                if self.stop_event.wait(.1) or self.refresh_event.is_set(): break
