import copy
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from config_store import empty_config,load_config,validate_config,merge_config,display_name
from desktop_ui import App,GroupEditor
from avatar_sync import write_json


def fake_inventory():
    result={}
    for i in range(3):
        aid=f'avtr_fixture_{i}'
        names={'Accessory','FT/v2/EyeLeftX','EyeTrackingEnable'}
        result[aid]={'id':aid,'name':f'示例模型 {i+1}','mtime':i,'saved_names':names,
                     'defs':{n:{'name':n,'input':{'type':'Float' if n.startswith('FT/') else 'Bool'},'output':{'type':'Float' if n.startswith('FT/') else 'Bool'}} for n in names}}
    return result


def fixture():
    return {'version':1,'groups':[{'id':'test-group','name':'测试分组','avatars':['avtr_fixture_0','avtr_fixture_1'],
                                 'parameters':[{'name':'Accessory','type':'Bool','enabled':False},
                                               {'name':'FT/v2/EyeLeftX','type':'Float','enabled':False},
                                               {'name':'EyeTrackingEnable','type':'Bool','enabled':True}]}]}


class ConfigTests(unittest.TestCase):
    def test_fresh_has_no_preinstalled_avatars(self):
        self.assertEqual(empty_config(),{'version':1,'groups':[]})

    def test_existing_configuration_roundtrips(self):
        self.assertEqual(validate_config(fixture()),fixture())

    def test_duplicate_membership_and_invalid_parameter_rejected(self):
        config=fixture()
        config['groups'].append({**copy.deepcopy(config['groups'][0]),'id':'other'})
        with self.assertRaises(ValueError):validate_config(config)
        config=fixture()
        config['groups'][0]['parameters'][0]['enabled']='true'
        with self.assertRaises(ValueError):validate_config(config)

    def test_import_new_identity_and_reject_conflicts_without_mutating_source(self):
        config=fixture()
        result=merge_config(empty_config(),config)
        self.assertNotEqual(result['groups'][0]['id'],'test-group')
        self.assertEqual(config['groups'][0]['id'],'test-group')
        with self.assertRaises(ValueError):merge_config(config,config)

    def test_display_name_does_not_invent_function(self):
        self.assertEqual(display_name('__MA/AutoParam/头纱$abcdef123456'),'头纱')
        self.assertEqual(display_name('ZincatParts_123_M00'),'ZincatParts_123_M00')


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.data=Path(self.temp.name)
        self.root=tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        try:
            self.root.update_idletasks()
            for timer in self.root.tk.call('after','info'):
                self.root.after_cancel(timer)
            self.root.destroy()
        except tk.TclError:pass
        self.temp.cleanup()

    def test_first_run_empty_and_never_starts_network(self):
        with patch('avatar_sync.Worker') as worker:
            app=App(self.root,self.data,fake_inventory())
            self.root.update_idletasks()
            self.assertIsNone(app.current_group)
            self.assertEqual(app.config['groups'],[])
            self.assertEqual(str(app.start_button.cget('state')),'disabled')
            self.assertIsNone(app.worker)
            worker.assert_not_called()

    def test_migrated_group_filters_keyboard_and_persistence(self):
        write_json(self.data/'config.json',fixture())
        app=App(self.root,self.data,fake_inventory())
        self.root.update_idletasks()
        self.assertEqual(app.current_group,'test-group')
        self.assertEqual(len(app.table.get_children()),3)
        app.search.set('EyeTrackingEnable')
        self.assertEqual(len(app.table.get_children()),1)
        app.filter.set('受保护')
        app.paint_rows()
        self.assertEqual(len(app.table.get_children()),0)
        app.search.set('')
        app.filter.set('全部参数')
        app.paint_rows()
        app.table.selection_set('0')
        app.toggle_rows(['0'])
        self.assertTrue(load_config(self.data/'config.json')['groups'][0]['parameters'][0]['enabled'])
        app.toggle_rows(['1'])
        self.assertFalse(app.group()['parameters'][1]['enabled'])

    def test_edit_locked_while_running(self):
        write_json(self.data/'config.json',fixture())
        app=App(self.root,self.data,fake_inventory())
        class Running:
            def is_alive(self):return True
        app.worker=Running()
        before=copy.deepcopy(app.config)
        app.toggle_rows(['0'])
        self.assertEqual(before,app.config)
        app.worker=None

    def test_layout_at_default_and_minimum_sizes(self):
        write_json(self.data/'config.json',fixture())
        app=App(self.root,self.data,fake_inventory())
        self.root.deiconify()
        for size in ['1180x800','1000x690']:
            self.root.geometry(size)
            self.root.update()
            self.assertGreater(app.table.winfo_height(),120)
            self.assertLessEqual(app.start_button.winfo_rootx()+app.start_button.winfo_width(),self.root.winfo_rootx()+self.root.winfo_width())
            self.assertGreater(app.search_entry.winfo_width(),100)
            self.assertGreater(app.table.winfo_width(),500)

    def test_group_editor_keeps_actions_visible_and_creates_user_selected_members(self):
        app=App(self.root,self.data,fake_inventory())
        self.root.deiconify()
        self.root.update()
        dialog=GroupEditor(app)
        for size in ['660x570','550x460']:
            dialog.geometry(size)
            dialog.update()
            bottom=dialog.confirm.winfo_rooty()+dialog.confirm.winfo_height()
            self.assertLessEqual(bottom,dialog.winfo_rooty()+dialog.winfo_height())
            self.assertGreater(dialog.tree.winfo_height(),30)
        dialog.flip('avtr_fixture_0')
        dialog.flip('avtr_fixture_1')
        dialog.accept()
        self.assertEqual(set(dialog.result['avatars']),{'avtr_fixture_0','avtr_fixture_1'})

    def test_missing_group_parameter_is_hidden_and_removed_from_runtime(self):
        from avatar_sync import common_config
        config=fixture()
        config['groups'][0]['parameters'][0]['enabled']=True
        avatars=fake_inventory()
        del avatars['avtr_fixture_1']['defs']['Accessory']
        avatars['avtr_fixture_1']['saved_names'].remove('Accessory')
        write_json(self.data/'config.json',config)
        app=App(self.root,self.data,avatars)
        self.assertFalse(app.table.exists('0'))
        effective=common_config(config,avatars)
        names={p['name'] for p in effective['groups'][0]['parameters']}
        self.assertNotIn('Accessory',names)
        self.assertIn('EyeTrackingEnable',names)
        self.assertEqual(config['groups'][0]['parameters'][0]['name'],'Accessory')
        self.assertTrue(config['groups'][0]['parameters'][0]['enabled'])

    def test_type_conflicts_and_unmatched_model_disable_parameters(self):
        from avatar_sync import common_config,candidates
        avatars=fake_inventory()
        avatars['avtr_fixture_1']['defs']['Accessory']['input']['type']='Int'
        config=fixture()
        self.assertNotIn('Accessory',{p['name'] for p in common_config(config,avatars)['groups'][0]['parameters']})
        del avatars['avtr_fixture_1']
        self.assertEqual(candidates(avatars,['avtr_fixture_0','avtr_fixture_1']),[])
        self.assertEqual(common_config(config,avatars)['groups'][0]['parameters'],[])


if __name__=='__main__':unittest.main(verbosity=2)
