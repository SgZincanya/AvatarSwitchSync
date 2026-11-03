from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
import steamvr_startup as s


class StartupTests(unittest.TestCase):
    def test_manifest_uses_current_install_path_and_start_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe=Path(tmp)/'名称 with spaces.exe';exe.touch()
            item=s.manifest(exe)['applications'][0]
            self.assertEqual(item['binary_path_windows'],str(exe.resolve()))
            self.assertEqual(item['arguments'],'--start-sharing')
            self.assertTrue(item['is_dashboard_overlay'])
            self.assertEqual(item['app_key'],s.APP_KEY)

    def test_real_named_event_delivers_once_without_creating_second_worker(self):
        name='Local\\AvatarSwitchSync.Test.'+uuid.uuid4().hex
        handle=s.create_event(name)
        try:
            self.assertTrue(s.request_start(name))
            root=Mock();app=Mock(closing=False,running=False)
            s.poll_start(root,app,handle)
            app.start.assert_called_once()
            app.start.assert_called_with(capture_current=False)
            s.poll_start(root,app,handle)
            app.start.assert_called_once()
        finally:s.kernel().CloseHandle(handle)

    def test_existing_running_sync_is_not_restarted(self):
        app=Mock(closing=False,running=True)
        with patch('steamvr_startup.kernel') as kernel:
            kernel.return_value.WaitForSingleObject.return_value=0
            s.poll_start(Mock(),app,1)
        app.start.assert_not_called()

    def test_closing_app_does_not_accept_start_request(self):
        app=Mock(closing=True)
        with patch('steamvr_startup.kernel') as kernel:s.poll_start(Mock(),app,1)
        kernel.assert_not_called();app.start.assert_not_called()

    def test_registration_errors_are_not_reported_as_success(self):
        apps=s.Applications();apps.call=Mock(return_value=100)
        with self.assertRaises(RuntimeError):apps.configure(Path('fixture.vrmanifest'),True)


if __name__=='__main__':unittest.main()
