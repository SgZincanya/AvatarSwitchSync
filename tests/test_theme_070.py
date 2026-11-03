from pathlib import Path
import sys
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from desktop_ui import App
from ui_theme import LIGHT,DARK
from avatar_sync import write_json
from test_desktop import fixture,fake_inventory


def luminance(color):
    rgb=[int(color[i:i+2],16)/255 for i in (1,3,5)]
    values=[x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4 for x in rgb]
    return sum(x*w for x,w in zip(values,[.2126,.7152,.0722]))


class ThemeTests(unittest.TestCase):
    def test_text_and_primary_action_contrast_in_both_appearances(self):
        for c in (LIGHT,DARK):
            for fg,bg in [(c['text'],c['panel']),(c['muted'],c['panel']),(c['muted'],c['side']),('#FFFFFF',c['button'])]:
                a,b=sorted([luminance(fg),luminance(bg)])
                self.assertGreaterEqual((b+.05)/(a+.05),4.5,(fg,bg))

    def test_status_text_fits_and_label_backgrounds_match_in_both_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp);write_json(data/'config.json',fixture())
            for c in (LIGHT,DARK):
                root=tk.Tk()
                with patch('desktop_ui.palette',return_value=dict(c)):app=App(root,data,fake_inventory())
                root.geometry('1000x690')
                app.result_text.set('启动前备份已保存。正在等待模型稳定后恢复已有共享记录，原来的保存值会继续保留。')
                root.update()
                card=app.result_label.master.master.master
                self.assertLessEqual(app.result_label.winfo_rooty()+app.result_label.winfo_height(),card.winfo_rooty()+card.winfo_height()-6)
                style=ttk.Style(root)
                self.assertEqual(style.lookup('PanelMuted.TLabel','background'),c['panel'])
                self.assertEqual(style.lookup('SideMuted.TLabel','background'),c['side'])
                self.assertTrue(app.menu_strip.winfo_ismapped())
                app.close()


if __name__=='__main__':unittest.main()
