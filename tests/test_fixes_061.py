from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
import avatar_sync as b
from config_store import validate_config
from desktop_ui import App,GroupEditor
from test_desktop import fixture,fake_inventory
from enrollment import enroll


class FixTests(unittest.TestCase):
    def test_local_http_never_initializes_ssl_or_uses_proxies(self):
        with patch('urllib.request.HTTPSHandler',side_effect=FileNotFoundError('fixture frozen SSL unavailable')) as https:
            opener=b.local_http_opener()
        https.assert_not_called()
        self.assertFalse(any(type(h).__name__ in ('HTTPSHandler','FTPHandler','FileHandler','HTTPRedirectHandler') for h in opener.handlers))

    def test_single_model_config_roundtrip_and_enrollment(self):
        config=fixture();config['groups'][0]['avatars']=['avtr_fixture_0']
        self.assertEqual(validate_config(config),config)
        updated,_=enroll(config,'test-group','avtr_fixture_1',fake_inventory())
        self.assertEqual(len(updated['groups'][0]['avatars']),2)
        config['groups'][0]['avatars']=[]
        with self.assertRaises(ValueError):validate_config(config)

    def test_single_model_can_create_reference_and_initialize_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=tk.Tk();root.withdraw()
            app=App(root,Path(tmp),fake_inventory())
            dialog=GroupEditor(app)
            self.assertEqual(str(dialog.confirm.cget('state')),'disabled')
            dialog.flip('avtr_fixture_0')
            self.assertEqual(str(dialog.confirm.cget('state')),'normal')
            dialog.accept()
            self.assertEqual(dialog.result['avatars'],['avtr_fixture_0'])
            self.assertTrue(b.candidates(app.avatars,dialog.result['avatars']))
            app.close()

    def test_collapsed_member_rows_expand_and_remain_inside_minimum_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=fixture();avatars=fake_inventory()
            for i in range(3,20):
                aid=f'avtr_fixture_{i}'
                avatars[aid]={**avatars['avtr_fixture_0'],'id':aid,'name':f'较长的模型名称 {i}'}
                config['groups'][0]['avatars'].append(aid)
            b.write_json(Path(tmp)/'config.json',config)
            root=tk.Tk();root.geometry('1000x690')
            app=App(root,Path(tmp),avatars)
            root.geometry('1000x690');root.update()
            self.assertFalse(app.members_expanded)
            self.assertFalse(app.member_panel.winfo_ismapped())
            app.toggle_members();root.update()
            self.assertTrue(app.member_panel.winfo_ismapped())
            self.assertEqual(len(app.member_table.get_children()),19)
            for i,aid in enumerate(config['groups'][0]['avatars'],1):
                self.assertEqual(app.member_table.item(aid,'values'),(str(i),avatars[aid]['name']))
            self.assertGreater(app.table.winfo_height(),100)
            app.toggle_members();root.update()
            self.assertFalse(app.member_panel.winfo_ismapped())
            app.close()


if __name__=='__main__':unittest.main()
