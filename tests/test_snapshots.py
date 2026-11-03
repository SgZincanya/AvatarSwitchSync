from pathlib import Path
import queue
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from parameter_snapshots import make_snapshot,store_snapshot,list_snapshots,CaptureWorker
from desktop_ui import App


def sample():
    aid='avtr_fixture'
    address=r'/avatar/parameters/\u5934\u53d1'
    avatars={aid:{'name':'测试模型','saved_names':{'头发'},'defs':{
        '头发':{'name':'头发','output':{'address':address},'input':{'address':address}}}}}
    nodes={address:{'TYPE':'i','ACCESS':3,'VALUE':[2]},
           '/avatar/parameters/FT/v2/EyeLeftX':{'TYPE':'f','ACCESS':3,'VALUE':[.4]},
           '/avatar/parameters/Toggle':{'TYPE':'F','ACCESS':3,'VALUE':[False]},
           '/avatar/parameters/Unreadable':{'TYPE':'f','ACCESS':2},
           '/avatar/change':{'TYPE':'s','ACCESS':1,'VALUE':[aid]}}
    return aid,nodes,avatars


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.data=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def test_capture_includes_hidden_and_realtime_values_without_false_defaults(self):
        aid,nodes,avatars=sample()
        capture=make_snapshot(aid,nodes,avatars)
        rows={p['name']:p for p in capture['parameters']}
        self.assertEqual(len(rows),4)
        self.assertEqual(rows['头发']['value'],2)
        self.assertTrue(rows['头发']['saved_locally'])
        self.assertEqual(rows['FT/v2/EyeLeftX']['value'],.4)
        self.assertIs(rows['Toggle']['value'],False)
        self.assertFalse(rows['Unreadable']['has_value'])
        self.assertIsNone(rows['Unreadable']['value'])
        self.assertIn('captured_at',capture)

    def test_snapshots_persist_separately_without_overwrite(self):
        one=make_snapshot(*sample())
        two=make_snapshot(*sample())
        store_snapshot(self.data,one)
        store_snapshot(self.data,two)
        self.assertEqual(len(list_snapshots(self.data)),2)
        self.assertFalse((self.data/'state.json').exists())
        self.assertFalse((self.data/'config.json').exists())

    def test_invalid_path_id_rejected(self):
        capture=make_snapshot(*sample())
        capture['id']='../state'
        with self.assertRaises(ValueError):store_snapshot(self.data,capture)

    def test_capture_worker_never_sends_parameters(self):
        aid,nodes,avatars=sample()
        events=queue.Queue()
        with patch('parameter_snapshots.backend.Transport') as factory,patch('parameter_snapshots.backend.inventory',return_value=avatars):
            transport=factory.return_value
            transport.snapshot.return_value=(aid,nodes)
            transport.changes.return_value=[]
            CaptureWorker(self.data,events).run()
            transport.send.assert_not_called()
            transport.close.assert_called_once()
        self.assertEqual(len(list_snapshots(self.data)),1)
        self.assertEqual(events.get()[0],'snapshot_saved')

    def test_library_visible_on_fresh_install_and_after_restart(self):
        capture=make_snapshot(*sample())
        store_snapshot(self.data,capture)
        root=tk.Tk()
        root.withdraw()
        try:
            app=App(root,self.data,avatars={})
            app.show_snapshots()
            root.update_idletasks()
            self.assertEqual(len(app.snapshots),1)
            self.assertEqual(len(app.snapshot_table.get_children()),4)
            self.assertIsNone(app.worker)
            app.snapshot_search.set('头发')
            self.assertEqual(len(app.snapshot_table.get_children()),1)
            self.assertEqual(app.heading.get(),'参数快照')
            app.root.after_cancel(app.pump_id)
        finally:
            root.update_idletasks()
            root.destroy()


if __name__=='__main__':unittest.main(verbosity=2)
