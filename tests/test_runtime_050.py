from pathlib import Path
import json
import queue
import struct
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
import avatar_sync as b
from parameter_snapshots import make_snapshot,store_snapshot,list_snapshots,save_startup_backup
from sync_core import Engine
from desktop_ui import App


def fixture():
    address='/avatar/parameters/Accessory'
    avatars={aid:{'id':aid,'name':aid,'mtime':1,'saved_names':{'Accessory'},'defs':{'Accessory':{'name':'Accessory','input':{'address':address,'type':'Bool'},'output':{'address':address,'type':'Bool'}}}} for aid in ['avtr_A','avtr_B']}
    config={'version':1,'groups':[{'id':'g','name':'示例组','avatars':list(avatars),'parameters':[{'name':'Accessory','type':'Bool','enabled':True}]}]}
    nodes={address:{'TYPE':'F','ACCESS':3,'VALUE':[False]}}
    return avatars,config,nodes,address


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.data=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def test_packet_decoder_filters_unselected_and_handles_bundles(self):
        a='/avatar/parameters/Accessory'
        packet=b.osc_packet(a,'Bool',False)
        self.assertEqual(b.osc_updates(packet,{a}),{a:('Bool',False)})
        self.assertEqual(b.osc_updates(packet,set()),{})
        bundle=b'#bundle\0'+b'\0'*8+struct.pack('>I',len(packet))+packet
        self.assertEqual(b.osc_updates(bundle,{a}),{a:('Bool',False)})
        self.assertEqual(b.osc_updates(b'bad',{a}),{})

    def test_automatic_retention_keeps_manual_snapshots(self):
        avatars,_,nodes,_=fixture()
        manual=make_snapshot('avtr_A',nodes,avatars)
        store_snapshot(self.data,manual)
        for _ in range(4):save_startup_backup(self.data,'avtr_A',nodes,avatars,keep=2)
        entries=list_snapshots(self.data)
        self.assertEqual(len(entries),3)
        self.assertIn(manual['id'],{s['id'] for s in entries})
        self.assertEqual(sum(s.get('kind')=='automatic_start' for s in entries),2)

    def test_unreadable_backup_rejects_without_creating_snapshot(self):
        with self.assertRaises(ValueError):save_startup_backup(self.data,'avtr_A',{},fixture()[0])
        self.assertEqual(list_snapshots(self.data),[])

    def run_worker(self,backup_failure=False,switch=False,save_failure=False,calibrate=False):
        avatars,config,nodes,address=fixture()
        b.write_json(self.data/'state.json',{'g':{'Accessory':{'type':'Bool','value':True}}})
        tick=[0.0]
        trace=[]
        class Stop:
            def is_set(self):return tick[0]>(26 if calibrate else 18)
            def wait(self,seconds):tick[0]+=seconds;return self.is_set()
        class Transport:
            received_packets=0
            sent_packets=0
            reads=0
            def __init__(self,*_):self.changed=False;self.switched=False;self.send_times=[];self.control_stage=None
            def identity(self):return 'avtr_B' if self.switched else 'avtr_A'
            def changes(self):
                if switch and tick[0]>10 and not self.switched:
                    self.switched=True
                    nodes[address]['VALUE']=[False]
                    nodes[address]['TYPE']='F'
                    return ['avtr_B']
                return []
            def snapshot(self):
                self.reads+=1
                if calibrate:
                    tracking=0 if 10<tick[0]<13 else 6
                    nodes['/avatar/parameters/TrackingType']={'TYPE':'i','ACCESS':1,'VALUE':[tracking]}
                    nodes['/avatar/parameters/VRMode']={'TYPE':'i','ACCESS':1,'VALUE':[1]}
                    if tracking==0:
                        nodes[address]['VALUE']=[False]
                        nodes[address]['TYPE']='F'
                return ('avtr_B' if self.switched else 'avtr_A'),nodes
            def take_updates(self):
                if calibrate:
                    stage=0 if 10<tick[0]<13 else 6
                    if stage!=self.control_stage:
                        self.control_stage=stage
                        nodes['/avatar/parameters/TrackingType']={'TYPE':'i','ACCESS':1,'VALUE':[stage]}
                        values={'/avatar/parameters/TrackingType':('Int',stage),'/avatar/parameters/VRMode':('Int',1)}
                        if stage==0:
                            nodes[address].update(TYPE='F',VALUE=[False]);values[address]=('Bool',False)
                        return values
                if tick[0]>7 and not self.changed:
                    self.changed=True
                    nodes[address]['VALUE']=[True]
                    nodes[address]['TYPE']='T'
                    return {address:('Bool',True)}
                return {}
            def send(self,name,kind,value):
                trace.append('send')
                self.send_times.append((tick[0],value))
                self.sent_packets+=1
                nodes[address]['VALUE']=[value]
                nodes[address]['TYPE']='T' if value else 'F'
            def close(self):trace.append('closed')
        transport=Transport()
        def backup(*_):
            trace.append('backup')
            self.assertIs(nodes[address]['VALUE'][0],False)
            if backup_failure:raise OSError('fixture backup failure')
            return {'id':'fixture'}
        events=queue.Queue()
        worker=b.Worker(config,events,self.data)
        worker.stop_event=Stop()
        worker.wait=lambda seconds:worker.stop_event.wait(min(seconds,.1))
        write=b.write_json
        def commit(path,value):
            if save_failure:raise OSError('fixture state write failure')
            if path.name=='state.json':trace.append(('saved',value['g']['Accessory']['value']))
            write(path,value)
        with patch('avatar_sync.write_json',side_effect=commit),patch('avatar_sync.Transport',return_value=transport),patch('avatar_sync.inventory',return_value=avatars),patch('avatar_sync.time.monotonic',side_effect=lambda:tick[0]),patch('parameter_snapshots.save_startup_backup',side_effect=backup):
            worker.run()
        return trace,transport,list(events.queue)

    def test_current_values_replace_old_shared_record_before_sync(self):
        trace,transport,events=self.run_worker()
        self.assertEqual(trace[:2],['backup',('saved',False)])
        self.assertNotIn('send',trace)
        self.assertEqual(sum(kind=='startup_saved' for kind,_ in events),1)
        self.assertLess(transport.reads,23)
        state=b.read_json(self.data/'state.json',{})
        self.assertIs(state['g']['Accessory']['value'],True)
        results=[value for kind,value in events if kind=='result']
        self.assertEqual(results[-1],{'confirmed':1,'skipped':0,'failed':0,'total':1})

    def test_later_avatar_switch_restores_shared_values_instead_of_recapturing(self):
        trace,_,events=self.run_worker(switch=True)
        self.assertEqual(trace.count('backup'),1)
        self.assertEqual(trace.count('send'),1)
        self.assertEqual(sum(kind=='startup_saved' for kind,_ in events),1)

    def test_failed_startup_commit_stops_without_writes_to_game(self):
        trace,_,events=self.run_worker(save_failure=True)
        self.assertNotIn('send',trace)
        self.assertFalse(any(kind=='startup_saved' for kind,_ in events))
        self.assertTrue(any(kind=='error' for kind,_ in events))
        self.assertIs(b.read_json(self.data/'state.json',{})['g']['Accessory']['value'],True)

    def test_calibration_preserves_shared_values_and_restores_after_exit(self):
        trace,transport,events=self.run_worker(calibrate=True)
        self.assertTrue(any('暂停记录' in str(v) for k,v in events if k=='status'))
        self.assertEqual(len(transport.send_times),1)
        self.assertGreater(transport.send_times[0][0],16)
        self.assertIs(transport.send_times[0][1],True)
        self.assertIs(b.read_json(self.data/'state.json',{})['g']['Accessory']['value'],True)

    def test_backup_failure_prevents_restore_and_preserves_shared_record(self):
        trace,_,events=self.run_worker(backup_failure=True)
        self.assertNotIn('send',trace)
        self.assertIn('closed',trace)
        self.assertTrue(any(kind=='error' for kind,_ in events))
        self.assertIs(b.read_json(self.data/'state.json',{})['g']['Accessory']['value'],True)

    def test_result_counts_do_not_double_count_missing_parameters(self):
        tick=[0]
        config=fixture()[1]
        config['groups'][0]['parameters'].append({'name':'Other','type':'Bool','enabled':True})
        reports=[]
        engine=Engine(config,{},lambda *_:None,lambda _:None,lambda _:None,clock=lambda:tick[0],report=reports.append)
        live={'Accessory':{'type':'Bool','value':False,'writable':True}}
        engine.snapshot('avtr_A',live)
        tick[0]=3.1;engine.snapshot('avtr_A',live)
        tick[0]=4.5;engine.snapshot('avtr_A',live)
        self.assertEqual(reports[-1],{'confirmed':1,'skipped':1,'failed':0,'total':2})

    def test_unchanged_table_and_log_updates_do_not_rebuild_whole_widgets(self):
        avatars,config,_,_=fixture()
        b.write_json(self.data/'config.json',config)
        root=tk.Tk();root.withdraw()
        app=App(root,self.data,avatars)
        with patch.object(app.table,'delete',wraps=app.table.delete) as delete:
            app.paint_rows();app.paint_rows()
            delete.assert_not_called()
        with patch.object(app.logs,'delete',wraps=app.logs.delete) as delete:
            app.append_logs(['one','two'])
            delete.assert_not_called()
        app.show_diagnostics()
        self.assertEqual(app.heading.get(),'运行诊断')
        root.update_idletasks();app.close()


if __name__=='__main__':unittest.main(verbosity=2)
