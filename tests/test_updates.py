from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
import updates as u
from desktop_ui import App
from avatar_sync import write_json
from test_desktop import fixture,fake_inventory


def release(payload=b'fixture installer'):
    return {'tag_name':'v0.9.0','draft':False,'prerelease':False,'body':'修复与改进',
            'assets':[{'name':'AvatarSwitchSync-0.9.0-Setup.exe','state':'uploaded','size':len(payload),
                       'digest':'sha256:'+hashlib.sha256(payload).hexdigest(),
                       'browser_download_url':'https://github.com/'+u.REPOSITORY+'/releases/download/v0.9.0/AvatarSwitchSync-0.9.0-Setup.exe'}]}


class UpdateTests(unittest.TestCase):
    def test_compare_numeric_versions_and_skip_old_or_preview(self):
        self.assertGreater(u.version_tuple('v0.10.0'),u.version_tuple('0.9.0'))
        self.assertIsNone(u.parse_release(release(),'0.9.0'))
        item=release();item['prerelease']=True
        self.assertIsNone(u.parse_release(item,'0.8.0'))

    def test_valid_release_selects_exact_installer(self):
        info=u.parse_release(release(),'0.8.0')
        self.assertEqual(info['name'],'AvatarSwitchSync-0.9.0-Setup.exe')
        self.assertEqual(info['notes'],'修复与改进')

    def test_missing_digest_or_installer_is_rejected(self):
        item=release();item['assets'][0]['digest']=None
        with self.assertRaises(ValueError):u.parse_release(item,'0.8.0')
        item['assets']=[]
        with self.assertRaises(ValueError):u.parse_release(item,'0.8.0')

    def test_wrong_repository_or_http_download_is_rejected(self):
        item=release();item['assets'][0]['browser_download_url']='https://github.com/another/repo/releases/download/v0.9.0/AvatarSwitchSync-0.9.0-Setup.exe'
        with self.assertRaises(ValueError):u.parse_release(item,'0.8.0')
        for url in ('http://github.com/x','https://github.com.evil.example/x','https://name:secret@github.com/x','https://github.com:8080/x'):
            with self.assertRaises(ValueError):u.trusted_url(url)

    def test_download_is_committed_only_after_size_and_hash_verification(self):
        payload=b'fixture installer';info=u.parse_release(release(payload),'0.8.0')
        def fetch(url,limit,sink,stop,progress):sink(payload[:5]);sink(payload[5:]);progress(len(payload))
        with tempfile.TemporaryDirectory() as tmp:
            result=u.download(info,tmp,threading.Event(),lambda _:None,fetch=fetch)
            self.assertEqual(result.read_bytes(),payload)
            self.assertEqual(list(result.parent.glob('*.part')),[])

    def test_failed_checksum_keeps_prior_file_and_removes_partial(self):
        info=u.parse_release(release(),'0.8.0')
        def fetch(url,limit,sink,stop,progress):sink(b'x'*info['size'])
        with tempfile.TemporaryDirectory() as tmp:
            old=Path(tmp)/'updates'/info['version']/info['name'];old.parent.mkdir(parents=True);old.write_bytes(b'prior valid file')
            with self.assertRaises(ValueError):u.download(info,tmp,threading.Event(),lambda _:None,fetch=fetch)
            self.assertEqual(old.read_bytes(),b'prior valid file')
            self.assertEqual(list(old.parent.glob('*.part')),[])

    def test_cancellation_does_not_leave_installable_file(self):
        payload=b'fixture installer';info=u.parse_release(release(payload),'0.8.0');stop=threading.Event()
        def fetch(url,limit,sink,stop,progress):sink(payload);stop.set()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(u.UpdateCancelled):u.download(info,tmp,stop,lambda _:None,fetch=fetch)
            self.assertEqual(list(Path(tmp).rglob('*.exe')),[])
            self.assertEqual(list(Path(tmp).rglob('*.part')),[])

    def test_oversize_payload_is_rejected_before_commit(self):
        info=u.parse_release(release(),'0.8.0')
        def fetch(url,limit,sink,stop,progress):sink(b'x'*(limit+1))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):u.download(info,tmp,threading.Event(),lambda _:None,fetch=fetch)
            self.assertEqual(list(Path(tmp).rglob('*.exe')),[])

    def test_launcher_validates_installer_and_copies_helper_outside_install_dir(self):
        payload=b'fixture installer';info=u.parse_release(release(payload),'0.8.0')
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)/'app';base.mkdir();(base/'AvatarSwitchSync.exe').touch();(base/'UpdateHelper.exe').write_bytes(b'helper')
            setup=Path(tmp)/info['name'];setup.write_bytes(payload)
            calls=[]
            with patch.object(sys,'frozen',True,create=True):
                u.start_install(setup,info,Path(tmp)/'data',base,True,parent_pid=123,popen=lambda *args,**kw:calls.append((args,kw)))
            args=calls[0][0][0]
            self.assertNotEqual(Path(args[0]).parent,base)
            self.assertEqual(args[1],'123');self.assertEqual(args[6],'1')
            setup.write_bytes(b'wrong')
            with patch.object(sys,'frozen',True,create=True):
                with self.assertRaises(ValueError):u.start_install(setup,info,tmp,base,False,popen=lambda *a,**k:self.fail('must not launch'))


