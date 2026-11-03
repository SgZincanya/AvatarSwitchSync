"""Desktop interface. All user groups are loaded from configuration, never from code."""
import copy
import json
import os
from pathlib import Path
import queue
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import uuid
import webbrowser

import avatar_sync as backend
from config_store import VERSION, display_name, empty_config, load_config, merge_config, validate_config
from sync_core import protected, default_exclusion
from parameter_snapshots import CaptureWorker, list_snapshots
from model_discovery import InventoryMonitor
from updates import CheckWorker,DownloadWorker,RELEASES_URL,start_install


def palette():
    dark = False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
            dark = winreg.QueryValueEx(key, 'AppsUseLightTheme')[0] == 0
    except (ImportError, OSError):
        pass
    from ui_theme import LIGHT,DARK
    return dict(DARK if dark else LIGHT)


class GroupEditor(tk.Toplevel):
    def __init__(self, app, group=None):
        super().__init__(app.root)
        self.app, self.original = app, group
        self.result = None
        self.selected = set(group['avatars'] if group else [])
        self.title('编辑共享组' if group else '新建共享组')
        x = max(0, app.root.winfo_rootx() + (app.root.winfo_width()-660)//2)
        y = max(0, app.root.winfo_rooty() + (app.root.winfo_height()-570)//2)
        self.geometry(f'660x570+{x}+{y}')
        self.minsize(550, 460)
        self.transient(app.root)
        self.configure(bg=app.c['bg'])
        frame = ttk.Frame(self, padding=24)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(6, weight=1)
        ttk.Label(frame, text='哪些模型需要延续同一份设置？', style='Section.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(frame, text='先选一个参考模型，之后可用添加模式扩充。', style='Muted.TLabel').grid(row=1, column=0, sticky='w', pady=(6, 14))
        ttk.Label(frame, text='分组名称').grid(row=2, column=0, sticky='w')
        self.name = tk.StringVar(value=group['name'] if group else f"共享组 {len(app.config['groups']) + 1}")
        entry = ttk.Entry(frame, textvariable=self.name)
        entry.grid(row=3, column=0, sticky='ew', pady=(6, 12))
        self.search = tk.StringVar()
        ttk.Label(frame, text='搜索模型名称或 ID', style='Muted.TLabel').grid(row=4, column=0, sticky='w', pady=(0, 4))
        ttk.Entry(frame, textvariable=self.search).grid(row=5, column=0, sticky='ew', pady=(0, 8))
        self.search.trace_add('write', lambda *_: self.render())
        tree_frame = ttk.Frame(frame)
        tree_frame.grid(row=6, column=0, sticky='nsew')
        self.tree = ttk.Treeview(tree_frame, columns=('model', 'saved'), show='tree headings', selectmode='browse', height=3)
        self.tree.heading('#0', text='加入')
        self.tree.column('#0', width=52, stretch=False)
        self.tree.heading('model', text='本机模型')
        self.tree.column('model', width=330)
        self.tree.heading('saved', text='保存项')
        self.tree.column('saved', width=85, stretch=False, anchor='center')
        scroll = ttk.Scrollbar(tree_frame, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.tree.bind('<ButtonRelease-1>', self.toggle)
        self.tree.bind('<space>', self.toggle_key)
        self.ids = list(sorted(app.avatars, key=lambda a: app.avatars[a]['mtime'], reverse=True))
        self.ids += sorted(self.selected - set(self.ids))
        self.count = tk.StringVar()
        ttk.Label(frame, textvariable=self.count, style='Muted.TLabel').grid(row=7, column=0, sticky='w', pady=10)
        bottom = ttk.Frame(frame)
        bottom.grid(row=8, column=0, sticky='ew')
        ttk.Button(bottom, text='刷新模型', command=app.refresh_models).pack(side='left')
        ttk.Button(bottom, text='取消', command=self.destroy).pack(side='right')
        self.confirm = ttk.Button(bottom, text='保存分组' if group else '创建分组', style='Primary.TButton', command=self.accept)
        self.confirm.pack(side='right', padx=8)
        self.render()
        entry.focus_set()
        self.bind('<Escape>', lambda _: self.destroy())
        self.grab_set()

    def render(self):
        selection = self.tree.selection()
        position = self.tree.yview()
        self.tree.delete(*self.tree.get_children())
        needle = self.search.get().lower()
        occupied = {a for g in self.app.config['groups'] if not self.original or g['id'] != self.original['id'] for a in g['avatars']}
        for aid in self.ids:
            avatar = self.app.avatars.get(aid)
            name = avatar['name'] if avatar else f'本机未找到 · {aid[-12:]}'
            if needle and needle not in (name + aid).lower():
                continue
            note = '已在其他组' if aid in occupied else str(len(avatar['saved_names'])) if avatar and avatar['saved_names'] else '等待保存' if avatar else '未匹配'
            self.tree.insert('', 'end', iid=aid, text='☑' if aid in self.selected else '☐', values=(name, note), tags=('muted',) if aid in occupied else ())
        self.count.set(f'已选择 {len(self.selected)} 个模型 · 空格或点击行可切换选择')
        self.confirm.configure(state='normal' if self.selected else 'disabled')
        for aid in selection:
            if self.tree.exists(aid): self.tree.selection_add(aid)
        if position:self.tree.yview_moveto(position[0])

    def update_inventory(self):
        self.ids = list(sorted(self.app.avatars, key=lambda a:self.app.avatars[a]['mtime'],reverse=True))
        self.ids += sorted(self.selected-set(self.ids))
        self.render()

    def toggle(self, event):
        aid = self.tree.identify_row(event.y)
        if aid:
            self.flip(aid)

    def toggle_key(self, _):
        if self.tree.selection():
            self.flip(self.tree.selection()[0])
        return 'break'

    def flip(self, aid):
        if any(aid in g['avatars'] for g in self.app.config['groups'] if not self.original or g['id'] != self.original['id']):
            return
        self.selected.symmetric_difference_update({aid})
        self.render()

    def accept(self):
        if not self.selected or not self.name.get().strip():
            messagebox.showinfo('补充分组信息', '请填写名称，并选择至少一个模型。', parent=self)
            return
        self.result = {'name': self.name.get().strip(), 'avatars': [a for a in self.ids if a in self.selected]}
        self.destroy()


class Card(tk.Canvas):
    def __init__(self,parent,color,background,padding=12):
        super().__init__(parent,highlightthickness=0,borderwidth=0,bg=background)
        self.color,self.inset=color,6
        self.body=ttk.Frame(self,style='Panel.TFrame',padding=padding)
        self.content_window=self.create_window((6,6),window=self.body,anchor='nw')
        self.bind('<Configure>',self.layout)

    def layout(self,event):
        w,h=event.width,event.height
        r=14
        self.delete('surface')
        self.create_polygon(0,r,0,0,r,0,w-r,0,w,0,w,r,w,h-r,w,h,w-r,h,r,h,0,h,0,h-r,
                            smooth=True,splinesteps=20,fill=self.color,outline='',tags='surface')
        self.tag_lower('surface')
        self.itemconfigure(self.content_window,width=max(1,w-12),height=max(1,h-12))


class App:
    def __init__(self, root, data_dir=None, avatars=None):
        self.root = root
        self.data_dir = Path(data_dir) if data_dir is not None else backend.DATA
        self.config = load_config(self.data_dir / 'config.json')
        self.avatars = backend.inventory() if avatars is None else avatars
        self.monitor = None
        self.group_editor = None
        self.nav_mode = 'group'
        self.c = palette()
        self.events = queue.Queue()
        self.worker = None
        self.add_group = None
        self.capture_worker = None
        self.snapshots = []
        self.closing = False
        self.exit_requested = False
        self.update_check = None
        self.update_download = None
        self.update_info = None
        self.update_path = None
        self.update_dialog = None
        self.update_manual = False
        self.update_downloading = False
        self.update_message = '可以检查 GitHub 上的新版本。'
        self.auto_update_id = None
        self.current_group = None
        self.sort_reverse = False
        self.log_lines = []
        self.state_cache = backend.read_json(self.data_dir / 'state.json', {})
        self.snapshot_stamp = 0
        self.runtime_metrics = {}
        self.last_result = None
        self.runtime_error = None
        self._row_values = {}
        self._table_group = None
        self.configure_style()
        root.title(f'Avatar Switch Sync · 模型设置共享 {VERSION}')
        root.geometry('1220x820')
        root.minsize(1000, 690)
        root.configure(bg=self.c['bg'])
        try:
            icon = backend.BASE / 'app.ico'
            if icon.exists():
                root.iconbitmap(str(icon))
        except tk.TclError:
            pass
        self.build_menu()
        self.build_shell()
        self.compact_buttons(self.root)
        self.render_groups()
        if self.config['groups']:
            self.select_group(self.config['groups'][0]['id'])
        else:
            self.show_empty()
        self.pump_id = self.root.after(150, self.pump)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.bind('<Control-n>', lambda _: self.create_group())
        root.bind('<Control-f>', lambda _: self.search_entry.focus_set())
        root.bind('<F5>', lambda _: self.refresh_models())
        from ui_theme import apply_native_chrome
        self.chrome_id=root.after_idle(lambda:apply_native_chrome(root,self.c))
        if avatars is None:
            self.monitor = InventoryMonitor(self.events)
            self.monitor.start()
            self.auto_update_id=root.after(8000,lambda:self.check_updates(automatic=True))

    def configure_style(self):
        from ui_theme import apply_theme
        self.theme_images=apply_theme(self.root,self.c)
        self.button_images=list(self.theme_images.values())

    def update_status_marker(self):
        key='signal_good' if '共享中' in self.status.get() else 'signal_active' if any(s in self.status.get() for s in ('连接','等待','恢复')) else 'signal'
        self.status_marker.configure(image=self.theme_images[key])

    def compact_buttons(self,widget):
        for child in widget.winfo_children():
            if isinstance(child,ttk.Button):child.configure(width=0)
            self.compact_buttons(child)

    def update_navigation(self):
        for mode,button in self.nav_buttons.items():
            button.configure(style='NavSelected.TButton' if self.nav_mode==mode else 'Nav.TButton',image=self.theme_images[mode+'_active' if self.nav_mode==mode else mode])
        if self.running and callable(getattr(self.worker,'set_diagnostics',None)):
            self.worker.set_diagnostics(self.nav_mode=='diagnostics')

    def build_menu(self):
        menu = tk.Menu(self.root, tearoff=False)
        file = tk.Menu(menu, tearoff=False)
        file.add_command(label='新建共享组', accelerator='Ctrl+N', command=self.create_group)
        file.add_command(label='保存当前参数表', command=self.capture_parameters)
        file.add_command(label='查看参数快照', command=self.show_snapshots)
        file.add_command(label='本机模型资料库', command=self.show_models)
        file.add_command(label='运行诊断',command=self.show_diagnostics)
        file.add_separator()
        file.add_command(label='导入分组配置…', command=self.import_config)
        file.add_command(label='导出分组配置…', command=self.export_config)
        file.add_command(label='打开数据目录', command=self.open_data)
        file.add_separator()
        file.add_command(label='退出', command=self.close)
        menu.add_cascade(label='文件', menu=file)
        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label='检查更新…',command=self.check_updates)
        help_menu.add_separator()
        help_menu.add_command(label='快速开始', command=self.help)
        help_menu.add_command(label='关于 Avatar Switch Sync', command=self.about)
        menu.add_cascade(label='帮助', menu=help_menu)
        # Keep menu commands and shortcuts in a compact, styled command strip.
        self.root.config(menu='')
        self.menu_strip=ttk.Frame(self.root,style='Side.TFrame',padding=(12,2))
        self.menu_strip.pack(side='top',fill='x')
        for label,popup,key in [('文件  ▾',file,'f'),('帮助  ▾',help_menu,'h')]:
            popup.configure(font=('Microsoft YaHei UI',10),background=self.c['panel'],foreground=self.c['text'],activebackground=self.c['selected'],activeforeground=self.c['text'],borderwidth=0,relief='flat')
            button=ttk.Button(self.menu_strip,text=label,style='Menu.TButton')
            button.configure(command=lambda m=popup,b=button:m.tk_popup(b.winfo_rootx(),b.winfo_rooty()+b.winfo_height()))
            button.pack(side='left',padx=(0,4))
            self.root.bind('<Alt-'+key+'>',lambda _,m=popup,b=button:m.tk_popup(b.winfo_rootx(),b.winfo_rooty()+b.winfo_height()))
        self.update_button=ttk.Button(self.menu_strip,text='检查更新',style='Menu.TButton',command=self.open_updates)
        self.update_button.pack(side='right')

    def open_updates(self):
        if self.update_info:self.show_update_dialog()
        else:self.check_updates()

    def check_updates(self,automatic=False):
        if self.exit_requested:return
        if not automatic:
            self.update_manual=True
            self.show_update_dialog()
        if self.update_check and self.update_check.is_alive():return
        if self.update_download and self.update_download.is_alive():return
        self.update_message='正在检查 GitHub 更新…'
        self.update_button.configure(text='正在检查…')
        self.render_update_dialog()
        self.update_check=CheckWorker(VERSION,self.events)
        self.update_check.start()

    def show_update_dialog(self):
        if self.update_dialog and self.update_dialog.winfo_exists():
            self.update_dialog.lift();return
        dialog=tk.Toplevel(self.root);self.update_dialog=dialog
        dialog.title('软件更新');dialog.geometry('620x490');dialog.minsize(520,390)
        dialog.transient(self.root);dialog.configure(bg=self.c['bg'])
        frame=ttk.Frame(dialog,padding=24);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='软件更新',style='Section.TLabel').pack(anchor='w')
        ttk.Label(frame,text=f'当前版本 {VERSION}',style='Muted.TLabel').pack(anchor='w',pady=(6,12))
        self.update_status=tk.StringVar()
        ttk.Label(frame,textvariable=self.update_status,wraplength=550).pack(anchor='w',pady=(0,10))
        self.update_notes=tk.Text(frame,height=8,wrap='word',font=('Microsoft YaHei UI',10),background=self.c['panel'],foreground=self.c['text'],relief='flat',padx=12,pady=12,highlightthickness=0,state='disabled')
        self.update_notes.pack(fill='both',expand=True)
        self.update_bar=ttk.Progressbar(frame,mode='determinate',maximum=100)
        self.update_bar.pack(fill='x',pady=(12,8))
        ttk.Label(frame,text='安装会正常停止共享并重启软件，个人设置和记录会保留。',style='Muted.TLabel',wraplength=550).pack(anchor='w')
        actions=ttk.Frame(frame);actions.pack(fill='x',pady=(18,0))
        ttk.Button(actions,text='GitHub 版本页',command=lambda:webbrowser.open(self.update_info['page'] if self.update_info else RELEASES_URL)).pack(side='left')
        ttk.Button(actions,text='稍后',command=dialog.destroy).pack(side='right')
        self.update_action=ttk.Button(actions,text='下载更新',style='Primary.TButton',command=self.update_action_clicked)
        self.update_action.pack(side='right',padx=8)
        self.render_update_dialog()

    def render_update_dialog(self):
        if not self.update_dialog or not self.update_dialog.winfo_exists():return
        self.update_status.set(self.update_message)
        info=self.update_info
        self.update_notes.configure(state='normal');self.update_notes.delete('1.0','end')
        self.update_notes.insert('end',info['notes'] if info else '新版本会在这里显示更新内容。')
        self.update_notes.configure(state='disabled')
        downloading=self.update_downloading
        self.update_action.configure(text='安装并重启' if self.update_path else '下载中…' if downloading else '下载更新',state='disabled' if not info or downloading else 'normal')

    def update_action_clicked(self):
        if not self.update_info:return
        if self.update_path:
            try:
                start_install(self.update_path,self.update_info,self.data_dir,backend.BASE,self.running)
            except Exception as exc:
                self.update_message=str(exc);self.render_update_dialog();return
            self.close()
            return
        if self.update_download and self.update_download.is_alive():return
        self.update_download=DownloadWorker(self.update_info,self.data_dir,self.events)
        self.update_downloading=True
        self.update_message='正在下载安装程序，可稍后再安装。'
        self.update_bar['value']=0
        self.update_download.start()
        self.render_update_dialog()

    def build_shell(self):
        outer = ttk.Frame(self.root)
        outer.pack(fill='both', expand=True)
        side = ttk.Frame(outer, style='Side.TFrame', width=210, padding=(16, 24))
        side.pack(side='left', fill='y')
        side.pack_propagate(False)
        brand=ttk.Frame(side,style='Side.TFrame')
        brand.pack(fill='x')
        ttk.Label(brand,image=self.theme_images['models_active'],style='Side.TLabel').pack(side='left',padx=(0,8))
        ttk.Label(brand,text='Avatar Sync',style='Side.TLabel',font=('Segoe UI',15,'bold')).pack(side='left')
        ttk.Label(side, text='模型设置共享', style='SideMuted.TLabel',font=('Microsoft YaHei UI',10)).pack(anchor='w', pady=(5, 24))
        self.nav_buttons={}
        for mode,label,command in [('models','模型资料库',self.show_models),('snapshots','参数快照',self.show_snapshots),('diagnostics','运行诊断',self.show_diagnostics)]:
            button=ttk.Button(side,text='  '+label,image=self.theme_images[mode],compound='left',style='Nav.TButton',command=command)
            button.pack(fill='x',pady=(0,4 if mode!='diagnostics' else 22))
            self.nav_buttons[mode]=button
        ttk.Label(side, text='共享组', style='SideMuted.TLabel').pack(anchor='w', pady=(0, 8))
        self.groups = tk.Listbox(side, bg=self.c['side'], fg=self.c['text'], selectbackground=self.c['selected'], selectforeground=self.c['text'],
                                 relief='flat', borderwidth=0, highlightthickness=0, activestyle='none', exportselection=False,
                                 font=('Microsoft YaHei UI', 11), height=7)
        self.groups.pack(fill='both', expand=True)
        self.groups.bind('<<ListboxSelect>>', self.group_selected)
        self.new_button = ttk.Button(side, text='＋ 新建分组',style='Nav.TButton', command=self.create_group)
        self.new_button.pack(fill='x', pady=(10, 18))
        self.start_button=ttk.Button(side,text='开始共享',style='Primary.TButton',command=self.start_stop)
        self.start_button.pack(fill='x',pady=(0,10))
        self.add_button=ttk.Button(side,text='开启添加模式',style='SideAction.TButton',command=self.toggle_add_mode)
        self.add_button.pack(fill='x',pady=(0,4))
        self.add_hint=tk.StringVar(value='自动加入当前分组')
        ttk.Label(side,textvariable=self.add_hint,style='SideMuted.TLabel',wraplength=175,anchor='center',justify='center',font=('Microsoft YaHei UI',10)).pack(fill='x',pady=(4,0))
        ttk.Label(side, text=f'启动前自动备份\n版本 {VERSION} · 本机保存', style='SideMuted.TLabel',font=('Microsoft YaHei UI',10)).pack(anchor='w', pady=(8, 0))
        self.main = ttk.Frame(outer, padding=(26, 18, 26, 12))
        self.main.pack(side='left', fill='both', expand=True)
        top = ttk.Frame(self.main)
        top.pack(fill='x')
        self.heading = tk.StringVar(value='开始共享模型设置')
        self.capture_button = ttk.Button(top, text='保存快照', command=self.capture_parameters)
        self.capture_button.pack(side='right')
        self.refresh_button = ttk.Button(top,text='刷新',style='Quiet.TButton',command=self.refresh_models)
        self.refresh_button.pack(side='right',padx=(0,8))
        self.heading_label = ttk.Label(top, textvariable=self.heading, style='Title.TLabel', wraplength=600)
        self.heading_label.pack(side='left', fill='x', expand=True)
        self.subtitle = tk.StringVar(value='创建一个共享组，选择需要延续设置的模型。')
        ttk.Label(self.main, textvariable=self.subtitle, style='Muted.TLabel').pack(anchor='w', pady=(4, 10))
        status_card=Card(self.main,self.c['panel'],self.c['bg'],padding=(14,8))
        status_card.configure(height=86)
        status_card.body.bind('<Configure>',lambda _:status_card.configure(height=status_card.body.winfo_reqheight()+12))
        status_card.pack(fill='x')
        status_box=status_card.body
        self.status_marker=ttk.Label(status_box,image=self.theme_images['signal'],style='Panel.TLabel')
        self.status_marker.pack(side='left',padx=(0,12))
        status_copy=ttk.Frame(status_box,style='Panel.TFrame')
        status_copy.pack(side='left',fill='both',expand=True)
        self.status = tk.StringVar(value='尚未启动')
        self.status.trace_add('write',lambda *_:self.update_status_marker())
        self.status_label=ttk.Label(status_copy,textvariable=self.status,style='Panel.TLabel',font=('Microsoft YaHei UI',11,'bold'),wraplength=600)
        self.status_label.pack(anchor='w')
        self.result_text=tk.StringVar(value='开始共享前会自动保存一份备份，实时追踪流始终受保护。')
        self.result_label=ttk.Label(status_copy,textvariable=self.result_text,style='PanelMuted.TLabel',font=('Microsoft YaHei UI',10),wraplength=600)
        self.result_label.pack(anchor='w',pady=(4,0))
        self.content = ttk.Frame(self.main)
        self.content.pack(fill='both', expand=True, pady=(10, 0))
        self.empty = ttk.Frame(self.content, padding=(28, 40))
        self.snapshot_view = ttk.Frame(self.content)
        self.build_snapshots()
        self.models_view = ttk.Frame(self.content)
        self.build_models()
        self.diagnostics_view=ttk.Frame(self.content)
        self.build_diagnostics()
        ttk.Label(self.empty, text='从你自己的模型开始', style='Section.TLabel').pack(anchor='center', pady=(16, 12))
        ttk.Label(self.empty, text='先选择一个参考模型，保存常用设置。\n之后开启添加模式，换模型即可扩充共享组。', style='Muted.TLabel', justify='center').pack(anchor='center')
        ttk.Button(self.empty, text='创建第一个共享组', style='Primary.TButton', command=self.create_group).pack(pady=(24, 12))
        self.local_hint = tk.StringVar(value=f'已在本机发现 {len(self.avatars)} 个模型；也可以导入已有分组配置。')
        ttk.Label(self.empty, textvariable=self.local_hint, style='Muted.TLabel', wraplength=600, justify='center').pack(anchor='center', pady=6)
        ttk.Button(self.empty, text='刷新本机模型', command=self.refresh_models).pack(pady=8)
        self.editor = ttk.Frame(self.content)
        membership = ttk.Frame(self.editor)
        membership.pack(fill='x', pady=(0, 8))
        self.member_text = tk.StringVar()
        self.members_expanded = False
        self.member_button = ttk.Button(membership,textvariable=self.member_text,style='Quiet.TButton',command=self.toggle_members)
        self.member_button.pack(side='left')
        self.edit_button = ttk.Button(membership, text='编辑分组', command=self.edit_group)
        self.edit_button.pack(side='right', padx=(8, 0))
        self.more_menu = tk.Menu(self.root, tearoff=False)
        self.more_menu.add_command(label='刷新模型与参数', command=self.refresh_models)
        self.more_menu.add_command(label='恢复默认共享范围', command=self.apply_defaults)
        self.more_menu.add_separator()
        self.more_menu.add_command(label='删除此共享组…', command=self.delete_group)
        self.more_button = ttk.Button(membership, text='更多', command=self.show_more)
        self.more_button.pack(side='right')
        self.member_panel = ttk.Frame(self.editor)
        self.member_table = ttk.Treeview(self.member_panel,columns=('number','name'),show='headings',height=4,selectmode='browse')
        self.member_table.heading('number',text='序号')
        self.member_table.column('number',width=55,minwidth=55,stretch=False,anchor='center')
        self.member_table.heading('name',text='模型名称',anchor='w')
        self.member_table.column('name',width=550,minwidth=120)
        self.member_scroll=ttk.Scrollbar(self.member_panel,command=self.member_table.yview)
        self.member_table.configure(yscrollcommand=self.member_scroll.set)
        self.member_table.pack(side='left',fill='both',expand=True)
        self.member_scroll.pack(side='right',fill='y')
        self.tabs = ttk.Notebook(self.editor)
        self.tabs.pack(fill='both', expand=True)
        params_card=Card(self.tabs,self.c['panel'],self.c['bg'],padding=8)
        params=params_card.body
        params.columnconfigure(0, weight=1)
        params.rowconfigure(2, weight=1)
        logs = ttk.Frame(self.tabs, style='Panel.TFrame', padding=14)
        self.tabs.add(params_card, text='共享参数')
        self.tabs.add(logs, text='运行记录')
        toolbar = ttk.Frame(params, style='Panel.TFrame')
        toolbar.grid(row=0, column=0, sticky='ew', pady=(0, 8))
        ttk.Label(toolbar,text='搜索',style='PanelMuted.TLabel').pack(side='left',padx=(0,10))
        self.search = tk.StringVar()
        self.search_entry = ttk.Entry(toolbar, textvariable=self.search, width=25)
        self.search_entry.pack(side='left', fill='x', expand=True)
        self.search.trace_add('write', lambda *_: self.paint_rows())
        self.filter = tk.StringVar(value='全部参数')
        self.filter_box = ttk.Combobox(toolbar, state='readonly', textvariable=self.filter, values=['全部参数', '参与共享', '未参与共享', '受保护'], width=13)
        self.filter_box.pack(side='left', padx=(8, 0))
        self.filter_box.bind('<<ComboboxSelected>>', lambda _: self.paint_rows())
        table_frame = ttk.Frame(params, style='Panel.TFrame')
        table_frame.grid(row=2, column=0, sticky='nsew')
        self.table = ttk.Treeview(table_frame, columns=('enabled', 'name', 'type', 'models', 'value'), show='headings', selectmode='extended', height=4)
        for key, title, width in [('enabled', '共享', 65), ('name', '功能 / 参数名称', 320), ('type', '类型', 60), ('models', '模型覆盖', 85), ('value', '已记录值', 95)]:
            self.table.heading(key, text=title,anchor='w' if key=='name' else 'center', command=self.sort_rows if key=='name' else '')
            self.table.column(key, width=width, minwidth=45, stretch=key=='name', anchor='w' if key=='name' else 'center')
        scroll = ttk.Scrollbar(table_frame, command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.table.tag_configure('muted', foreground=self.c['muted'])
        self.table.tag_configure('stripe',background=self.c['stripe'])
        self.table.bind('<ButtonRelease-1>', self.table_click)
        self.table.bind('<space>', self.table_space)
        self.table.bind('<<TreeviewSelect>>', lambda _: self.render_detail())
        actions = ttk.Frame(params, style='Panel.TFrame')
        actions.grid(row=3, column=0, sticky='ew', pady=(8, 6))
        self.enable_button = ttk.Button(actions, text='共享选中', command=lambda:self.set_selected(True))
        self.disable_button = ttk.Button(actions, text='排除选中', command=lambda:self.set_selected(False))
        self.enable_button.pack(side='left')
        self.disable_button.pack(side='left', padx=6)
        self.count = tk.StringVar()
        ttk.Label(actions, textvariable=self.count, style='PanelMuted.TLabel').pack(side='right')
        self.detail = tk.StringVar(value='选择一项查看原始参数和排除原因。')
        self.detail_label = ttk.Label(params, textvariable=self.detail, style='PanelMuted.TLabel',font=('Microsoft YaHei UI',10), wraplength=700, justify='left')
        self.detail_label.grid(row=4, column=0, sticky='ew')
        log_header = ttk.Frame(logs, style='Panel.TFrame')
        log_header.pack(fill='x', pady=(0, 12))
        ttk.Label(log_header, text='本次运行的连接、恢复与记录事件', style='PanelMuted.TLabel').pack(side='left')
        ttk.Button(log_header, text='复制记录', command=self.copy_logs).pack(side='right')
        self.logs = tk.Text(logs, bg=self.c['panel'], fg=self.c['text'], font=('Microsoft YaHei UI',10), relief='flat', borderwidth=0, highlightthickness=0, wrap='word', state='disabled', padx=4, pady=4)
        self.logs.pack(fill='both', expand=True)
        self.notice = tk.StringVar(value='就绪 · 修改会自动保存')
        footer = ttk.Frame(self.main)
        self.content.pack_forget()
        footer.pack(side='bottom', fill='x', pady=(12, 0))
        self.content.pack(fill='both', expand=True, pady=(10, 0))
        ttk.Label(footer, textvariable=self.notice, style='Muted.TLabel').pack(side='left')
        ttk.Label(footer, text='实时眼追流受保护', style='Muted.TLabel').pack(side='right')
        self.main.bind('<Configure>', self.resize_content)

    def resize_content(self, event):
        if event.widget is self.main:
            self.heading_label.configure(wraplength=max(250, event.width-290))
            self.status_label.configure(wraplength=max(260,event.width-140))
            self.result_label.configure(wraplength=max(260,event.width-140))
            self.detail_label.configure(wraplength=max(300, event.width-100))

    @property
    def running(self):
        return self.worker is not None and self.worker.is_alive()

    def group(self):
        return next((g for g in self.config['groups'] if g['id']==self.current_group), None)

    def save(self):
        try:
            backend.write_json(self.data_dir/'config.json', validate_config(self.config))
        except (ValueError, OSError) as exc:
            self.notice.set('设置尚未保存，请检查数据目录。')
            messagebox.showerror('无法保存设置', str(exc), parent=self.root)
            return False
        self.notice.set('已保存到本机 · ' + time.strftime('%H:%M:%S'))
        return True

    def editable(self):
        if self.running:
            self.notice.set('共享运行中；停止后可修改分组和共享范围。')
            return False
        return True

    def render_groups(self):
        self.groups.delete(0, 'end')
        self.group_ids = [g['id'] for g in self.config['groups']]
        for g in self.config['groups']:
            self.groups.insert('end', f"  {g['name']}  ·  {len(g['avatars'])}")
        if self.current_group in self.group_ids:
            i = self.group_ids.index(self.current_group)
            self.groups.selection_set(i)
            self.groups.see(i)
        self.start_button.configure(state='normal' if self.config['groups'] else 'disabled')
        self.add_button.configure(state='normal' if self.config['groups'] else 'disabled')

    def group_selected(self, _):
        selected = self.groups.curselection()
        if selected:
            self.select_group(self.group_ids[selected[0]])

    def select_group(self, gid):
        if gid != self.current_group:
            self.members_expanded = False
            self.member_panel.pack_forget()
        self.nav_mode = 'group'
        self.update_navigation()
        self.current_group = gid
        group = self.group()
        if not group:
            return self.show_empty()
        self.empty.pack_forget()
        self.snapshot_view.pack_forget()
        self.models_view.pack_forget()
        self.diagnostics_view.pack_forget()
        self.editor.pack(fill='both', expand=True)
        self.heading.set(group['name'])
        self.subtitle.set(f"{len(group['avatars'])} 个模型 · 仅显示全部组员共有的保存项")
        self.render_members()
        self.search.set('')
        self.paint_rows()
        self.render_groups()

    def render_members(self):
        group = self.group()
        if not group:return
        self.member_text.set(('▾' if self.members_expanded else '▸')+f" 成员 · {len(group['avatars'])}")
        self.member_table.delete(*self.member_table.get_children())
        for index,aid in enumerate(group['avatars'],1):
            name=self.avatars[aid]['name'] if aid in self.avatars else f'未匹配 ({aid[-8:]})'
            self.member_table.insert('','end',iid=aid,values=(index,name))
        self.member_table.configure(height=min(4,len(group['avatars'])))

    def toggle_members(self):
        self.members_expanded = not self.members_expanded
        if self.members_expanded:self.member_panel.pack(fill='x',before=self.tabs,pady=(0,12))
        else:self.member_panel.pack_forget()
        self.render_members()

    def show_empty(self):
        self.nav_mode = 'empty'
        self.update_navigation()
        self.current_group = None
        self.editor.pack_forget()
        self.snapshot_view.pack_forget()
        self.models_view.pack_forget()
        self.diagnostics_view.pack_forget()
        self.empty.pack(fill='both', expand=True)
        self.heading.set('开始共享模型设置')
        self.subtitle.set('建立共享组，在切换模型后延续常用设置。')
        self.start_button.configure(state='disabled')

    def build_snapshots(self):
        self.snapshot_choice = tk.StringVar()
        self.snapshot_combo = ttk.Combobox(self.snapshot_view, textvariable=self.snapshot_choice, state='readonly')
        self.snapshot_combo.pack(fill='x', pady=(0, 12))
        self.snapshot_combo.bind('<<ComboboxSelected>>', lambda _: self.render_snapshot())
        self.snapshot_info = tk.StringVar(value='尚未保存快照。点击“保存当前参数表”读取当前模型。')
        ttk.Label(self.snapshot_view, textvariable=self.snapshot_info, style='Muted.TLabel', wraplength=680).pack(anchor='w', pady=(0, 12))
        self.snapshot_search = tk.StringVar()
        ttk.Entry(self.snapshot_view, textvariable=self.snapshot_search).pack(fill='x', pady=(0, 10))
        self.snapshot_search.trace_add('write', lambda *_: self.render_snapshot())
        table_frame = ttk.Frame(self.snapshot_view)
        table_frame.pack(fill='both', expand=True)
        self.snapshot_table = ttk.Treeview(table_frame, columns=('name', 'type', 'value', 'saved'), show='headings', height=5)
        for key, text, width in [('name','参数原名',380),('type','类型',70),('value','快照值',150),('saved','本地保存记录',115)]:
            self.snapshot_table.heading(key,text=text)
            self.snapshot_table.column(key,width=width,minwidth=55,stretch=key in ('name','value'))
        scroll = ttk.Scrollbar(table_frame,command=self.snapshot_table.yview)
        self.snapshot_table.configure(yscrollcommand=scroll.set)
        self.snapshot_table.pack(side='left',fill='both',expand=True)
        scroll.pack(side='right',fill='y')

    def capture_parameters(self):
        if self.capture_worker and self.capture_worker.is_alive(): return
        self.capture_worker = CaptureWorker(self.data_dir,self.events)
        self.capture_button.configure(state='disabled',text='正在保存…')
        self.notice.set('正在读取当前模型的实时参数；不修改游戏状态。')
        self.capture_worker.start()

    def show_snapshots(self, identifier=None):
        self.nav_mode = 'snapshots'
        self.update_navigation()
        self.editor.pack_forget()
        self.empty.pack_forget()
        self.models_view.pack_forget()
        self.diagnostics_view.pack_forget()
        self.snapshot_view.pack(fill='both',expand=True)
        self.groups.selection_clear(0,'end')
        self.heading.set('参数快照')
        self.subtitle.set('手动保存当前模型的完整参数表，随时查看当时的数值。')
        self.snapshots = list_snapshots(self.data_dir)
        labels = [f"{s['captured_at'].replace('T',' ')}  ·  {'自动备份' if s.get('kind')=='automatic_start' else '手动快照'}  ·  {s['avatar_name']}  ·  {len(s['parameters'])} 项" for s in self.snapshots]
        self.snapshot_combo['values'] = labels
        if self.snapshots:
            index = next((i for i,s in enumerate(self.snapshots) if s['id']==identifier),0)
            self.snapshot_combo.current(index)
        else:
            self.snapshot_combo.set('尚无参数快照')
        self.snapshot_search.set('')
        self.render_snapshot()

    def build_models(self):
        self.model_summary = tk.StringVar()
        ttk.Label(self.models_view,textvariable=self.model_summary,style='Section.TLabel').pack(anchor='w',pady=(0,10))
        ttk.Label(self.models_view,text='新上传的模型需在游戏中实际加载并启用 OSC。列表会自动更新，也可随时刷新。',style='Muted.TLabel',wraplength=680).pack(anchor='w',pady=(0,14))
        searchbar = ttk.Frame(self.models_view)
        searchbar.pack(fill='x',pady=(0,12))
        ttk.Label(searchbar,text='搜索名称或 ID',style='Muted.TLabel').pack(side='left',padx=(0,10))
        self.model_search = tk.StringVar()
        ttk.Entry(searchbar,textvariable=self.model_search).pack(side='left',fill='x',expand=True)
        self.model_search.trace_add('write',lambda *_:self.render_models())
        table = ttk.Frame(self.models_view)
        table.pack(fill='both',expand=True)
        self.model_table = ttk.Treeview(table,columns=('name','updated','parameters','saved','status'),show='headings',height=5)
        for key,label,width in [('name','模型名称',240),('updated','缓存更新',135),('parameters','参数',70),('saved','保存项',70),('status','资料状态',120)]:
            self.model_table.heading(key,text=label)
            self.model_table.column(key,width=width,minwidth=55,stretch=key=='name')
        scrollbar = ttk.Scrollbar(table,command=self.model_table.yview)
        self.model_table.configure(yscrollcommand=scrollbar.set)
        self.model_table.pack(side='left',fill='both',expand=True)
        scrollbar.pack(side='right',fill='y')
        self.model_table.bind('<<TreeviewSelect>>',lambda _:self.model_selected())
        self.model_detail = tk.StringVar(value='选择模型查看完整 ID 和可用状态。')
        ttk.Label(self.models_view,textvariable=self.model_detail,style='Muted.TLabel',wraplength=680).pack(anchor='w',pady=(12,0))

    def show_models(self):
        self.nav_mode = 'models'
        self.update_navigation()
        for view in (self.editor,self.empty,self.snapshot_view,self.diagnostics_view):view.pack_forget()
        self.models_view.pack(fill='both',expand=True)
        self.groups.selection_clear(0,'end')
        self.heading.set('本机模型')
        self.subtitle.set('自动发现本地模型缓存 · 无需重启软件')
        self.render_models()

    def build_diagnostics(self):
        ttk.Label(self.diagnostics_view,text='实时资源与连接',style='Section.TLabel').pack(anchor='w',pady=(0,8))
        ttk.Label(self.diagnostics_view,text='仅在打开本页时每秒采样。本页只测量本软件，不能据此判断游戏帧率。',style='Muted.TLabel',wraplength=650).pack(anchor='w',pady=(0,18))
        grid=ttk.Frame(self.diagnostics_view)
        grid.pack(fill='x')
        grid.columnconfigure(0,weight=1)
        grid.columnconfigure(1,weight=1)
        self.diagnostic_fields={}
        for i,(key,label) in enumerate([('cpu','CPU 占用'),('memory','内存使用'),('read','最近一次参数读取'),('rate','完整校验频率'),('received','收到的数据包'),('sent','写入的数据包')]):
            card=ttk.Frame(grid,style='Panel.TFrame',padding=18)
            card.grid(row=i//2,column=i%2,sticky='ew',padx=(0 if i%2==0 else 6,6 if i%2==0 else 0),pady=(0,12))
            ttk.Label(card,text=label,style='PanelMuted.TLabel').pack(anchor='w')
            value=tk.StringVar(value='—')
            ttk.Label(card,textvariable=value,style='Panel.TLabel',font=('Segoe UI',18,'bold')).pack(anchor='w',pady=(7,0))
            self.diagnostic_fields[key]=value
        ttk.Label(self.diagnostics_view,text='稳定运行时不轮询完整参数表；通过 OSC 通知记录变化，仅每 5 秒轻量检查连接。\nCPU 按全机逻辑核心数折算。停止后保留最后一次采样，数据不上传。',style='Muted.TLabel',wraplength=650).pack(anchor='w',pady=(10,0))

    def show_diagnostics(self):
        self.nav_mode='diagnostics'
        self.update_navigation()
        for view in (self.editor,self.empty,self.snapshot_view,self.models_view):view.pack_forget()
        self.diagnostics_view.pack(fill='both',expand=True)
        self.groups.selection_clear(0,'end')
        self.heading.set('运行诊断')
        self.subtitle.set('查看本软件的实时资源占用和连接状态')
        self.render_diagnostics()

    def render_diagnostics(self):
        if not self.runtime_metrics:return
        m=self.runtime_metrics
        values={'cpu':f"{m['cpu_percent']:.2f}%",'memory':f"{m['memory_mb']:.1f} MB" if m.get('memory_mb') is not None else '暂不可用',
                'read':f"{m['read_ms']:.1f} ms",'rate':f"{m['reads_per_second']:.1f} 次 / 秒",'received':str(m['received']),'sent':str(m['sent'])}
        for key,value in values.items():self.diagnostic_fields[key].set(value)

    def render_models(self):
        selected = self.model_table.selection()
        self.model_table.delete(*self.model_table.get_children())
        needle = self.model_search.get().lower().strip()
        count = 0
        for aid,avatar in sorted(self.avatars.items(),key=lambda item:item[1]['mtime'],reverse=True):
            if needle and needle not in (avatar['name']+' '+aid).lower():continue
            saved = avatar.get('saved_names',set())
            state = '资料就绪' if saved else '等待保存记录'
            if avatar.get('saved_status')=='unavailable':state='保存记录暂不可读'
            updated = time.strftime('%m-%d %H:%M',time.localtime(avatar['mtime']))
            self.model_table.insert('','end',iid=aid,values=(avatar['name'],updated,len(avatar['defs']),len(saved),state))
            count += 1
        for aid in selected:
            if self.model_table.exists(aid):self.model_table.selection_add(aid)
        self.model_summary.set(f'已发现 {len(self.avatars)} 个模型' + (f' · 搜索结果 {count} 个' if needle else ''))
        self.model_selected()

    def model_selected(self):
        selected = self.model_table.selection()
        if not selected:
            self.model_detail.set('找不到模型？先在游戏中加载该模型，确认 OSC 已启用，再点击顶部“刷新模型”。')
            return
        aid = selected[0]
        avatar = self.avatars[aid]
        status = '已具备本地参数与保存记录，可加入共享组。' if avatar['saved_names'] else '已发现模型，尚无保存记录；可加入分组，暂不参与参数同步。'
        self.model_detail.set(aid+'\n'+status)

    def accept_inventory(self, avatars):
        added = set(avatars)-set(self.avatars)
        self.avatars = avatars
        self.local_hint.set(f'本机已发现 {len(avatars)} 个模型，游戏加载新模型后会自动更新。')
        self.render_models()
        if self.group_editor and self.group_editor.winfo_exists():self.group_editor.update_inventory()
        if self.group():
            self.paint_rows()
            self.render_members()
        if added:self.notice.set(f'已自动发现 {len(added)} 个新模型，可在“本机模型”中查看。')
        return added

    def render_snapshot(self):
        self.snapshot_table.delete(*self.snapshot_table.get_children())
        index = self.snapshot_combo.current()
        if not 0 <= index < len(self.snapshots):
            self.snapshot_info.set('尚未保存快照。点击“保存当前参数表”读取当前模型；无需先开始共享。')
            return
        item = self.snapshots[index]
        kind='启动前自动备份（仅保留最近 20 份）' if item.get('kind')=='automatic_start' else '手动快照（长期保留）'
        self.snapshot_info.set(f"{item['avatar_name']} · 共 {len(item['parameters'])} 项 · {kind} · 不自动恢复")
        needle = self.snapshot_search.get().lower().strip()
        for p in item['parameters']:
            if needle and needle not in p['name'].lower(): continue
            value = json.dumps(p['value'],ensure_ascii=False) if p['has_value'] else '不可读取'
            saved = '有记录' if p['saved_locally'] is True else '无记录' if p['saved_locally'] is False else '未知'
            self.snapshot_table.insert('','end',values=(p['name'],p['type'],value,saved))

    def create_group(self):
        if not self.editable(): return
        self.accept_inventory(backend.inventory())
        if not self.avatars:
            messagebox.showinfo('尚未发现模型', '请先在 VRChat 中启用 OSC，并加载一个参考模型，然后点击“刷新本机模型”。', parent=self.root)
            return
        dialog = GroupEditor(self)
        self.group_editor = dialog
        self.root.wait_window(dialog)
        self.group_editor = None
        if dialog.result:
            group = {'id':uuid.uuid4().hex, **dialog.result, 'parameters':backend.candidates(self.avatars, dialog.result['avatars'])}
            self.config['groups'].append(group)
            self.save()
            self.select_group(group['id'])

    def edit_group(self):
        if not self.editable() or not self.group(): return
        self.accept_inventory(backend.inventory())
        group = self.group()
        dialog = GroupEditor(self, group)
        self.group_editor = dialog
        self.root.wait_window(dialog)
        self.group_editor = None
        if dialog.result:
            previous = {p['name']:p for p in group['parameters']}
            known = [a for a in dialog.result['avatars'] if a in self.avatars]
            rows = backend.candidates(self.avatars, known)
            for p in rows:
                if p['name'] in previous:
                    p.update(copy.deepcopy(previous[p['name']]))
                    if 'mapping' in p:
                        p['mapping'] = {a:n for a,n in p['mapping'].items() if a in dialog.result['avatars']}
            # Keep explicit mappings and unmatched definitions until the user resolves them.
            names = {p['name'] for p in rows}
            rows.extend(copy.deepcopy(p) for p in group['parameters'] if p['name'] not in names)
            for p in rows:
                if 'mapping' in p:
                    p['mapping'] = {a:n for a,n in p['mapping'].items() if a in dialog.result['avatars']}
            group.update(dialog.result)
            group['parameters'] = rows
            self.save()
            self.select_group(group['id'])

    def delete_group(self):
        group = self.group()
        if not self.editable() or not group: return
        if not messagebox.askyesno('删除共享组', f"删除“{group['name']}”？\n只移除分组配置，不改动游戏里的模型。", parent=self.root): return
        self.config['groups'] = [g for g in self.config['groups'] if g['id']!=group['id']]
        self.save()
        self.current_group = None
        self.render_groups()
        if self.config['groups']: self.select_group(self.config['groups'][0]['id'])
        else: self.show_empty()

    def refresh_models(self):
        if self.monitor:
            self.monitor.request_refresh()
            self.notice.set('正在检查本机模型缓存…')
            return
        self.accept_inventory(backend.inventory())
        self.reconcile_parameters()

    def reconcile_parameters(self):
        if self.running:
            self.notice.set(f'已刷新 {len(self.avatars)} 个模型；停止共享后可调整成员。')
            return
        if self.group_editor and self.group_editor.winfo_exists():
            self.notice.set('模型列表已刷新，当前选择已保留。')
            return
        group = self.group()
        if group:
            old = {p['name']:p for p in group['parameters']}
            rows = backend.candidates(self.avatars, [a for a in group['avatars'] if a in self.avatars])
            for p in rows:
                if p['name'] in old: p.update(copy.deepcopy(old[p['name']]))
            names = {p['name'] for p in rows}
            rows.extend(copy.deepcopy(p) for p in group['parameters'] if p['name'] not in names)
            group['parameters'] = rows
            self.save()
            if self.nav_mode=='group':self.select_group(group['id'])
        self.local_hint.set(f'已在本机发现 {len(self.avatars)} 个模型；可新建或导入分组。')
        self.notice.set(f'模型列表已刷新 · {len(self.avatars)} 个本机模型')

    def show_more(self):
        self.more_menu.tk_popup(self.more_button.winfo_rootx(), self.more_button.winfo_rooty()+self.more_button.winfo_height())

    def apply_defaults(self):
        if not self.editable() or not self.group(): return
        for p in self.group()['parameters']:
            p['reason'] = default_exclusion(p['name'])
            p['enabled'] = not bool(p['reason'])
        self.save()
        self.paint_rows()

    def paint_rows(self):
        group=self.group()
        if not group:return
        selected=self.table.selection()
        position=self.table.yview()
        needle,mode=self.search.get().lower().strip(),self.filter.get()
        rows=sorted(enumerate(group['parameters']),key=lambda pair:display_name(pair[1]['name']).casefold(),reverse=self.sort_reverse)
        saved=self.state_cache.get(group['id'],{})
        rendered=[]
        common=[]
        for i,p in rows:
            if not backend.compatible_parameter(self.avatars,group,p):continue
            common.append(p)
            lock=protected(p['name'])
            enabled=p['enabled'] and not lock
            if needle and needle not in (p['name']+' '+display_name(p['name'])).lower():continue
            if mode=='参与共享' and not enabled or mode=='未参与共享' and enabled or mode=='受保护' and not lock:continue
            value=saved.get(p['name'],{}).get('value',None)
            label='未记录' if value is None else ('开' if value else '关') if type(value) is bool else f'{value:.4g}' if isinstance(value,float) else str(value)
            values=('保护' if lock else '✓' if enabled else '—',display_name(p['name']),p['type'],f"{len(group['avatars'])}/{len(group['avatars'])}",label)
            rendered.append((str(i),values,(('stripe',) if len(rendered)%2 else ()) + (() if enabled else ('muted',))))
        order=tuple(iid for iid,_,_ in rendered)
        rebuild=self._table_group!=group['id'] or self.table.get_children()!=order
        if rebuild:
            self.table.delete(*self.table.get_children())
            self._row_values={}
        for iid,values,tags in rendered:
            if rebuild:self.table.insert('','end',iid=iid,values=values,tags=tags)
            elif self._row_values.get(iid)!=(values,tags):self.table.item(iid,values=values,tags=tags)
            self._row_values[iid]=(values,tags)
        if rebuild and self._table_group==group['id']:
            for iid in selected:
                if self.table.exists(iid):self.table.selection_add(iid)
            if position:self.table.yview_moveto(position[0])
        self._table_group=group['id']
        count=sum(p['enabled'] and not protected(p['name']) for p in common)
        self.count.set(f"共享 {count} / {len(common)} 项")
        self.render_detail()

    def sort_rows(self):
        self.sort_reverse = not self.sort_reverse
        self.paint_rows()

    def table_click(self, event):
        row = self.table.identify_row(event.y)
        if row and self.table.identify_column(event.x)=='#1':
            self.toggle_rows([row])

    def table_space(self, _):
        self.toggle_rows(self.table.selection())
        return 'break'

    def toggle_rows(self, ids):
        if not self.editable() or not self.group(): return
        for iid in ids:
            p = self.group()['parameters'][int(iid)]
            if not protected(p['name']): p['enabled'] = not p['enabled']
        self.save()
        self.paint_rows()

    def set_selected(self, value):
        if not self.editable() or not self.group(): return
        if not self.table.selection():
            self.notice.set('请先选择一个或多个参数。')
            return
        for iid in self.table.selection():
            p = self.group()['parameters'][int(iid)]
            if not protected(p['name']): p['enabled'] = value
        self.save()
        self.paint_rows()

    def render_detail(self):
        selection = self.table.selection()
        if not selection or not self.group():
            self.detail.set('点击共享列或按空格切换 · 支持多选 · 选择参数查看详情')
            return
        p = self.group()['parameters'][int(selection[0])]
        reason = '受保护：实时追踪、内部同步或重置动作' if protected(p['name']) else '参与共享' if p['enabled'] else p.get('reason') or '手动排除'
        raw = p['name'] if len(p['name']) <= 130 else p['name'][:127]+'…'
        self.detail.set(f"原始参数  {raw}\n{reason} · 来源：游戏本地保存记录（未核对当前构建的 Saved 标记）")

    def import_config(self):
        if not self.editable(): return
        filename = filedialog.askopenfilename(parent=self.root, title='导入分组配置', filetypes=[('分组配置','*.json')])
        if not filename: return
        try:
            incoming = load_config(Path(filename))
            merged = merge_config(self.config, incoming)
            self.config = merged
            self.save()
            self.render_groups()
            if incoming['groups']: self.select_group(merged['groups'][-len(incoming['groups'])]['id'])
            self.notice.set(f"已导入 {len(incoming['groups'])} 个组 · 不导入运行状态")
        except (ValueError, OSError) as exc:
            messagebox.showerror('无法导入', str(exc), parent=self.root)

    def export_config(self):
        if not self.config['groups']:
            self.notice.set('暂无分组可导出。')
            return
        filename = filedialog.asksaveasfilename(parent=self.root, title='导出分组配置', defaultextension='.json', initialfile='avatar-sync-groups.json', filetypes=[('分组配置','*.json')])
        if filename:
            try:
                backend.write_json(Path(filename), validate_config(self.config))
                self.notice.set('已导出分组配置 · 包含模型 ID，不含保存值和运行记录')
            except OSError as exc:
                messagebox.showerror('无法导出', str(exc), parent=self.root)

    def open_data(self):
        self.data_dir.mkdir(exist_ok=True, parents=True)
        os.startfile(self.data_dir)

    def help(self):
        messagebox.showinfo('快速开始', '1. 在 VRChat 中启用 OSC，分别加载需要共享的模型。\n2. 新建共享组，先选择一个参考模型。\n3. 检查共享参数，点击“开始共享”。\n\n衣服按名称筛选；自动命名暂未通过 Unity 菜单映射验证。\n眼追实时值不会写入，已知静态开关会在换模时恢复。', parent=self.root)

    def about(self):
        messagebox.showinfo('关于', f'Avatar Switch Sync {VERSION}\n模型设置共享工具\n\n独立 OSCQuery 连接 · 本机保存配置\n分发包不包含预设模型或个人数据。\n\n数据目录：{self.data_dir}', parent=self.root)

    def start_stop(self):
        if self.running: self.stop()
        else: self.start()

    def start(self, capture_current=True, add_group=None):
        if self.running: return
        effective = backend.common_config(self.config, self.avatars)
        if not any(p['enabled'] and not protected(p['name']) for g in effective['groups'] for p in g['parameters']):
            self.notice.set('先创建共享组，并选择至少一项共享参数。')
            return
        if not capture_current and not any(p['enabled'] and p['name'] in self.state_cache.get(g['id'],{})
                and self.state_cache[g['id']][p['name']].get('type')==p['type']
                and backend.valid(self.state_cache[g['id']][p['name']].get('value'),p['type'])
                for g in effective['groups'] for p in g['parameters']):
            self.notice.set('尚无可恢复的共享记录，请先手动开始共享，保存参考模型的设置。')
            return
        if not self.save(): return
        self.worker = backend.Worker(copy.deepcopy(self.config), self.events, self.data_dir,capture_current=capture_current,add_group=add_group)
        self.worker.set_diagnostics(self.nav_mode=='diagnostics')
        self.worker.start()
        self.start_button.configure(text='停止共享')
        self.status.set('正在连接 VRChat…')
        self.last_result=None
        self.runtime_error=None
        self.result_text.set('等待模型稳定后，将当前游戏参数保存为最新共享记录。' if capture_current else '等待模型稳定后恢复已有共享记录，保留原保存值。')
        self.set_edit_controls(False)

    def toggle_add_mode(self):
        if self.add_group:
            if self.running:self.worker.set_add_group(None)
            self.clear_add_mode()
            self.notice.set('已退出添加模式，继续共享现有组员的设置。')
            return
        group = self.group()
        if not group:
            self.notice.set('请先在左侧选择要加入的共享组。')
            return
        record = self.state_cache.get(group['id'],{})
        if not any(p['enabled'] and not protected(p['name']) and p['name'] in record and record[p['name']].get('type')==p['type'] and backend.valid(record[p['name']].get('value'),p['type']) for p in group['parameters']):
            self.notice.set('请先在参考模型上开始共享一次，保存该组的设置，再开启添加模式。')
            return
        if self.running:self.worker.set_add_group(group['id'])
        else:
            self.start(capture_current=False,add_group=group['id'])
            if not self.running:return
        self.add_group = group['id']
        self.add_button.configure(text='退出添加模式',style='NavSelected.TButton')
        self.add_hint.set('正在添加到：'+group['name'])
        self.notice.set('切换模型即可加入“'+group['name']+'”并同步；其他分组的模型会跳过。')

    def clear_add_mode(self):
        self.add_group = None
        self.add_button.configure(text='开启添加模式',style='SideAction.TButton')
        self.add_hint.set('自动加入当前分组')

    def set_edit_controls(self, value):
        state = 'normal' if value else 'disabled'
        for widget in (self.new_button, self.edit_button, self.more_button, self.enable_button, self.disable_button):
            widget.configure(state=state)

    def stop(self):
        if self.running:
            self.clear_add_mode()
            self.worker.stop_event.set()
            if hasattr(self.worker,'wake'):self.worker.wake.set()
            self.start_button.configure(state='disabled')
            self.status.set('正在停止共享…')

    def copy_logs(self):
        self.root.clipboard_clear()
        self.root.clipboard_append('\n'.join(self.log_lines))
        self.notice.set('本次运行记录已复制。')

    def log(self, value):
        self.append_logs([value])

    def append_logs(self, values):
        if not values:return
        lines=[time.strftime('%H:%M:%S  ')+value for value in values]
        self.log_lines.extend(lines)
        overflow=max(0,len(self.log_lines)-400)
        if overflow:self.log_lines=self.log_lines[-400:]
        self.logs.configure(state='normal')
        self.logs.insert('end','\n'.join(lines)+'\n')
        if overflow:self.logs.delete('1.0',f'{overflow+1}.0')
        self.logs.see('end')
        self.logs.configure(state='disabled')

    def pump(self):
        pending_logs=[]
        received_event=False
        while True:
            try: kind, value = self.events.get_nowait()
            except queue.Empty: break
            received_event=True
            if kind=='log': pending_logs.append(value)
            elif kind=='update_checked':
                old_version=self.update_info['version'] if self.update_info else None
                self.update_info=value
                if not value or value['version']!=old_version:self.update_path=None
                self.update_button.configure(text='有更新 '+value['version'] if value else '检查更新')
                self.update_message='发现新版本 '+value['version'] if value else '当前已是最新版本。'
                if value:self.notice.set('发现新版本 '+value['version']+'，可点击右上角查看更新。')
                self.render_update_dialog()
                self.update_manual=False
            elif kind=='update_progress':
                if self.update_info:
                    percent=min(100,value/self.update_info['size']*100)
                    self.update_message=f'正在下载… {percent:.0f}%'
                    if self.update_dialog and self.update_dialog.winfo_exists():
                        self.update_bar['value']=percent;self.update_status.set(self.update_message)
            elif kind=='update_ready':
                self.update_downloading=False
                self.update_path=value;self.update_message='下载完成，文件校验通过。可以安装并重启。'
                self.update_button.configure(text='更新已就绪')
                self.notice.set('更新已下载，可点击右上角安装。')
                self.render_update_dialog()
                if self.update_dialog and self.update_dialog.winfo_exists():self.update_action.configure(text='安装并重启',state='normal')
            elif kind=='update_cancelled':
                self.update_downloading=False
                self.update_message='下载已取消。';self.render_update_dialog()
            elif kind=='update_error':
                self.update_downloading=False
                self.update_button.configure(text='检查更新')
                self.update_message='更新未完成：'+value
                if self.update_manual or (self.update_dialog and self.update_dialog.winfo_exists()):self.render_update_dialog()
                self.update_manual=False
            elif kind=='group_enrolled':
                self.config=value['config']
                self.accept_inventory(value['avatars'])
                self.render_groups()
                if self.nav_mode=='group' and self.group():self.select_group(self.current_group)
                self.notice.set('已将“'+value['avatars'][value['avatar']]['name']+'”加入分组，正在同步已有共享设置。')
            elif kind=='enrollment_status':self.notice.set(value)
            elif kind=='backup_saved':
                self.result_text.set('启动前备份已保存，正在准备共享。')
                self.notice.set('已保存启动前自动备份 · 可在参数快照中查看')
            elif kind=='startup_saved':
                self.notice.set(f'已将当前游戏的 {value} 项参数保存为最新共享记录')
            elif kind=='result':
                self.last_result=value
                self.result_text.set(f"已确认 {value['confirmed']} 项    跳过 {value['skipped']} 项    未确认 {value['failed']} 项")
            elif kind=='diagnostics':
                self.runtime_metrics=value
                self.render_diagnostics()
            elif kind=='inventory':
                self.accept_inventory(value['avatars'])
                if value.get('manual'):self.reconcile_parameters()
            elif kind=='discovery_error':self.notice.set('本地模型扫描未完成：'+value)
            elif kind=='snapshot_saved':
                self.show_snapshots(value)
                self.notice.set('当前参数表已保存到软件的参数快照中。')
            elif kind=='snapshot_error':
                self.notice.set('参数表未保存：'+value)
                messagebox.showerror('无法保存参数表',value,parent=self.root)
            elif kind=='snapshot_finished':
                self.capture_button.configure(state='normal',text='保存快照')
            elif kind=='error':
                self.runtime_error=value
                self.status.set('连接已停止 · ' + value)
                self.result_text.set(value)
                self.notice.set('请查看“运行记录”了解原因。')
            elif kind=='stopped':
                self.clear_add_mode()
                self.status.set('共享未完成，请检查运行记录' if self.runtime_error else '已停止共享')
                self.start_button.configure(text='开始共享', state='normal' if self.config['groups'] else 'disabled')
                self.set_edit_controls(True)
            elif kind=='status': self.status.set(value)
            elif kind=='live' and time.monotonic() - self.snapshot_stamp > .5:
                self.snapshot_stamp = time.monotonic()
                try:
                    state=value.get('state')
                    if state is None:state=backend.read_json(self.data_dir/'state.json',{})
                    if state!=self.state_cache:
                        self.state_cache=state
                        self.paint_rows()
                except (ValueError, OSError): pass
        self.append_logs(pending_logs)
        if not self.closing: self.pump_id = self.root.after(150 if received_event else 750, self.pump)

    def close(self):
        self.exit_requested=True
        if self.auto_update_id:self.root.after_cancel(self.auto_update_id);self.auto_update_id=None
        if self.update_check:self.update_check.stop_event.set()
        if self.update_download and self.update_download.is_alive():
            self.update_download.stop_event.set()
            self.root.after(150,self.close)
            return
        if self.monitor:self.monitor.stop_event.set()
        if self.capture_worker and self.capture_worker.is_alive():
            self.capture_worker.stop_event.set()
            self.root.after(150, self.close)
            return
        if self.running:
            self.stop()
            self.root.after(150, self.close)
        else:
            self.closing = True
            self.root.after_cancel(self.chrome_id)
            self.root.after_cancel(self.pump_id)
            self.root.destroy()
