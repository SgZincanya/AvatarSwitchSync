"""Public GitHub releases, Windows-native HTTPS, verified installer downloads."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit,urljoin
import uuid

REPOSITORY='SgZincanya/AvatarSwitchSync'
RELEASES_URL='https://github.com/'+REPOSITORY+'/releases'
LATEST_URL='https://raw.githubusercontent.com/'+REPOSITORY+'/main/update.json'
MAX_INSTALLER=200*1024*1024
ALLOWED_HOSTS={'api.github.com','github.com','raw.githubusercontent.com','objects.githubusercontent.com','release-assets.githubusercontent.com'}


class UpdateCancelled(Exception):pass


def version_tuple(value):
    match=re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)',value or '')
    if not match:raise ValueError('版本号格式不受支持')
    return tuple(map(int,match.groups()))


def trusted_url(url):
    parts=urlsplit(url)
    if parts.scheme!='https' or parts.hostname not in ALLOWED_HOSTS or parts.port not in (None,443) or parts.username or parts.password:
        raise ValueError('更新地址不受支持')
    return parts


def https_get(url,limit,sink=None,stop=None,progress=None):
    """WinHTTP uses Windows certificate validation, not bundled OpenSSL files."""
    api=ctypes.WinDLL('winhttp',use_last_error=True)
    handle=ctypes.c_void_p;dword=wintypes.DWORD;pointer=ctypes.c_void_p
    signatures={
        'WinHttpOpen':([wintypes.LPCWSTR,dword,wintypes.LPCWSTR,wintypes.LPCWSTR,dword],handle),
        'WinHttpConnect':([handle,wintypes.LPCWSTR,wintypes.WORD,dword],handle),
        'WinHttpOpenRequest':([handle,wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.LPCWSTR,pointer,dword],handle),
        'WinHttpSetTimeouts':([handle,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int],wintypes.BOOL),
        'WinHttpSetOption':([handle,dword,pointer,dword],wintypes.BOOL),
        'WinHttpSendRequest':([handle,wintypes.LPCWSTR,dword,pointer,dword,dword,ctypes.c_size_t],wintypes.BOOL),
        'WinHttpReceiveResponse':([handle,pointer],wintypes.BOOL),
        'WinHttpQueryHeaders':([handle,dword,wintypes.LPCWSTR,pointer,ctypes.POINTER(dword),ctypes.POINTER(dword)],wintypes.BOOL),
        'WinHttpReadData':([handle,pointer,dword,ctypes.POINTER(dword)],wintypes.BOOL),
        'WinHttpCloseHandle':([handle],wintypes.BOOL)}
    for name,(args,result) in signatures.items():
        fn=getattr(api,name);fn.argtypes=args;fn.restype=result
    def require(value):
        if not value:raise ctypes.WinError(ctypes.get_last_error())
        return value
    def header(request,index):
        buffer=ctypes.create_unicode_buffer(8192);size=dword(ctypes.sizeof(buffer))
        if not api.WinHttpQueryHeaders(request,index,None,buffer,ctypes.byref(size),None):return ''
        return buffer.value
    session=require(api.WinHttpOpen('AvatarSwitchSync-Updater',4,None,None,0))
    try:
        require(api.WinHttpSetTimeouts(session,10000,10000,15000,30000))
        for _ in range(6):
            if stop and stop.is_set():raise UpdateCancelled()
            parts=trusted_url(url)
            connection=require(api.WinHttpConnect(session,parts.hostname,443,0))
            request=None
            try:
                path=(parts.path or '/')+('?' + parts.query if parts.query else '')
                request=require(api.WinHttpOpenRequest(connection,'GET',path,None,None,None,0x00800000))
                disabled=dword(2)  # Handle redirects ourselves and validate every destination.
                require(api.WinHttpSetOption(request,63,ctypes.byref(disabled),ctypes.sizeof(disabled)))
                extra='Accept: application/vnd.github+json\r\n' if parts.hostname=='api.github.com' else ''
                require(api.WinHttpSendRequest(request,extra,len(extra),None,0,0,0))
                require(api.WinHttpReceiveResponse(request,None))
                status=dword();size=dword(ctypes.sizeof(status))
                require(api.WinHttpQueryHeaders(request,19|0x20000000,None,ctypes.byref(status),ctypes.byref(size),None))
                if status.value in (301,302,303,307,308):
                    destination=header(request,33)
                    if not destination:raise ValueError('更新下载重定向无效')
                    url=urljoin(url,destination);trusted_url(url)
                    continue
                if status.value!=200:raise OSError(f'GitHub 请求失败（HTTP {status.value}）')
                declared=header(request,5)
                if declared.isdigit() and int(declared)>limit:raise ValueError('更新文件大小超过限制')
                chunks=[];total=0;buffer=ctypes.create_string_buffer(65536);read=dword();last=0
                while True:
                    if stop and stop.is_set():raise UpdateCancelled()
                    require(api.WinHttpReadData(request,buffer,len(buffer),ctypes.byref(read)))
                    if not read.value:break
                    total+=read.value
                    if total>limit:raise ValueError('更新文件大小超过限制')
                    block=buffer.raw[:read.value]
                    if sink:sink(block)
                    else:chunks.append(block)
                    if progress and time.monotonic()-last>.15:
                        progress(total);last=time.monotonic()
                if progress:progress(total)
                return b''.join(chunks) if sink is None else total
            finally:
                if request:api.WinHttpCloseHandle(request)
                api.WinHttpCloseHandle(connection)
        raise ValueError('更新下载重定向次数过多')
    finally:api.WinHttpCloseHandle(session)


def parse_release(release,current):
    if not isinstance(release,dict):raise ValueError('GitHub 版本信息无效')
    if release.get('draft') or release.get('prerelease'):return None
    tag=release.get('tag_name','')
    if version_tuple(tag)<=version_tuple(current):return None
    version=tag.lstrip('v')
    name=f'AvatarSwitchSync-{version}-Setup.exe'
    asset=next((a for a in release.get('assets',[]) if a.get('name')==name and a.get('state')=='uploaded'),None)
    if not asset:raise ValueError('新版本尚未提供安装程序，请稍后重试或前往 GitHub 下载。')
    size=asset.get('size');digest=asset.get('digest','')
    if type(size) is not int or not 0<size<=MAX_INSTALLER:raise ValueError('安装程序大小无效')
    if not re.fullmatch(r'sha256:[a-fA-F0-9]{64}',digest or ''):raise ValueError('版本缺少 SHA-256 校验信息，请前往 GitHub 下载。')
    url=asset.get('browser_download_url','')
    trusted_url(url)
    expected='https://github.com/'+REPOSITORY+'/releases/download/'+tag+'/'+name
    if url!=expected:raise ValueError('安装程序来源不匹配')
    return {'version':version,'name':name,'size':size,'sha256':digest.split(':',1)[1].lower(),'url':url,
            'notes':str(release.get('body',''))[:16000],'page':RELEASES_URL+'/tag/'+tag}


class CheckWorker(threading.Thread):
    def __init__(self,current,events):
        super().__init__(daemon=True);self.current=current;self.events=events;self.stop_event=threading.Event()
    def run(self):
        try:
            raw=https_get(LATEST_URL,2*1024*1024,stop=self.stop_event)
            info=parse_release(json.loads(raw),self.current)
            self.events.put(('update_checked',info))
        except UpdateCancelled:pass
        except Exception as exc:self.events.put(('update_error',str(exc)))


def download(info,data_dir,stop,progress,fetch=https_get):
    directory=Path(data_dir)/'updates'/info['version'];directory.mkdir(parents=True,exist_ok=True)
    destination=directory/info['name']
    temporary=directory/(uuid.uuid4().hex+'.part')
    digest=hashlib.sha256();size=0
    try:
        with temporary.open('wb') as output:
            def sink(block):
                nonlocal size
                size+=len(block)
                if size>info['size']:raise ValueError('下载文件大小不匹配')
                output.write(block);digest.update(block)
            fetch(info['url'],info['size'],sink=sink,stop=stop,progress=progress)
        if stop.is_set():raise UpdateCancelled()
        if size!=info['size'] or digest.hexdigest()!=info['sha256']:raise ValueError('安装程序校验失败，未进行安装。请重试下载。')
        temporary.replace(destination)
        return destination
    finally:temporary.unlink(missing_ok=True)


class DownloadWorker(threading.Thread):
    def __init__(self,info,data_dir,events):
        super().__init__(daemon=True);self.info=info;self.data_dir=data_dir;self.events=events;self.stop_event=threading.Event()
    def run(self):
        try:
            path=download(self.info,self.data_dir,self.stop_event,lambda value:self.events.put(('update_progress',value)))
            self.events.put(('update_ready',str(path)))
        except UpdateCancelled:self.events.put(('update_cancelled',None))
        except Exception as exc:self.events.put(('update_error',str(exc)))


def start_install(installer,info,data_dir,base,resume,parent_pid=None,popen=subprocess.Popen):
    installer=Path(installer).resolve(strict=True);base=Path(base).resolve(strict=True)
    executable=base/'AvatarSwitchSync.exe';helper=base/'UpdateHelper.exe'
    if not getattr(sys,'frozen',False):raise ValueError('源码运行时请手动安装；安装版支持直接升级。')
    if installer.name!=info['name'] or installer.stat().st_size!=info['size'] or hashlib.sha256(installer.read_bytes()).hexdigest()!=info['sha256']:
        raise ValueError('安装程序校验失败，请重新下载。')
    if not helper.is_file() or not executable.is_file():raise FileNotFoundError('缺少更新助手，请从 GitHub 重新下载安装包。')
    updates=Path(data_dir).resolve()/'updates';updates.mkdir(parents=True,exist_ok=True)
    launcher=updates/('UpdateHelper-'+uuid.uuid4().hex+'.exe')
    shutil.copy2(helper,launcher)
    args=[str(launcher),str(parent_pid or os.getpid()),str(installer),info['sha256'],str(base),str(executable),
          '1' if resume else '0',str(updates/'update-result.txt'),str(updates/'update-install.log')]
    return popen(args,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
