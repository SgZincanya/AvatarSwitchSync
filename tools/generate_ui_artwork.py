"""Build antialiased artwork once; Pillow is not needed by the shipped app."""
from pathlib import Path
import base64
import io
import sys
from PIL import Image,ImageDraw
source=Path(__file__).parents[1]/'src'
sys.path.insert(0,str(source))
from ui_theme import LIGHT,DARK
S=4

def encode(im):
    out=io.BytesIO();im.resize((im.width//S,im.height//S),Image.Resampling.LANCZOS).save(out,format='PNG')
    return base64.b64encode(out.getvalue()).decode()

def rounded(fill,border=None,size=24,radius=7,outside=None):
    im=Image.new('RGBA',(size*S,size*S),outside or (0,0,0,0));d=ImageDraw.Draw(im)
    d.rounded_rectangle((S//2,S//2,size*S-S//2-1,size*S-S//2-1),radius*S,fill=fill,outline=border,width=S if border else 1)
    return encode(im)

def glyph(name,color):
    im=Image.new('RGBA',(24*S,24*S));d=ImageDraw.Draw(im)
    def line(points,w=1.7):d.line([(int(x*S),int(y*S)) for x,y in points],fill=color,width=round(w*S),joint='curve')
    def rect(box,r=2):d.rounded_rectangle(tuple(int(x*S) for x in box),r*S,outline=color,width=round(1.6*S))
    if name=='models':
        for x,y in [(4,4),(14,4),(4,14),(14,14)]:rect((x,y,x+6,y+6),1)
    elif name=='snapshots':
        rect((6,4,20,17));line([(3,8),(3,21),(16,21)])
    elif name=='diagnostics':
        line([(3,18),(3,6)]);line([(3,18),(21,18)]);line([(6,14),(10,10),(14,13),(20,5)],2)
    elif name=='chevron':line([(7,10),(12,15),(17,10)])
    elif name=='signal':
        d.ellipse((6*S,6*S,18*S,18*S),fill=color)
        d.ellipse((3*S,3*S,21*S,21*S),outline=color,width=S)
    return encode(im)

art={}
for c in (LIGHT,DARK):
    a={};art[c['mode']]=a
    for key,fill,hover,border in [('button',c['panel'],c['subtle'],c['line']),('primary',c['button'],c['hover'],None),
                                 ('quiet',c['bg'],c['side'],None),('nav',c['side'],c['line'],None),
                                 ('nav_selected',c['selected'],c['selected'],None),('side_action',c['panel'],c['subtle'],c['line'])]:
        outside=c['side'] if key in ('primary','nav','nav_selected','side_action') else c['bg'] if key=='quiet' else c['panel']
        a[key]=rounded(fill,border,outside=outside)
        a[key+'_hover']=rounded(hover,border,outside=outside)
        a[key+'_focus']=rounded(fill,c['accent'],outside=outside)
        a[key+'_disabled']=rounded(c['subtle'],outside=outside)
    a['field']=rounded(c['panel'],c['line'],outside=c['panel']);a['field_focus']=rounded(c['panel'],c['accent'],outside=c['panel']);a['field_disabled']=rounded(c['subtle'],c['line'],outside=c['panel'])
    a['tab']=rounded(c['bg'],outside=c['bg']);a['tab_selected']=rounded(c['panel'],c['line'],outside=c['bg']);a['tab_hover']=rounded(c['side'],outside=c['bg']);a['tab_focus']=rounded(c['panel'],c['accent'],outside=c['bg'])
    a['scroll']=rounded(c['line'],size=10,radius=5);a['scroll_hover']=rounded(c['muted'],size=10,radius=5)
    for name in ('models','snapshots','diagnostics','chevron','signal'):
        a[name]=glyph(name,c['muted']);a[name+'_active']=glyph(name,c['accent'])
    a['signal_good']=glyph('signal',c['good'])
(source/'ui_artwork.py').write_text('"""Generated, antialiased UI resources. No runtime image dependency."""\nARTWORK = '+repr(art)+'\n',encoding='utf-8')
print('Built artwork:',sum(len(v) for v in art.values()),'images')
