"""Read-only calibration/reset filter; never writes avatar or shared state."""
import math

CONTROL_TYPES = {'TrackingType': 'Int', 'VRMode': 'Int', 'IsAnimatorEnabled': 'Bool'}
CONTROL_ADDRESSES = frozenset('/avatar/parameters/' + name for name in CONTROL_TYPES)


def control_values(nodes):
    result = {}
    for name, kind in CONTROL_TYPES.items():
        node = nodes.get('/avatar/parameters/' + name, {})
        values = node.get('VALUE', [])
        expected = {'i'} if kind == 'Int' else {'T', 'F'}
        if node.get('TYPE') in expected and node.get('ACCESS', 0) & 1 and values:
            value = values[0]
            if type(value) is (int if kind == 'Int' else bool):
                result[name] = value
    return result


class CalibrationGuard:
    def __init__(self):
        self.avatar = None
        self.controls = {}
        self.baseline = {}
        self.candidate = None
        self.since = 0
        self.paused = False
        self.reason = ''
        self.metadata_pause = False
        self.zeroed = set()
        self.resumed = False

    def reset(self, avatar):
        self.__init__()
        self.avatar = avatar

    def inspect(self, avatar, record, now, controls=None, detect_zero=True):
        if avatar != self.avatar:
            self.reset(avatar)
        if controls is not None:
            self.controls = controls
        self.resumed = False
        tracking = self.controls.get('TrackingType')
        unready = (self.controls.get('IsAnimatorEnabled') is False or tracking == 0
                   or (self.controls.get('VRMode') == 1 and tracking in (1, 2)))
        if unready:
            self.paused = self.metadata_pause = True
            self.reason = '校准或模型初始化期间，暂停记录与恢复'
            self.candidate = None
            return False
        nonzero = {name for name, item in self.baseline.items() if item['value'] != 0}
        zeroed = {name for name in nonzero if name in record and record[name]['value'] == 0}
        if detect_zero and len(zeroed) >= max(3, math.ceil(len(nonzero) * .6)) and not self.metadata_pause:
            self.paused = True
            self.zeroed.update(zeroed)
            self.reason = '检测到多项参数批量归零，已暂停记录并保留共享值'
        if self.paused:
            if self.metadata_pause:
                recovered = (tracking is not None and tracking >= 3) or self.controls.get('IsAnimatorEnabled') is True
            else:
                recovered = all(name in record and record[name]['value'] != 0 for name in self.zeroed)
            if not recovered:
                self.candidate = None
                return False
        # Debounce BOTH full reads and UDP notifications before accepting changes.
        if record != self.candidate:
            self.candidate = {name: dict(item) for name, item in record.items()}
            self.since = now
            return False
        if now - self.since < (3 if self.paused else 2):
            return False
        if self.paused:
            self.resumed = True
            self.paused = self.metadata_pause = False
            self.zeroed.clear()
            self.reason = ''
        self.baseline = {name: dict(item) for name, item in record.items()}
        return True
