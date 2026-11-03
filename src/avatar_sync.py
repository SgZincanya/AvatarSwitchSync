"""Avatar Switch Sync: local OSCQuery client with an explicit parameter allowlist."""
import collections
import ctypes
import hashlib
import http.server
import json
import os
from pathlib import Path
import queue
import socket
import struct
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
import tkinter as tk
from tkinter import ttk, messagebox

from zeroconf import Zeroconf, ServiceInfo, ServiceBrowser, IPVersion
from sync_core import Engine, protected, valid, default_exclusion

BASE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
DATA = BASE / "data" if (BASE / "portable.flag").exists() else Path(os.environ.get("LOCALAPPDATA", str(BASE))) / "AvatarSwitchSync"
CACHE = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "AppData/LocalLow/VRChat/VRChat/OSC"


def read_json(path, fallback):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else fallback


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def local_http_opener():
    # OSCQuery only uses local HTTP. build_opener also creates HTTPSHandler,
    # which initializes unnecessary OpenSSL resources in the frozen application.
    opener = urllib.request.OpenerDirector()
    for handler in (urllib.request.ProxyHandler({}), urllib.request.HTTPHandler(),
                    urllib.request.HTTPDefaultErrorHandler(), urllib.request.HTTPErrorProcessor()):
        opener.add_handler(handler)
    return opener


def inventory(root=CACHE):
    result = {}
    for path in root.glob("*/Avatars/*.json"):
        try:
            item = read_json(path, {})
            saved_path = path.parents[3] / "LocalAvatarData" / path.parents[1].name / item["id"]
            # OSC/<user>/Avatars/<file> -> VRChat/LocalAvatarData/<user>/<id>
            saved_status = 'available' if saved_path.exists() else 'missing'
            try:
                saved = read_json(saved_path, {})
            except (ValueError, OSError):
                saved, saved_status = {}, 'unavailable'
            if not isinstance(saved,dict):
                saved, saved_status = {}, 'unavailable'
            saved_rows = saved.get('animationParameters', [])
            if not isinstance(saved_rows,list):
                saved_rows, saved_status = [], 'unavailable'
            item["saved_names"] = {p['name'] for p in saved_rows if isinstance(p,dict) and isinstance(p.get('name'),str)}
            item['saved_status'] = saved_status
            item["defs"] = {p["name"]: p for p in item.get("parameters", [])}
            item["mtime"] = path.stat().st_mtime
            if item["id"] not in result or result[item["id"]]["mtime"] < item["mtime"]:
                result[item["id"]] = item
        except (ValueError, KeyError, OSError, TypeError, AttributeError):
            continue
    return result


def candidates(avatars, selected):
    if not selected or any(a not in avatars for a in selected):
        return []
    common = set.intersection(*(set(avatars[a]["defs"]) & avatars[a]["saved_names"] for a in selected))
    result = []
    for name in sorted(common):
        definitions = [avatars[a]["defs"][name] for a in selected if name in avatars[a]["defs"]]
        kinds = {p.get("input", {}).get("type") for p in definitions}
        if len(kinds) != 1 or next(iter(kinds)) not in ("Bool", "Int", "Float"):
            continue
        if all(p.get("input", {}).get("type") == p.get("output", {}).get("type") for p in definitions):
            reason = default_exclusion(name)
            result.append({"name": name, "type": next(iter(kinds)), "enabled": not bool(reason), "reason": reason})
    return result


def compatible_parameter(avatars, group, entry):
    """Every member must expose the same saved type, including explicit name mappings."""
    if not group.get('avatars') or entry.get('type') not in ('Bool', 'Int', 'Float'):
        return False
    for aid in group['avatars']:
        avatar = avatars.get(aid)
        actual = entry.get('mapping', {}).get(aid, entry['name'])
        if not avatar or actual not in avatar.get('saved_names', set()):
            return False
        definition = avatar.get('defs', {}).get(actual, {})
        if any(definition.get(direction, {}).get('type') != entry['type'] for direction in ('input', 'output')):
            return False
    return True


def common_config(config, avatars):
    import copy
    result = copy.deepcopy(config)
    for group in result.get('groups', []):
        group['parameters'] = [p for p in group.get('parameters', []) if compatible_parameter(avatars, group, p)]
    return result


