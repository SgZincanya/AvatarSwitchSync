"""Generate Windows version metadata from src/config_store.py's VERSION."""
from pathlib import Path
import sys
root=Path(__file__).parents[1]
sys.path.insert(0,str(root/'src'))
from config_store import VERSION
parts=tuple(int(p) for p in VERSION.split('.'))
assert 1<=len(parts)<=4 and all(0<=p<=65535 for p in parts)
parts=parts+(0,)*(4-len(parts))
target=Path(sys.argv[1])
target.parent.mkdir(parents=True,exist_ok=True)
target.write_text(f'''VSVersionInfo(
 ffi=FixedFileInfo(filevers={parts},prodvers={parts},mask=0x3f,flags=0x0,OS=0x40004,fileType=0x1,subtype=0x0,date=(0,0)),
 kids=[StringFileInfo([StringTable('040904B0',[
 StringStruct('FileDescription','Avatar Switch Sync'),
 StringStruct('FileVersion','{VERSION}'),
 StringStruct('ProductName','Avatar Switch Sync'),
 StringStruct('ProductVersion','{VERSION}'),
 StringStruct('OriginalFilename','AvatarSwitchSync.exe')])]),
 VarFileInfo([VarStruct('Translation',[1033,1200])])])
''',encoding='utf-8')
print(VERSION)
