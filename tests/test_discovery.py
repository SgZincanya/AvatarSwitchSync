from pathlib import Path
import json
import queue
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from avatar_sync import inventory,write_json
from model_discovery import InventoryMonitor,cache_signature
from desktop_ui import App,GroupEditor


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.base=Path(self.temp.name)
        self.cache=self.base/'OSC'
    def tearDown(self):self.temp.cleanup()

    def add_model(self,aid='avtr_fixture_new'):
        path=self.cache/'usr_fixture/Avatars'/f'{aid}.json'
        item={'id':aid,'name':'新上传模型','parameters':[{'name':'Accessory','input':{'type':'Bool'},'output':{'type':'Bool'}}]}
        write_json(path,item)
        return aid

    def test_new_model_without_saved_record_is_still_discovered(self):
        aid=self.add_model()
        result=inventory(self.cache)
        self.assertIn(aid,result)
        self.assertEqual(result[aid]['saved_status'],'missing')
        self.assertEqual(result[aid]['saved_names'],set())

    def test_corrupt_saved_record_does_not_hide_valid_model(self):
        aid=self.add_model()
        path=self.base/'LocalAvatarData/usr_fixture'/aid
        path.parent.mkdir(parents=True)
        path.write_text('{bad json',encoding='utf-8')
        result=inventory(self.cache)
        self.assertIn(aid,result)
        self.assertEqual(result[aid]['saved_status'],'unavailable')

    def test_watcher_detects_new_files_and_saved_record_changes(self):
        events=queue.Queue()
        monitor=InventoryMonitor(events,self.cache,interval=.1)
        monitor.start()
        try:
            self.assertEqual(events.get(timeout=2)[1]['avatars'],{})
            aid=self.add_model()
            self.assertIn(aid,events.get(timeout=2)[1]['avatars'])
            before=cache_signature(self.cache)
            write_json(self.base/'LocalAvatarData/usr_fixture'/aid,{'animationParameters':[{'name':'Accessory','value':True}]})
            self.assertNotEqual(before,cache_signature(self.cache))
            changed=events.get(timeout=2)[1]['avatars']
            self.assertIn('Accessory',changed[aid]['saved_names'])
        finally:
            monitor.stop_event.set()
            monitor.join(timeout=2)

    def test_open_editor_receives_new_model_without_resetting_selection(self):
        aid=self.add_model()
        avatars=inventory(self.cache)
        root=tk.Tk()
        root.withdraw()
        app=App(root,self.base/'app',avatars=avatars)
        dialog=GroupEditor(app)
        app.group_editor=dialog
        dialog.selected.add(aid)
        new=self.add_model('avtr_fixture_second')
        app.accept_inventory(inventory(self.cache))
        self.assertIn(new,dialog.ids)
        self.assertIn(aid,dialog.selected)
        self.assertTrue(dialog.tree.exists(new))
        dialog.destroy()
        app.group_editor=None
        root.update_idletasks()
        app.close()

    def test_library_shows_recent_model_and_waiting_status(self):
        aid=self.add_model()
        root=tk.Tk()
        root.withdraw()
        app=App(root,self.base/'app',avatars={})
        app.show_models()
        app.accept_inventory(inventory(self.cache))
        self.assertTrue(app.model_table.exists(aid))
        self.assertEqual(app.nav_mode,'models')
        self.assertEqual(app.heading.get(),'本机模型')
        self.assertIn('等待保存记录',app.model_table.item(aid,'values'))
        root.update_idletasks()
        app.close()


if __name__=='__main__':unittest.main(verbosity=2)
