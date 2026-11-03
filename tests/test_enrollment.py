import copy
from pathlib import Path
import queue
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
import avatar_sync as b
from enrollment import enroll
from desktop_ui import App
from test_runtime_050 import fixture


class EnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.data=Path(self.temp.name)
        self.avatars,self.config,self.nodes,self.address=fixture()
        self.avatars['avtr_C']=copy.deepcopy(self.avatars['avtr_A'])
        self.avatars['avtr_C'].update(id='avtr_C',name='新增模型')
    def tearDown(self):self.temp.cleanup()

    def test_add_preserves_choices_and_original_config(self):
        updated,_=enroll(self.config,'g','avtr_C',self.avatars)
        self.assertEqual(updated['groups'][0]['avatars'],['avtr_A','avtr_B','avtr_C'])
        self.assertEqual(updated['groups'][0]['parameters'],self.config['groups'][0]['parameters'])
        self.assertEqual(len(self.config['groups'][0]['avatars']),2)

    def test_existing_member_and_other_group_not_duplicated_or_moved(self):
        self.assertIsNone(enroll(self.config,'g','avtr_A',self.avatars)[0])
        self.config['groups'].append({'id':'other','name':'其他组','avatars':['avtr_C','avtr_D'],'parameters':[]})
        updated,message=enroll(self.config,'g','avtr_C',self.avatars)
        self.assertIsNone(updated)
        self.assertIn('其他组',message)

    def test_missing_cache_or_saved_record_waits(self):
        self.assertIsNone(enroll(self.config,'g','avtr_D',self.avatars)[0])
        self.avatars['avtr_C']['saved_names']=set()
        self.assertIsNone(enroll(self.config,'g','avtr_C',self.avatars)[0])

    def run_worker(self,late=False,fail=False,disable=False,live_enable=False):
        b.write_json(self.data/'config.json',self.config)
        b.write_json(self.data/'state.json',{'g':{'Accessory':{'type':'Bool','value':True}}})
        tick=[0.]
        trace=[]
        worker=b.Worker(copy.deepcopy(self.config),queue.Queue(),self.data,capture_current=False,add_group=None if live_enable else 'g')
        class Stop:
            def is_set(self):return tick[0]>20
            def wait(self,seconds):tick[0]+=seconds;return self.is_set()
        class Transport:
            received_packets=sent_packets=0
            def __init__(inner):inner.changed=False;inner.mode_changed=False
            def changes(inner):
                if disable and tick[0]>10 and not inner.changed:
                    inner.changed=True
                    worker.set_add_group(None)
                if live_enable and tick[0]>2 and not inner.mode_changed:
                    inner.mode_changed=True
                    worker.set_add_group('g')
                return []
            def snapshot(inner):return 'avtr_D' if inner.changed else 'avtr_C',self.nodes
            def take_updates(inner):return {}
            def send(inner,name,kind,value):
                trace.append(('send',name,value))
                self.assertIn('avtr_C',b.read_json(self.data/'config.json',{})['groups'][0]['avatars'])
                self.nodes[self.address].update(TYPE='T',VALUE=[value])
            def close(inner):pass
        transport=Transport()
        worker.stop_event=Stop()
        def inventory():
            result=copy.deepcopy(self.avatars)
            if late and tick[0]<5:result.pop('avtr_C')
            result['avtr_D']=copy.deepcopy(self.avatars['avtr_C']);result['avtr_D']['id']='avtr_D'
            return result
        real_write=b.write_json
        def write(path,value):
            if fail and path.name=='config.json':raise OSError('membership write failure')
            real_write(path,value)
        with patch('avatar_sync.Transport',return_value=transport),patch('avatar_sync.inventory',side_effect=inventory),patch('avatar_sync.time.monotonic',side_effect=lambda:tick[0]),patch('avatar_sync.write_json',side_effect=write),patch('parameter_snapshots.save_startup_backup',return_value={'id':'backup'}):
            worker.run()
        return trace,list(worker.events.queue)

    def test_new_current_model_joins_and_receives_old_values_without_switchback(self):
        trace,events=self.run_worker()
        self.assertEqual(trace,[('send','Accessory',True)])
        self.assertEqual(sum(k=='group_enrolled' for k,v in events),1)
        self.assertFalse(any(k=='startup_saved' for k,v in events))
        self.assertIs(b.read_json(self.data/'state.json',{})['g']['Accessory']['value'],True)

    def test_cache_appearing_after_load_is_retried(self):
        trace,_=self.run_worker(late=True)
        self.assertEqual(len(trace),1)

    def test_mode_can_be_enabled_on_running_worker(self):
        trace,events=self.run_worker(live_enable=True)
        self.assertEqual(len(trace),1)
        self.assertTrue(any(k=='group_enrolled' for k,v in events))

    def test_mode_exit_does_not_enroll_next_model(self):
        self.run_worker(disable=True)
        self.assertNotIn('avtr_D',b.read_json(self.data/'config.json',{})['groups'][0]['avatars'])

    def test_failed_membership_save_sends_nothing_and_keeps_disk_config(self):
        trace,events=self.run_worker(fail=True)
        self.assertEqual(trace,[])
        self.assertTrue(any(k=='error' for k,v in events))
        self.assertEqual(b.read_json(self.data/'config.json',{}),self.config)

    def test_ui_pins_target_and_can_exit_without_stopping_worker(self):
        b.write_json(self.data/'config.json',self.config)
        b.write_json(self.data/'state.json',{'g':{'Accessory':{'type':'Bool','value':True}}})
        root=tk.Tk();root.withdraw()
        app=App(root,self.data,self.avatars)
        class Worker:
            def is_alive(self):return True
            def set_add_group(self,gid):self.gid=gid
        worker=Worker();app.worker=worker
        app.toggle_add_mode()
        self.assertEqual(worker.gid,'g')
        self.assertEqual(app.add_group,'g')
        app.show_models()
        app.toggle_add_mode()
        self.assertIsNone(worker.gid)
        self.assertIsNone(app.add_group)
        app.worker=None;app.close()


if __name__=='__main__':unittest.main()