class UpdateUiTests(unittest.TestCase):
    def test_check_download_ready_and_install_failure_are_non_destructive(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp);write_json(data/'config.json',fixture())
            root=tk.Tk();root.withdraw();app=App(root,data,fake_inventory())
            with patch('desktop_ui.CheckWorker') as worker:
                app.check_updates();worker.return_value.start.assert_called_once()
            info=u.parse_release(release(),'0.8.0')
            root.after_cancel(app.pump_id)
            app.events.put(('update_checked',info));app.pump()
            self.assertIn('0.9.0',app.update_status.get())
            self.assertEqual(str(app.update_action.cget('state')),'normal')
            root.after_cancel(app.pump_id)
            app.update_downloading=True;app.events.put(('update_error','fixture network failure'));app.pump()
            self.assertFalse(app.update_downloading)
            self.assertEqual(str(app.update_action.cget('state')),'normal')
            root.after_cancel(app.pump_id)
            app.events.put(('update_ready',str(data/'fixture.exe')));app.pump()
            self.assertEqual(app.update_action.cget('text'),'安装并重启')
            with patch('desktop_ui.start_install',side_effect=OSError('fixture missing helper')):app.update_action_clicked()
            self.assertFalse(app.closing);self.assertFalse(app.exit_requested)
            self.assertIn('missing helper',app.update_status.get())
            app.update_dialog.destroy();app.close()


class UpdateHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler=Path(os.environ.get('WINDIR','C:/Windows'))/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        if not cls.compiler.exists():raise unittest.SkipTest('C# compiler unavailable')
        cls.temp=tempfile.TemporaryDirectory();cls.base=Path(cls.temp.name)
        cls.helper=cls.base/'UpdateHelper.exe'
        subprocess.run([str(cls.compiler),'/nologo','/target:winexe','/reference:System.Windows.Forms.dll','/out:'+str(cls.helper),str(Path(__file__).parents[1]/'tools/UpdateHelper.cs')],check=True,capture_output=True)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def simulate(self,corrupt=False,installer_exit=0):
        directory=self.base/('case-'+str(time.monotonic_ns()));directory.mkdir()
        target=directory/'app';target.mkdir()
        setup=directory/'AvatarSwitchSync-0.9.0-Setup.exe';app=target/'AvatarSwitchSync.exe'
        setup_marker=directory/'setup.txt';app_marker=directory/'restart.txt';result=directory/'result.txt'
        for filename,output,marker,exitcode in [('setup.cs',setup,setup_marker,installer_exit),('app.cs',app,app_marker,0)]:
            code='using System.IO; class Fixture { static int Main(string[] args) { File.WriteAllText(@"'+str(marker).replace('"','""')+'",string.Join("\\n",args)); return '+str(exitcode)+'; } }'
            source=directory/filename;source.write_text(code)
            subprocess.run([str(self.compiler),'/nologo','/target:winexe','/out:'+str(output),str(source)],check=True,capture_output=True)
        digest='0'*64 if corrupt else hashlib.sha256(setup.read_bytes()).hexdigest()
        parent=subprocess.Popen([sys.executable,'-c','import time;time.sleep(1.2)'])
        started=time.monotonic()
        helper=subprocess.run([str(self.helper),str(parent.pid),str(setup),digest,str(target),str(app),'1',str(result),str(directory/'install.log'),'quiet'],timeout=30)
        elapsed=time.monotonic()-started;parent.wait(timeout=5)
        for _ in range(40):
            if app_marker.exists() or helper.returncode:break
            time.sleep(.05)
        return helper.returncode,elapsed,result,setup_marker,app_marker

    def test_helper_waits_for_exit_installs_to_same_folder_and_resumes_by_restore(self):
        code,elapsed,result,setup,app=self.simulate()
        self.assertEqual(code,0);self.assertGreater(elapsed,1.)
        self.assertEqual(result.read_text(encoding='utf-8-sig'),'ok')
        self.assertIn('/NORESTART',setup.read_text())
        self.assertIn('/DIR=',setup.read_text())
        self.assertEqual(app.read_text(),'--start-sharing')

    def test_helper_rejects_corrupt_installer_without_execution(self):
        code,_,result,setup,app=self.simulate(corrupt=True)
        self.assertNotEqual(code,0);self.assertFalse(setup.exists());self.assertFalse(app.exists())
        self.assertIn('error:',result.read_text(encoding='utf-8-sig'))

    def test_helper_does_not_report_failed_installer_as_success(self):
        code,_,result,setup,app=self.simulate(installer_exit=9)
        self.assertNotEqual(code,0);self.assertTrue(setup.exists());self.assertFalse(app.exists())
        self.assertIn('9',result.read_text(encoding='utf-8-sig'))


if __name__=='__main__':unittest.main()
