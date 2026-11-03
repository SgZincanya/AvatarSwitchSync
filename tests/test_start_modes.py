from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
import avatar_sync as b
from desktop_ui import App
from sync_core import Engine
from test_runtime_050 import fixture


class StartModeTests(unittest.TestCase):
    def test_auto_restore_sends_saved_value_and_never_seeds_missing(self):
        _,config,_,_=fixture()
        config['groups'][0]['parameters'].append({'name':'Unrecorded','type':'Int','enabled':True})
        state={'g':{'Accessory':{'type':'Bool','value':True}}}
        sent=[];tick=[0.]
        engine=Engine(config,state,lambda *args:sent.append(args),lambda _:None,lambda _:None,clock=lambda:tick[0],seed_missing=False)
        live={'Accessory':{'type':'Bool','value':False,'writable':True},'Unrecorded':{'type':'Int','value':0,'writable':True}}
        engine.snapshot('avtr_A',live)
        tick[0]=3.1;engine.snapshot('avtr_A',live)
        self.assertEqual(sent,[('Accessory','Bool',True)])
        self.assertEqual(state,{'g':{'Accessory':{'type':'Bool','value':True}}})
        live['Accessory']['value']=True
        tick[0]=5.;engine.snapshot('avtr_A',live)
        tick[0]=7.;engine.snapshot('avtr_A',live)
        self.assertNotIn('Unrecorded',state['g'])

    def run_ui(self,auto,has_record):
        avatars,config,_,_=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp);b.write_json(data/'config.json',config)
            if has_record:b.write_json(data/'state.json',{'g':{'Accessory':{'type':'Bool','value':True}}})
            root=tk.Tk();root.withdraw();app=App(root,data,avatars)
            with patch('avatar_sync.Worker') as worker:
                app.start(capture_current=not auto)
                kwargs=worker.call_args.kwargs if worker.called else None
                notice=app.notice.get()
            app.worker=None;app.close()
        return kwargs,notice

    def test_manual_button_path_captures_current_even_with_existing_record(self):
        kwargs,_=self.run_ui(auto=False,has_record=True)
        self.assertTrue(kwargs['capture_current'])

    def test_steamvr_path_restores_without_capturing(self):
        kwargs,_=self.run_ui(auto=True,has_record=True)
        self.assertFalse(kwargs['capture_current'])

    def test_auto_without_record_requests_manual_setup_instead_of_seeding(self):
        kwargs,notice=self.run_ui(auto=True,has_record=False)
        self.assertIsNone(kwargs)
        self.assertIn('手动开始共享',notice)


if __name__=='__main__':unittest.main()
