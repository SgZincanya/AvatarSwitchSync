"""State machine independent of networking and the user interface."""
import math
import re
import time

TYPES = {"Bool": (bool, "T"), "Int": (int, "i"), "Float": (float, "f")}
TRACKING_SETTINGS = {"EyeTrackingEnable", "MouthTrackingEnable", "VisemesEnable", "FacialExpressionsDisabled"}
TRACKING_SETTINGS.update({"FT/Local/EyeLidSmoother", "FT/Local/EyeLookSmoother", "FT/Local/MouthSmoother", "FT/Local/TongueSmoother", "FT/EyelidSync", "ForceTongueOutToggle"})


def protected(name):
    # A positive allowlist is still required; this is an additional exclusion.
    if name in TRACKING_SETTINGS:
        return False
    if name in {'TrackingType', 'VRMode', 'IsAnimatorEnabled'}:
        return True
    return (bool(re.search(r"(?i)^(FT/|VFH/|OGB|/|Eye|Brow|Jaw|Mouth|Lip|Cheek|Nose|Tongue|Viseme|Tracking|Gesture|Velocity|Angular|Scale|Head|LeftEye|RightEye)", name)) or
            bool(re.search(r"(?i)(SyncData|SyncIndex|AutoBool|IsLocal|VRCEmote|PreviewMode|reset|重置|chongzhi)", name)))


def default_exclusion(name):
    if protected(name):
        return "实时追踪、同步中间数据或重置动作"
    if name in {"F_Set", "F_Parts"} or re.search(r"(?i)(^ZincatParts_|衣服|服装|衣装|浴袍|袜|鞋|裙|裤|上衣|下装|内衣|胸罩)", name):
        return "衣服或衣服分件（按名称筛选）"
    return ""


def valid(value, kind):
    if kind == "Bool":
        return type(value) is bool
    if kind == "Int":
        return type(value) is int and -2147483648 <= value <= 2147483647
    return kind == "Float" and type(value) in (float, int) and math.isfinite(value) and abs(value) <= 3.4e38


def equal(a, b, kind):
    return abs(a - b) < 0.0001 if kind == "Float" else type(a) is type(b) and a == b


class Engine:
    def __init__(self, config, state, send, save, log, clock=time.monotonic, report=None, seed_missing=True):
        self.config, self.state = config, state
        self.send, self.save, self.log, self.clock = send, save, log, clock
        self.avatar = None
        self.phase = "waiting"
        self.group = None
        self.deadline = 0
        self.pending = {}
        self.blocked = set()
        self.attempts = 0
        self.report = report or (lambda _: None)
        self.result = {'confirmed':0,'skipped':0,'failed':0,'total':0}
        self.seed_missing = seed_missing

    def change(self, avatar, force=False):
        if avatar == self.avatar and not force:
            return
        self.avatar = avatar
        self.group = next((g for g in self.config.get("groups", []) if avatar in g["avatars"]), None)
        self.phase = "settling" if self.group else "outside"
        self.deadline = self.clock() + 3.0
        self.pending, self.blocked = {}, set()
        self.attempts = 0
        self.result = {'confirmed':0,'skipped':0,'failed':0,'total':len(self.entries())}
        self.log("切换模型，等待初始化" if self.group else "当前模型不在共享组内")

    def disconnect(self):
        if self.avatar is not None:
            self.log("连接中断；已暂停记录与恢复")
        self.avatar, self.group, self.phase = None, None, "waiting"

    def entries(self):
        if not self.group:
            return []
        return [p for p in self.group.get("parameters", [])
                if p.get("enabled") and not protected(p["name"]) and p.get("type") in TYPES]

    def current_record(self, live):
        """Read only selected, validated values for an explicit session start."""
        return {p['name']: {'type': p['type'], 'value': live[p['name']]['value']}
                for p in self.entries() if p['name'] in live
                and live[p['name']]['type'] == p['type']
                and live[p['name']].get('writable')
                and valid(live[p['name']]['value'], p['type'])}

    def snapshot(self, avatar, live):
        """live: logical name -> {value, type, writable}; caller validates cache addresses."""
        if avatar != self.avatar:
            self.change(avatar)
        if not self.group or self.clock() < self.deadline:
            return
        shared = self.state.setdefault(self.group["id"], {})
        available = {p["name"]: p for p in self.entries()
                     if p["name"] in live and live[p["name"]]["type"] == p["type"]
                     and live[p["name"]].get("writable")
                     and valid(live[p["name"]]["value"], p["type"])}
        if not self.seed_missing:
            available = {name:p for name,p in available.items()
                         if name in shared and shared[name].get('type')==p['type']
                         and valid(shared[name].get('value'),p['type'])}
        if self.phase == "settling":
            self.blocked = {p["name"] for p in self.entries()} - set(available)
            for name, p in available.items():
                old = shared.get(name)
                if old and old.get("type") == p["type"] and valid(old.get("value"), p["type"]):
                    if not equal(old["value"], live[name]["value"], p["type"]):
                        self.pending[name] = old["value"]
                else:
                    shared[name] = {"type": p["type"], "value": live[name]["value"]}
            self.save(self.state)
            missing = len(self.entries()) - len(available)
            self.result.update(skipped=missing,total=len(self.entries()))
            if missing:
                self.log(f"{missing} 项不可读写或尚无共享记录，已跳过")
            self.phase = "restoring"
            self._restore(available)
            return
        if self.phase == "restoring":
            for name in list(self.pending):
                if name in available and equal(self.pending[name], live[name]["value"], available[name]["type"]):
                    del self.pending[name]
            if self.pending and self.attempts < 3:
                self._restore(available)
                return
            self.blocked.update(self.pending)
            if self.pending:
                self.log("恢复未确认，暂停记录这些项，保留原共享值：" + "、".join(sorted(self.pending)))
            self.phase = "active"
            self.result.update(confirmed=len(self.entries())-self.result['skipped']-len(self.pending),failed=len(self.pending))
            self.report(dict(self.result))
            self.log(f"共享已就绪：确认 {self.result['confirmed']} 项，跳过 {self.result['skipped']} 项，未确认 {self.result['failed']} 项")
            return
        if self.phase == "active":
            changed = False
            for name, p in available.items():
                if name in self.blocked:
                    continue
                value = live[name]["value"]
                old = shared.get(name)
                if not old or not equal(old["value"], value, p["type"]):
                    shared[name] = {"type": p["type"], "value": value}
                    changed = True
                    self.log(f"已记住：{name} = {value}")
            if changed:
                self.save(self.state)

    def _restore(self, available):
        for name, value in self.pending.items():
            if name in available:
                self.send(name, available[name]["type"], value)
        self.attempts += 1
        self.deadline = self.clock() + 1.2
