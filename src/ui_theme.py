"""Desktop visual system; native ttk controls retain keyboard and focus behavior."""
import tkinter as tk
from tkinter import ttk

LIGHT = dict(mode='light',bg='#F6F7F9',panel='#FFFFFF',side='#ECEEF2',text='#202126',muted='#606572',
             line='#E0E3E9',accent='#005FCE',button='#0065D9',hover='#0054BB',selected='#DCE8FA',
             good='#247448',subtle='#F4F5F8',stripe='#F8F9FB')
DARK = dict(mode='dark',bg='#1B1C20',panel='#25262C',side='#202127',text='#F0F1F5',muted='#B0B4C1',
            line='#40424C',accent='#9DC5FF',button='#0065D9',hover='#0054BB',selected='#303F59',
            good='#7FD7A3',subtle='#2D2F36',stripe='#292B31')


def apply_theme(root,c):
    from ui_artwork import ARTWORK
    images={name:tk.PhotoImage(master=root,data=data) for name,data in ARTWORK[c['mode']].items()}
    s=ttk.Style(root);s.theme_use('clam')
    font=('Microsoft YaHei UI',10)
    s.configure('.',font=font,background=c['bg'],foreground=c['text'],bordercolor=c['line'])
    for prefix,bg in [('',c['bg']),('Panel.',c['panel']),('Side.',c['side'])]:
        s.configure(prefix+'TFrame',background=bg)
        s.configure(prefix+'TLabel',background=bg,foreground=c['text'])
        s.configure(prefix.replace('.','')+'Muted.TLabel',background=bg,foreground=c['muted'])
    s.configure('Title.TLabel',font=('Microsoft YaHei UI',21,'bold'))
    s.configure('Section.TLabel',font=('Microsoft YaHei UI',12,'bold'))
    for name,key,fg in [('TButton','button',c['text']),('Primary.TButton','primary','#FFFFFF'),
                        ('Quiet.TButton','quiet',c['muted']),('Nav.TButton','nav',c['text']),
                        ('NavSelected.TButton','nav_selected',c['accent']),('SideAction.TButton','side_action',c['text']),
                        ('Menu.TButton','nav',c['text'])]:
        element='AS'+name
        s.element_create(element,'image',images[key],('disabled',images[key+'_disabled']),
                         ('pressed',images[key+'_hover']),('focus',images[key+'_focus']),
                         ('active',images[key+'_hover']),border=8,sticky='nsew')
        s.layout(name,[(element,{'sticky':'nsew','children':[('Button.padding',{'sticky':'nsew','children':[('Button.label',{'sticky':'nsew'})]})]})])
        s.configure(name,padding=(13,5),font=font,foreground=fg,anchor='center',borderwidth=0)
        s.map(name,foreground=[('disabled',c['muted']),('!disabled',fg)])
    for name in ('Nav.TButton','NavSelected.TButton'):s.configure(name,anchor='w',padding=(13,8))
    s.configure('Primary.TButton',padding=(14,9))
    s.configure('Menu.TButton',padding=(9,3))
    s.element_create('ASentry','image',images['field'],('disabled',images['field_disabled']),('focus',images['field_focus']),border=10,sticky='nsew')
    s.layout('TEntry',[('ASentry',{'sticky':'nsew','children':[('Entry.padding',{'sticky':'nsew','children':[('Entry.textarea',{'sticky':'nsew'})]})]})])
    s.configure('TEntry',padding=(11,6),fieldbackground=c['panel'],insertcolor=c['text'],foreground=c['text'],borderwidth=0)
    s.element_create('ASchevron','image',images['chevron'],sticky='')
    s.layout('TCombobox',[('ASentry',{'sticky':'nsew','children':[('ASchevron',{'side':'right','sticky':'ns'}),('Combobox.padding',{'sticky':'nsew','children':[('Combobox.textarea',{'sticky':'nsew'})]})]})])
    s.configure('TCombobox',padding=(10,6),arrowsize=20,foreground=c['text'],fieldbackground=c['panel'],borderwidth=0)
    s.map('TCombobox',fieldbackground=[('readonly',c['panel'])],selectbackground=[('readonly',c['panel'])],selectforeground=[('readonly',c['text'])])
    root.option_add('*TCombobox*Listbox.font',font)
    root.option_add('*TCombobox*Listbox.background',c['panel'])
    root.option_add('*TCombobox*Listbox.foreground',c['text'])
    s.configure('Treeview',font=('Segoe UI',10),rowheight=38,background=c['panel'],fieldbackground=c['panel'],foreground=c['text'],borderwidth=0,relief='flat')
    s.layout('Treeview',[('Treeview.treearea',{'sticky':'nsew'})])
    s.map('Treeview',background=[('selected',c['selected'])],foreground=[('selected',c['text'])])
    s.configure('Treeview.Heading',background=c['subtle'],foreground=c['muted'],font=font,padding=(10,10),borderwidth=0,relief='flat')
    s.layout('Treeview.Heading',[('Treeheading.cell',{'sticky':'nsew'}),('Treeheading.padding',{'sticky':'nsew','children':[('Treeheading.image',{'side':'right','sticky':''}),('Treeheading.text',{'sticky':'we'})]})])
    s.map('Treeview.Heading',background=[('active',c['selected'])])
    s.configure('TNotebook',background=c['bg'],borderwidth=0,tabmargins=(0,0,0,4))
    s.element_create('ASclient','image',images['tab'],border=0,sticky='nsew')
    s.layout('TNotebook',[('ASclient',{'sticky':'nswe'})])
    s.element_create('AStab','image',images['tab'],('selected','focus',images['tab_focus']),('selected',images['tab_selected']),('active',images['tab_hover']),border=10,sticky='nsew')
    s.layout('TNotebook.Tab',[('AStab',{'sticky':'nsew','children':[('Notebook.padding',{'sticky':'nsew','children':[('Notebook.label',{'sticky':'nsew'})]})]})])
    s.configure('TNotebook.Tab',padding=(17,6),foreground=c['muted'],font=font)
    s.map('TNotebook.Tab',foreground=[('selected',c['text'])])
    for orient in ('Vertical','Horizontal'):
        s.element_create('AS'+orient+'thumb','image',images['scroll'],('active',images['scroll_hover']),border=4,sticky='nsew')
        direction='ns' if orient=='Vertical' else 'we'
        s.layout(orient+'.TScrollbar',[(orient+'.Scrollbar.trough',{'sticky':direction,'children':[('AS'+orient+'thumb',{'expand':'1','sticky':'nsew'})]})])
        s.configure(orient+'.TScrollbar',width=10,arrowsize=0,background=c['panel'],troughcolor=c['panel'],borderwidth=0)
    return images


def apply_native_chrome(root,c):
    """Use the native Windows caption and buttons, with the app's surface color."""
    import ctypes
    import os
    if os.name!='nt':return
    try:
        user=ctypes.WinDLL('user32')
        user.GetAncestor.argtypes=[ctypes.c_void_p,ctypes.c_uint]
        user.GetAncestor.restype=ctypes.c_void_p
        hwnd=user.GetAncestor(root.winfo_id(),2)
        dwm=ctypes.WinDLL('dwmapi')
        dwm.DwmSetWindowAttribute.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_void_p,ctypes.c_uint]
        for attribute,key in ((35,'side'),(36,'text')):
            rgb=c[key].lstrip('#')
            value=ctypes.c_uint32(int(rgb[0:2],16)|(int(rgb[2:4],16)<<8)|(int(rgb[4:6],16)<<16))
            dwm.DwmSetWindowAttribute(hwnd,attribute,ctypes.byref(value),ctypes.sizeof(value))
    except (OSError,AttributeError,tk.TclError):pass