def osc_string(value):
    raw = value.encode("utf-8") + b"\0"
    return raw + b"\0" * (-len(raw) % 4)


def osc_packet(address, kind, value):
    if not address.startswith("/avatar/parameters/") or not valid(value, kind):
        raise ValueError("拒绝非法参数或地址")
    tag = ("T" if value else "F") if kind == "Bool" else {"Int": "i", "Float": "f"}[kind]
    payload = b"" if kind == "Bool" else struct.pack(">i" if kind == "Int" else ">f", value)
    return osc_string(address) + osc_string("," + tag) + payload


def avatar_changes(raw, depth=0):
    if depth > 8:
        return []
    if raw.startswith(b"#bundle\0"):
        cursor, ids = 16, []
        while cursor + 4 <= len(raw):
            length = struct.unpack_from(">I", raw, cursor)[0]
            cursor += 4
            if not 0 < length <= len(raw) - cursor:
                break
            ids.extend(avatar_changes(raw[cursor:cursor+length], depth+1))
            cursor += length
        return ids
    def string_at(offset):
        end = raw.index(b"\0", offset)
        return raw[offset:end].decode("utf-8"), (end + 4) & ~3
    try:
        address, cursor = string_at(0)
        if address != "/avatar/change":
            return []
        tags, cursor = string_at(cursor)
        if tags == ",s":
            value, _ = string_at(cursor)
            return [value] if value.startswith("avtr_") else []
    except (ValueError, UnicodeError):
        pass
    return []


def flatten(node, result=None):
    result = {} if result is None else result
    if "FULL_PATH" in node:
        result[node["FULL_PATH"]] = node
    for child in node.get("CONTENTS", {}).values():
        flatten(child, result)
    return result


def osc_updates(raw, accepted, depth=0):
    if depth>8:return {}
    if raw.startswith(b'#bundle\0'):
        result,cursor={},16
        while cursor+4<=len(raw):
            length=struct.unpack_from('>I',raw,cursor)[0]
            cursor+=4
            if not 0<length<=len(raw)-cursor:break
            result.update(osc_updates(raw[cursor:cursor+length],accepted,depth+1))
            cursor+=length
        return result
    try:
        end=raw.index(b'\0')
        address=raw[:end].decode('utf-8')
        if address not in accepted:return {}
        cursor=(end+4)&~3
        end=raw.index(b'\0',cursor)
        tag=raw[cursor:end].decode('ascii')
        cursor=(end+4)&~3
        if tag in (',T',',F'):kind,value='Bool',tag==',T'
        elif tag==',i':kind,value='Int',struct.unpack_from('>i',raw,cursor)[0]
        elif tag==',f':kind,value='Float',struct.unpack_from('>f',raw,cursor)[0]
        else:return {}
        return {address:(kind,value)} if valid(value,kind) else {}
    except (ValueError,UnicodeError,struct.error):return {}


