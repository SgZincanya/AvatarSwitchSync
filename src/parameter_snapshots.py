"""Manual read-only parameter captures, kept in the application's data directory."""
from datetime import datetime
from pathlib import Path
import threading
import time
import uuid

import avatar_sync as backend


def make_snapshot(avatar_id, nodes, avatars):
    avatar = avatars.get(avatar_id, {})
    by_address = {}
    for definition in avatar.get('defs', {}).values():
        for direction in ('input', 'output'):
            address = definition.get(direction, {}).get('address')
            if address:
                by_address[address] = definition
    rows = []
    for address, node in sorted(nodes.items()):
        if not address.startswith('/avatar/parameters/') or 'TYPE' not in node:
            continue
        definition = by_address.get(address, {})
        name = definition.get('name', address[len('/avatar/parameters/'):])
        values = node.get('VALUE')
        readable = bool(node.get('ACCESS', 0) & 1)
        has_value = readable and isinstance(values, list) and len(values) > 0
        value = values[0] if has_value and len(values) == 1 else values if has_value else None
        wire = node['TYPE']
        kind = {'T':'Bool', 'F':'Bool', 'i':'Int', 'f':'Float', 's':'String', 'd':'Double', 'h':'Int64'}.get(wire, wire)
        rows.append({'name': name, 'type': kind, 'value': value, 'has_value': has_value,
                     'address': address, 'saved_locally': name in avatar['saved_names'] if 'saved_names' in avatar else None})
    return {'version': 1, 'id': uuid.uuid4().hex, 'captured_at': datetime.now().astimezone().isoformat(timespec='seconds'),
            'avatar_id': avatar_id, 'avatar_name': avatar.get('name', avatar_id), 'parameters': rows}


def store_snapshot(data_dir, snapshot):
    identifier = snapshot['id']
    if len(identifier) != 32 or any(c not in '0123456789abcdef' for c in identifier):
        raise ValueError('快照标识无效')
    path = Path(data_dir) / 'snapshots' / (identifier + '.json')
    backend.write_json(path, snapshot)
    return path


def save_startup_backup(data_dir, avatar_id, nodes, avatars, keep=20):
    item = make_snapshot(avatar_id,nodes,avatars)
    if not any(p['has_value'] for p in item['parameters']):
        raise ValueError('无法读取启动前状态，已暂停同步以避免无备份恢复。')
    item['kind'] = 'automatic_start'
    item['captured_at'] = datetime.now().astimezone().isoformat(timespec='microseconds')
    store_snapshot(data_dir,item)
    automatic = [s for s in list_snapshots(data_dir) if s.get('kind')=='automatic_start']
    for old in automatic[keep:]:
        (Path(data_dir)/'snapshots'/(old['id']+'.json')).unlink(missing_ok=True)
    return item


def list_snapshots(data_dir):
    result = []
    for path in (Path(data_dir) / 'snapshots').glob('*.json'):
        try:
            if path.stat().st_size > 10_000_000: continue
            item = backend.read_json(path, {})
            good_rows = isinstance(item.get('parameters'), list) and all(
                isinstance(p,dict) and isinstance(p.get('name'),str) and isinstance(p.get('type'),str)
                and type(p.get('has_value')) is bool and 'value' in p and p.get('saved_locally') in (True,False,None)
                for p in item['parameters'])
            if item.get('version') == 1 and good_rows and item.get('id') == path.stem and isinstance(item.get('captured_at'),str) and isinstance(item.get('avatar_name'),str):
                result.append(item)
        except (ValueError, OSError, AttributeError):
            continue
    return sorted(result, key=lambda s: (s['captured_at'], s['id']), reverse=True)


class CaptureWorker(threading.Thread):
    def __init__(self, data_dir, events):
        super().__init__(daemon=True)
        self.data_dir, self.events = Path(data_dir), events
        self.stop_event = threading.Event()

    def run(self):
        transport = None
        try:
            transport = backend.Transport(lambda _: None)
            deadline = time.monotonic() + 7
            while not self.stop_event.is_set() and time.monotonic() < deadline:
                transport.changes()
                capture = transport.snapshot()
                changes = transport.changes()
                if capture and (not changes or changes[-1] == capture[0]):
                    item = make_snapshot(capture[0], capture[1], backend.inventory())
                    if not item['parameters']:
                        raise ValueError('当前模型未提供可读取的参数表，请确认已启用 OSC。')
                    if self.stop_event.is_set(): return
                    store_snapshot(self.data_dir, item)
                    self.events.put(('snapshot_saved', item['id']))
                    return
                self.stop_event.wait(.3)
            if not self.stop_event.is_set():
                raise ValueError('未读到当前模型，请确认 VRChat 已启动并启用 OSC，然后重试。')
        except Exception as exc:
            self.events.put(('snapshot_error', str(exc)))
        finally:
            try:
                if transport: transport.close()
            finally:
                self.events.put(('snapshot_finished', None))
