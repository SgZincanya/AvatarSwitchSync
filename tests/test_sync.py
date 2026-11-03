import copy
import json
from pathlib import Path
import socket
import struct
import sys
import tempfile
import time
import unittest
import urllib.request

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from sync_core import Engine, protected
from avatar_sync import (inventory, candidates, osc_packet, osc_string, avatar_changes,
                         Transport, flatten, live_values, write_json, read_json)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.sent, self.saves, self.logs = [], [], []
        self.config = {"groups": [{"id": "g", "avatars": ["A", "B"], "parameters": [
            {"name": "Glasses", "type": "Bool", "enabled": True},
            {"name": "Hair", "type": "Int", "enabled": True},
            {"name": "FT/v2/EyeLeftX", "type": "Float", "enabled": True},
            {"name": "EyeLeftX", "type": "Float", "enabled": True}]}]}
        self.state = {"g": {"Glasses": {"type": "Bool", "value": True}, "Hair": {"type": "Int", "value": 2}}}
        self.engine = Engine(self.config, self.state, lambda *v: self.sent.append(v),
                             lambda s: self.saves.append(copy.deepcopy(s)), self.logs.append, lambda: self.now)

    def snapshot(self, aid="A", glasses=False, hair=0):
        self.engine.snapshot(aid, {"Glasses": {"type": "Bool", "value": glasses, "writable": True},
                                   "Hair": {"type": "Int", "value": hair, "writable": True},
                                   "FT/v2/EyeLeftX": {"type": "Float", "value": .8, "writable": True},
                                   "EyeLeftX": {"type": "Float", "value": .2, "writable": True}})

    def test_initial_values_do_not_destroy_shared_state_and_confirm_then_record(self):
        self.snapshot()
        self.assertEqual(self.sent, [])
        self.now = 3.1
        self.snapshot()
        self.assertEqual(set(self.sent), {("Glasses", "Bool", True), ("Hair", "Int", 2)})
        self.assertTrue(self.state["g"]["Glasses"]["value"])
        self.now = 4.4
        self.snapshot(glasses=True, hair=2)
        self.assertEqual(self.engine.phase, "active")
        self.snapshot(glasses=False, hair=3)
        self.assertEqual(self.state["g"]["Hair"]["value"], 3)
        self.assertFalse(self.state["g"]["Glasses"]["value"])
        self.assertEqual(len(self.sent), 2)

    def test_failed_restore_bounded_and_never_records_failed_initial_value(self):
        self.snapshot()
        for t in (3.1, 4.4, 5.7, 7, 9, 15):
            self.now = t
            self.snapshot()
        self.assertEqual(len(self.sent), 6)
        self.assertTrue(self.state["g"]["Glasses"]["value"])
        self.assertEqual(self.engine.blocked, {"Glasses", "Hair"})

    def test_switch_cancels_previous_restore_and_group_outside_never_writes(self):
        self.snapshot()
        self.now = 3.1
        self.snapshot()
        before = len(self.sent)
        self.snapshot("B")
        self.assertEqual(len(self.sent), before)
        self.now = 4
        self.snapshot("OUTSIDE")
        self.now = 50
        self.snapshot("OUTSIDE")
        self.assertEqual(len(self.sent), before)

    def test_disconnect_requarantines(self):
        self.snapshot()
        self.now = 3.1
        self.snapshot()
        self.engine.disconnect()
        self.now = 100
        before = len(self.sent)
        self.snapshot()
        self.assertEqual(len(self.sent), before)
        self.assertEqual(self.engine.phase, "settling")

    def test_late_missing_parameter_does_not_overwrite_shared_value(self):
        self.engine.snapshot("A", {})
        self.now = 3.1
        self.engine.snapshot("A", {})
        self.now = 4.4
        self.engine.snapshot("A", {})
        self.now = 6
        self.snapshot()
        self.assertTrue(self.state["g"]["Glasses"]["value"])
        self.assertEqual(self.sent, [])

    def test_no_seeded_state_captures_first_live_model_without_writing(self):
        self.state.clear()
        self.snapshot()
        self.now = 3.1
        self.snapshot(glasses=True, hair=4)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.state["g"]["Hair"]["value"], 4)

    def test_type_mismatch_and_invalid_values_skipped(self):
        self.engine.snapshot("A", {})
        self.now = 4
        self.engine.snapshot("A", {"Glasses": {"type": "Int", "value": 1, "writable": True},
                                   "Hair": {"type": "Int", "value": True, "writable": True}})
        self.assertEqual(self.sent, [])
        self.assertEqual(self.engine.blocked, {"Glasses", "Hair"})