class Transport:
    def __init__(self, log):
        self.log = log
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        self.sock.settimeout(0.2)
        self.udp_port = self.sock.getsockname()[1]
        self.closed = threading.Event()
        self.notices = queue.Queue(maxsize=100)
        self.update_lock = threading.Lock()
        self.parameter_updates = {}
        self.listen_addresses = frozenset()
        self.received_packets = 0
        self.sent_packets = 0
        self.receiver = threading.Thread(target=self._receive, daemon=True)
        self.receiver.start()
        self.services = {}
        self.service_lock = threading.Lock()
        self.endpoint = None
        self.target = None
        self.last_definitions = {}
        owner = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                path = urllib.parse.urlsplit(self.path)
                if path.query == "HOST_INFO":
                    value = {"NAME": "AvatarSwitchSync", "OSC_IP": "127.0.0.1", "OSC_PORT": owner.udp_port,
                             "OSC_TRANSPORT": "UDP", "EXTENSIONS": {"ACCESS": True, "VALUE": True}}
                else:
                    change = {"FULL_PATH": "/avatar/change", "TYPE": "s", "ACCESS": 2}
                    avatar = {"FULL_PATH": "/avatar", "CONTENTS": {"change": change}}
                    value = {"FULL_PATH": "/", "CONTENTS": {"avatar": avatar}}
                    if path.path == "/avatar":
                        value = avatar
                    elif path.path == "/avatar/change":
                        value = change
                    elif path.path != "/":
                        self.send_error(404)
                        return
                raw = json.dumps(value).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        self.http = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http.daemon_threads = True
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.zc = Zeroconf(ip_version=IPVersion.V4Only)
        ident = "AvatarSwitchSync-" + uuid.uuid4().hex[:8]
        self.adverts = []
        for service, port in [("_oscjson._tcp.local.", self.http.server_port), ("_osc._udp.local.", self.udp_port)]:
            info = ServiceInfo(service, ident + "." + service, addresses=[socket.inet_aton("127.0.0.1")],
                               port=port, server=ident + ".local.")
            self.zc.register_service(info)
            self.adverts.append(info)
        self.browser = ServiceBrowser(self.zc, "_oscjson._tcp.local.", self)
        self.opener = local_http_opener()
        self.log(f"独立 OSC 接收端口：{self.udp_port}；未占用 9000/9001")

    def add_service(self, zc, kind, name):
        self.update_service(zc, kind, name)

    def update_service(self, zc, kind, name):
        if "vrchat" not in name.lower():
            return
        info = zc.get_service_info(kind, name, timeout=1000)
        if info:
            # Windows VRChat's HTTP service is local-only; never query another PC.
            local = {"127.0.0.1"}
            try:
                local.update(socket.gethostbyname_ex(socket.gethostname())[2])
            except OSError:
                pass
            if set(info.parsed_addresses()) & local:
                with self.service_lock:
                    self.services[name] = info.port

    def remove_service(self, zc, kind, name):
        with self.service_lock:
            port = self.services.pop(name, None)
        if self.endpoint == port:
            self.endpoint = None

    def get(self, port, path):
        with self.opener.open(f"http://127.0.0.1:{port}{path}", timeout=0.7) as response:
            return json.loads(response.read(8_000_000))

    def snapshot(self):
        if not self.endpoint:
            with self.service_lock:
                ports = list(self.services.values())
            for port in dict.fromkeys(ports + [9001]):
                try:
                    host = self.get(port, "/?HOST_INFO")
                    if str(host.get("NAME", "")).lower().startswith("vrchat"):
                        udp = host.get("OSC_PORT")
                        if type(udp) is int and 0 < udp < 65536:
                            self.endpoint, self.target = port, ("127.0.0.1", udp)
                            self.log("已发现 VRChat，正在读取当前模型")
                            break
                except (OSError, ValueError):
                    continue
        if not self.endpoint:
            return None
        try:
            nodes = flatten(self.get(self.endpoint, "/avatar"))
            identity = nodes.get("/avatar/change", {}).get("VALUE", [])
            if not identity or not isinstance(identity[0], str) or not identity[0].startswith("avtr_"):
                return None
            # A second identity read rejects a tree fetched across an avatar change.
            after = self.get(self.endpoint, "/avatar/change").get("VALUE", [])
            if after != identity:
                return None
            return identity[0], nodes
        except (OSError, ValueError):
            self.endpoint, self.target = None, None
            return None

    def changes(self):
        ids = []
        while True:
            try:
                ids.append(self.notices.get_nowait())
            except queue.Empty:
                break
        return ids

    def _receive(self):
        # Drain continuously: eye/face/physics traffic must never bury a switch event.
        while not self.closed.is_set():
            try:
                raw, addr = self.sock.recvfrom(65535)
                self.received_packets += 1
                if addr[0] != "127.0.0.1":
                    continue
                if raw.startswith((b"/avatar/change\0", b"#bundle\0")):
                    for avatar_id in avatar_changes(raw):
                        try:
                            self.notices.put_nowait(avatar_id)
                        except queue.Full:
                            try:self.notices.get_nowait()
                            except queue.Empty:pass
                            self.notices.put_nowait(avatar_id)
                if self.listen_addresses and raw.startswith((b'/avatar/parameters/',b'#bundle\0')):
                    updates=osc_updates(raw,self.listen_addresses)
                    if updates:
                        with self.update_lock:self.parameter_updates.update(updates)
            except socket.timeout:
                continue
            except OSError:
                break

    def take_updates(self):
        with self.update_lock:
            updates=self.parameter_updates
            self.parameter_updates={}
        return updates

    def send(self, name, kind, value):
        definition = self.last_definitions.get(name)
        if not definition or protected(name) or not self.target:
            return
        address = definition["input"]["address"]
        if protected(definition["name"]):
            return
        self.sock.sendto(osc_packet(address, kind, value), self.target)
        self.sent_packets += 1
        self.log(f"恢复：{name} = {value}")

    def close(self):
        self.browser.cancel()
        for info in self.adverts:
            self.zc.unregister_service(info)
        self.zc.close()
        self.http.shutdown()
        self.http.server_close()
        self.closed.set()
        self.sock.close()
        self.receiver.join(timeout=1)


