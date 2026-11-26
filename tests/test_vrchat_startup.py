from pathlib import Path
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, Mock
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
import vrchat_startup as s


class RegistrationTests(unittest.TestCase):
    def test_path_with_spaces_and_chinese_is_preserved(self):
        with tempfile.TemporaryDirectory(prefix='启动 helper ') as tmp:
            helper=Path(tmp)/'VRChatLauncher.exe';helper.touch()
            path,value=s.command(Path(tmp)/'AvatarSwitchSync.exe')
            self.assertEqual(path,str(helper.resolve()))
            self.assertEqual(value,subprocess.list2cmdline([path]))

    def test_enable_stops_old_helper_then_registers_and_launches(self):
        with patch.object(s,'command',return_value=('helper.exe','helper command')), patch.object(s,'registered_command',return_value='old'), patch.object(s,'stop_helper') as stop, patch.object(s,'set_registration') as put, patch.object(s.subprocess,'Popen') as launch:
            result=s.configure('app.exe',True)
            self.assertTrue(result['enabled']);stop.assert_called_once_with('helper.exe')
            put.assert_called_once_with('helper command');launch.assert_called_once()

    def test_disable_stops_helper_and_removes_only_own_run_value(self):
        with patch.object(s,'command',return_value=('helper.exe','helper command')), patch.object(s,'registered_command',return_value='old'), patch.object(s,'stop_helper') as stop, patch.object(s,'set_registration') as put, patch.object(s.subprocess,'Popen') as launch:
            self.assertFalse(s.configure('app.exe',False)['enabled'])
            stop.assert_called_once();put.assert_called_once_with('');launch.assert_not_called()

    def test_launch_failure_restores_previous_registration(self):
        with patch.object(s,'command',return_value=('helper.exe','new')), patch.object(s,'registered_command',return_value='old'), patch.object(s,'stop_helper'), patch.object(s,'set_registration') as put, patch.object(s.subprocess,'Popen',side_effect=[OSError('failure'),Mock()]):
            with self.assertRaises(OSError):s.configure('app.exe',True)
            self.assertEqual([c.args[0] for c in put.call_args_list],['new','old'])

    def test_stop_failure_does_not_change_registration(self):
        with patch.object(s,'command',return_value=('helper.exe','new')), patch.object(s,'registered_command',return_value='old'), patch.object(s,'stop_helper',side_effect=RuntimeError('busy')), patch.object(s,'set_registration') as put:
            with self.assertRaises(RuntimeError):s.configure('app.exe',False)
            put.assert_not_called()


@unittest.skipUnless(os.name=='nt','Windows launcher integration')
class LauncherIntegration(unittest.TestCase):
    def test_real_process_detection_deduplicates_and_handles_next_session(self):
        compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        with tempfile.TemporaryDirectory(prefix='avs-launcher-') as tmp:
            folder=Path(tmp);root=Path(__file__).parents[1]
            def compile_file(source,output,extra=()):
                subprocess.run([str(compiler),'/nologo','/target:winexe','/out:'+str(output),*extra,str(source)],check=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            launcher=folder/'VRChatLauncher.exe'
            compile_file(root/'tools/VRChatLauncher.cs',launcher,('/define:TESTING',))
            fake=folder/'fake.cs'
            fake.write_text('using System;using System.IO;using System.Threading;class Fake { static void Main(string[] args) { if (args.Length>0) File.AppendAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"requests.txt"),args[0]+"\\n"); else Thread.Sleep(30000); }}')
            game=folder/'AVSTestGame.exe';app=folder/'AvatarSwitchSync.exe'
            compile_file(fake,game);compile_file(fake,app)
            watcher=subprocess.Popen([str(launcher)])
            game_process=None
            try:
                time.sleep(.4)
                requests=folder/'requests.txt'
                self.assertFalse(requests.exists(),'must wait while game is absent')
                def wait_count(n):
                    deadline=time.monotonic()+6
                    while time.monotonic()<deadline:
                        if requests.exists() and len(requests.read_text().splitlines())>=n:return
                        time.sleep(.05)
                    self.fail('launcher did not detect game')
                game_process=subprocess.Popen([str(game)]);wait_count(1)
                time.sleep(.4)
                self.assertEqual(requests.read_text().splitlines(),['--start-sharing'])
                duplicate=subprocess.Popen([str(launcher)]);self.assertEqual(duplicate.wait(5),0)
                game_process.terminate();game_process.wait(5);game_process=None
                time.sleep(.3)
                game_process=subprocess.Popen([str(game)]);wait_count(2)
                self.assertEqual(requests.read_text().splitlines(),['--start-sharing','--start-sharing'])
                subprocess.run([str(launcher),'--stop'],check=True,timeout=10)
                self.assertEqual(watcher.wait(5),0)
            finally:
                if game_process and game_process.poll() is None:game_process.terminate();game_process.wait(5)
                if watcher.poll() is None:subprocess.run([str(launcher),'--stop'],timeout=10);watcher.wait(5)