class ProtocolTests(unittest.TestCase):
    def test_eye_and_compression_protection(self):
        for name in ["FT/v2/EyeLidLeft", "EyeLeftX", "VF57_SyncDataBool1", "__MA/AutoParam/xSyncIndex", "/tracking/eye/CenterPitchYaw", "FullReset"]:
            self.assertTrue(protected(name), name)
        for name in ["EyeTrackingEnable", "MouthTrackingEnable", "FT/Local/EyeLookSmoother", "VF126_WH Lollipop/PhysBones"]:
            self.assertFalse(protected(name), name)
        self.assertFalse(protected("头发"))

    def test_wire_encoding_and_bundles(self):
        packet = osc_packet("/avatar/parameters/\\u5934\\u53d1", "Int", 2)
        self.assertTrue(packet.endswith(struct.pack(">i", 2)))
        self.assertEqual(len(packet) % 4, 0)
        self.assertTrue(osc_packet("/avatar/parameters/X", "Bool", False).endswith(b",F\0\0"))
        with self.assertRaises(ValueError):
            osc_packet("/tracking/eye/CenterPitchYaw", "Float", .2)
        raw = osc_string("/avatar/change") + osc_string(",s") + osc_string("avtr_test")
        bundle = b"#bundle\0" + b"\0" * 8 + struct.pack(">I", len(raw)) + raw
        self.assertEqual(avatar_changes(bundle), ["avtr_test"])
        self.assertEqual(avatar_changes(b"bad"), [])

    def test_cache_reads_saved_data_from_isolated_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            aid='avtr_fixture_saved'
            definitions=[{'name':name,'input':{'type':'Bool'},'output':{'type':'Bool'}} for name in ['头发','EyeTrackingEnable']]
            write_json(base/'OSC/usr_fixture/Avatars'/f'{aid}.json',{'id':aid,'name':'测试参考模型','parameters':definitions})
            write_json(base/'LocalAvatarData/usr_fixture'/aid,{'animationParameters':[{'name':d['name'],'value':True} for d in definitions]})
            avatars=inventory(base/'OSC')
            self.assertEqual(avatars[aid]['saved_names'],{'头发','EyeTrackingEnable'})
            rows=candidates(avatars,[aid])
            self.assertTrue(any(p['name']=='头发' for p in rows))
            self.assertTrue(next(p for p in rows if p['name']=='EyeTrackingEnable')['enabled'])

    def test_actual_escaped_addresses_used_and_type_access_checked(self):
        definition = {"name": "头发", "input": {"address": "/avatar/parameters/\\u5934\\u53d1", "type": "Int"},
                      "output": {"address": "/avatar/parameters/\\u5934\\u53d1", "type": "Int"}}
        address = definition["input"]["address"]
        avatar = {"id": "A", "defs": {"头发": definition}, "saved_names": {"头发"}}
        group = {"parameters": [{"name": "头发", "type": "Int"}]}
        live, defs = live_values(avatar, {address: {"TYPE": "i", "ACCESS": 3, "VALUE": [2]}}, group)
        self.assertEqual(live["头发"]["value"], 2)
        self.assertTrue(live["头发"]["writable"])
        self.assertEqual(defs["头发"]["input"]["address"], address)
        live, _ = live_values(avatar, {address: {"TYPE": "f", "ACCESS": 3, "VALUE": [2]}}, group)
        self.assertEqual(live, {})

    def test_atomic_unicode_state_roundtrip(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
            path = Path(tmp) / "state.json"
            value = {"g": {"头发": {"type": "Int", "value": 2}}}
            write_json(path, value)
            self.assertEqual(read_json(path, {}), value)

    def test_common_saved_parameters_and_clothing_exclusions(self):
        from sync_core import default_exclusion
        def d(name, kind='Bool'):
            return {'name':name,'input':{'type':kind},'output':{'type':kind}}
        names=['头纱','浴袍','F_Set','F_Parts','ZincatParts_ABC_M00','EyeTrackingEnable','OnlyA','OnlyB']
        a={'A':{'defs':{n:d(n) for n in names[:-1]},'saved_names':set(names[:-1])},
           'B':{'defs':{n:d(n) for n in names if n!='OnlyA'},'saved_names':set(names)-{'OnlyA'}}}
        rows={p['name']:p for p in candidates(a,['A','B'])}
        self.assertNotIn('OnlyA',rows)
        self.assertNotIn('OnlyB',rows)
        self.assertTrue(rows['头纱']['enabled'])
        self.assertTrue(rows['EyeTrackingEnable']['enabled'])
        for name in ['浴袍','F_Set','F_Parts','ZincatParts_ABC_M00']:
            self.assertFalse(rows[name]['enabled'],name)

    def test_static_eye_setting_restores_once_but_dynamic_eye_is_excluded(self):
        now=[0]
        config={'groups':[{'id':'g','avatars':['A','B'],'parameters':[
            {'name':'EyeTrackingEnable','type':'Bool','enabled':True},
            {'name':'FT/v2/EyeLeftX','type':'Float','enabled':True}]}]}
        sent=[]
        engine=Engine(config,{'g':{'EyeTrackingEnable':{'type':'Bool','value':True}}},lambda *x:sent.append(x),lambda _:None,lambda _:None,lambda:now[0])
        live={'EyeTrackingEnable':{'type':'Bool','value':False,'writable':True},'FT/v2/EyeLeftX':{'type':'Float','value':.9,'writable':True}}
        engine.snapshot('A',live)
        now[0]=3.1
        engine.snapshot('A',live)
        self.assertEqual(sent,[('EyeTrackingEnable','Bool',True)])
        now[0]=4.5
        live['EyeTrackingEnable']['value']=True
        engine.snapshot('A',live)
        for i in range(10):
            now[0]+=1
            engine.snapshot('A',live)
        self.assertEqual(len(sent),1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