def live_values(avatar, nodes, group):
    live, definitions = {}, {}
    if not group:
        return live, definitions
    for entry in group["parameters"]:
        logical = entry["name"]
        actual = entry.get("mapping", {}).get(avatar["id"], logical)
        if actual not in avatar.get("saved_names", set()):
            continue
        definition = avatar["defs"].get(actual)
        if not definition or protected(logical) or protected(actual):
            continue
        inp, out = definition.get("input", {}), definition.get("output", {})
        if inp.get("type") != entry["type"] or out.get("type") != entry["type"]:
            continue
        in_node, node = nodes.get(inp.get("address"), {}), nodes.get(out.get("address"), {})
        values = node.get("VALUE", [])
        wire_type = node.get("TYPE")
        expected = {"Bool": {"T", "F"}, "Int": {"i"}, "Float": {"f"}}[entry["type"]]
        if not values or wire_type not in expected or not (node.get("ACCESS", 0) & 1):
            continue
        # Access 2 means the VRChat endpoint can receive writes.
        live[logical] = {"value": values[0], "type": entry["type"],
                         "writable": bool(in_node.get("ACCESS", 0) & 2)}
        definitions[logical] = definition
    return live, definitions


class Worker(threading.Thread):
    def __init__(self, config, events, data_dir=None, capture_current=True, add_group=None):
        super().__init__(daemon=True)
        self.config, self.events = config, events
        self.data_dir = Path(data_dir) if data_dir is not None else DATA
        self.stop_event = threading.Event()
        self.commands = queue.Queue()
        self.capture_current = capture_current
        self.add_group = add_group

    def set_add_group(self, group_id):
        self.commands.put(group_id)

    def log(self, text):
        self.events.put(("log", text))

    def run(self):
        import copy
        from parameter_snapshots import save_startup_backup
        from runtime_diagnostics import Diagnostics
        from calibration_guard import CalibrationGuard, CONTROL_ADDRESSES, CONTROL_TYPES, control_values
        from enrollment import enroll
        transport = None
        state = None
        dirty = False
        last_flush = time.monotonic()
        def persist(_):
            nonlocal dirty
            dirty = True
        try:
            state = read_json(self.data_dir / "state.json", {})
            transport = Transport(self.log)
            effective = common_config(self.config, inventory())
            engine = Engine(effective, state, transport.send, persist, self.log,
                            clock=time.monotonic,report=lambda result:self.events.put(('result',result)),seed_missing=self.capture_current)
            diagnostics = Diagnostics()
            guard = CalibrationGuard()
            guard_notice = ''
            enrollment_notice = ''
            last_good = time.monotonic()
            next_read = 0
            backup_complete = False
            live, output_lookup = {}, {}
            last_live_event = 0
            while not self.stop_event.is_set():
                now = time.monotonic()
                while True:
                    try: self.add_group = self.commands.get_nowait()
                    except queue.Empty: break
                    if self.add_group:self.capture_current = False
                    next_read = 0
                changes = transport.changes()
                if changes:
                    guard.reset(None)
                    for avatar_id in changes:engine.change(avatar_id,force=True)
                    self.loaded_avatar = None
                    next_read = 0
                    live, output_lookup = {}, {}
                    transport.take_updates()
                    transport.listen_addresses = frozenset()
                if now >= next_read:
                    started = time.perf_counter()
                    snapshot = transport.snapshot()
                    diagnostics.record_read(time.perf_counter()-started)
                    changes = transport.changes()
                    for avatar_id in changes:
                        guard.reset(None)
                        engine.change(avatar_id,force=True)
                        self.loaded_avatar = None
                    if snapshot and (not changes or changes[-1]==snapshot[0]):
                        avatar_id,nodes = snapshot
                        last_good = time.monotonic()
                        if avatar_id != getattr(self,'loaded_avatar',None):
                            self.avatars = inventory()
                            effective['groups'] = common_config(self.config,self.avatars)['groups']
                            self.loaded_avatar = avatar_id
                        engine.change(avatar_id)
                        if self.add_group and time.monotonic() >= engine.deadline:
                            self.avatars = inventory()
                            updated, message = enroll(self.config,self.add_group,avatar_id,self.avatars)
                            if message != enrollment_notice:
                                enrollment_notice = message
                                if message:
                                    self.log(message)
                                    self.events.put(('enrollment_status',message))
                            if updated is not None:
                                # Persist membership before applying the existing shared values.
                                if dirty:
                                    write_json(self.data_dir/'state.json',state)
                                    dirty = False
                                write_json(self.data_dir/'config.json',updated)
                                self.config = updated
                                effective['groups'] = common_config(updated,self.avatars)['groups']
                                engine.change(avatar_id,force=True)
                                guard.reset(None)
                                self.log(f'已添加模型：{self.avatars[avatar_id]["name"]}，准备同步已有共享设置')
                                self.events.put(('group_enrolled',{'config':copy.deepcopy(updated),'avatars':self.avatars,'group':self.add_group,'avatar':avatar_id}))
                            else:
                                effective['groups'] = common_config(self.config,self.avatars)['groups']
                        engine.group = next((g for g in effective['groups'] if avatar_id in g['avatars']),None)
                        avatar = self.avatars.get(avatar_id)
                        if avatar:
                            live,definitions = live_values(avatar,nodes,engine.group)
                            transport.last_definitions = definitions
                            enabled_names={p['name'] for p in engine.entries()}
                            output_lookup = {d['output']['address']:name for name,d in definitions.items() if name in enabled_names}
                            transport.listen_addresses = frozenset(output_lookup) | CONTROL_ADDRESSES
                            allowed = guard.inspect(avatar_id,engine.current_record(live),time.monotonic(),control_values(nodes),detect_zero=engine.phase!='restoring')
                            if guard.resumed:
                                engine.change(avatar_id,force=True)
                                self.log('校准保护已解除，等待模型稳定后恢复共享设置')
                            if allowed and engine.group and engine.phase=='settling' and time.monotonic()>=engine.deadline and not backup_complete:
                                self.events.put(('status','正在保存启动前备份…'))
                                item = save_startup_backup(self.data_dir,avatar_id,nodes,self.avatars)
                                self.events.put(('backup_saved',item['id']))
                                changes_after_backup = transport.changes()
                                if changes_after_backup:
                                    for new_id in changes_after_backup:engine.change(new_id,force=True)
                                    self.loaded_avatar = None
                                    next_read = 0
                                    continue
                                if self.stop_event.is_set():break
                                if self.capture_current:
                                    current = engine.current_record(live)
                                    if not current:
                                        raise ValueError('当前模型没有可读取的共享参数，未更新共享记录')
                                    updated = copy.deepcopy(state)
                                    updated.setdefault(engine.group['id'], {}).update(current)
                                    write_json(self.data_dir/'state.json', updated)
                                    state.clear()
                                    state.update(updated)
                                    dirty = False
                                    last_flush = time.monotonic()
                                    self.events.put(('startup_saved',len(current)))
                                    self.log(f'已将当前模型的 {len(current)} 项参数保存为最新共享记录')
                                else:
                                    self.log('保留已有共享记录，准备恢复到当前模型')
                                backup_complete = True
                            if allowed:engine.snapshot(avatar_id,live)
                            phase = {'settling':'等待模型稳定','restoring':'恢复并确认中','active':'共享中','outside':'当前模型不在共享组','waiting':'等待连接'}.get(engine.phase,engine.phase)
                            self.events.put(('status',guard.reason if guard.paused else f"{avatar['name']} · {phase}"))
                        else:self.events.put(('status','当前模型尚无本地缓存，等待自动发现'))
                    elif time.monotonic()-last_good>2.5:
                        engine.disconnect()
                        guard.reset(None)
                        live,output_lookup = {},{}
                        transport.listen_addresses = frozenset()
                        self.events.put(('status','等待 VRChat 连接'))
                    next_read = time.monotonic()+(2.0 if engine.phase=='active' else .45)
                updates = transport.take_updates()
                if engine.group and time.monotonic()-last_good<2.5:
                    for address,(kind,value) in updates.items():
                        control = address.rsplit('/',1)[-1]
                        if address in CONTROL_ADDRESSES and CONTROL_TYPES[control] == kind:
                            guard.controls[control] = value
                        name = output_lookup.get(address)
                        if name in live and live[name]['type']==kind:
                            live[name]['value'] = value
                    allowed = guard.inspect(engine.avatar,engine.current_record(live),time.monotonic(),detect_zero=engine.phase!='restoring')
                    if guard.resumed:
                        engine.change(engine.avatar,force=True)
                        next_read = 0
                        self.log('校准保护已解除，等待模型稳定后恢复共享设置')
                    if allowed and engine.phase=='active':engine.snapshot(engine.avatar,live)
                    if guard.paused:
                        self.events.put(('status',guard.reason))
                if guard.reason != guard_notice:
                    guard_notice = guard.reason
                    if guard_notice:self.log(guard_notice+'；如为主动批量重置，可停止后重新开始共享')
                if dirty and time.monotonic()-last_flush>=.5:
                    write_json(self.data_dir/'state.json',state)
                    dirty=False
                    last_flush=time.monotonic()
                if time.monotonic()-last_live_event>=1:
                    self.events.put(('live',{'state':copy.deepcopy(state),'phase':engine.phase}))
                    last_live_event=time.monotonic()
                sample=diagnostics.sample(transport)
                if sample:self.events.put(('diagnostics',sample))
                self.stop_event.wait(.1)
        except Exception as exc:
            import traceback
            self.log(traceback.format_exc())
            self.log(f'已停止：{type(exc).__name__}: {exc}')
            self.events.put(('error',str(exc)))
        finally:
            try:
                try:
                    if dirty and state is not None:write_json(self.data_dir/'state.json',state)
                finally:
                    if transport:transport.close()
            finally:self.events.put(('stopped','同步已停止'))


def App(root):
    from desktop_ui import App as DesktopApp
    return DesktopApp(root)


def main():
    if any(arg in sys.argv for arg in ('--steamvr-enable-autostart','--steamvr-disable-autostart')):
        from steamvr_startup import configure
        try:
            result=configure(BASE/'AvatarSwitchSync.exe','--steamvr-enable-autostart' in sys.argv)
        except Exception as exc:
            write_json(DATA/'steamvr-startup-result.json',{'error':str(exc)})
            raise SystemExit(1)
        write_json(DATA/'steamvr-startup-result.json',result)
        return
    if '--diagnose-connection' in sys.argv:
        import traceback
        transport = None
        result = {}
        try:
            transport = Transport(lambda _: None)
            result['connection_ready'] = True
        except Exception:
            result['traceback'] = traceback.format_exc()
        finally:
            if transport:transport.close()
        write_json(DATA/'connection-diagnostic.json',result)
        return
    if os.name == 'nt':
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError, OSError):
            pass
    mutex = None
    start_event = None
    if os.name == "nt":
        mutex_name = "Local\\AvatarSwitchSync"
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.restype = ctypes.c_void_p
        mutex = kernel.CreateMutexW(None, False, mutex_name)
        if ctypes.get_last_error() == 183:
            if '--start-sharing' in sys.argv:
                from steamvr_startup import request_start
                request_start()
            else:messagebox.showinfo("已在运行", "同步器已经打开，请使用已有窗口。")
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(mutex)
            return
    root = tk.Tk()
    try:
        DATA.mkdir(parents=True, exist_ok=True)
        app=App(root)
        if os.name=='nt':
            from steamvr_startup import create_event,poll_start
            start_event=create_event()
            poll_start(root,app,start_event)
        if '--start-sharing' in sys.argv:root.after(200,lambda:app.start(capture_current=False))
        root.mainloop()
    except Exception as exc:
        messagebox.showerror("无法启动", str(exc), parent=root)
        root.destroy()
    finally:
        if start_event:
            from steamvr_startup import kernel as event_kernel
            event_kernel().CloseHandle(start_event)
        if mutex:
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(mutex)


if __name__ == "__main__":
    main()
