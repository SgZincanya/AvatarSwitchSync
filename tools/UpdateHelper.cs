using System;
using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows.Forms;

class UpdateHelper {
    static string Quote(string value) {
        if (value.Contains("\"")) throw new ArgumentException("Invalid path");
        return "\"" + value + "\"";
    }
    static void Verify(string file, string expected) {
        using (var input = new FileStream(file, FileMode.Open, FileAccess.Read, FileShare.Read))
        using (var sha = SHA256.Create()) {
            string actual = BitConverter.ToString(sha.ComputeHash(input)).Replace("-", "").ToLowerInvariant();
            if (!String.Equals(actual, expected, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("安装程序校验失败，未执行更新。");
        }
    }
    [STAThread]
    static int Main(string[] args) {
        string result = args.Length >= 7 ? args[6] : null;
        bool quiet = args.Length > 8 && args[8] == "quiet";
        try {
            if (args.Length < 8) throw new ArgumentException("更新参数不完整。");
            string installer = Path.GetFullPath(args[1]), appDir = Path.GetFullPath(args[3]), app = Path.GetFullPath(args[4]);
            if (!Regex.IsMatch(Path.GetFileName(installer), @"^AvatarSwitchSync-\d+\.\d+\.\d+-Setup\.exe$") || !Regex.IsMatch(args[2], @"^[a-fA-F0-9]{64}$")) throw new ArgumentException("更新文件无效。");
            if (!String.Equals(Path.GetDirectoryName(app), appDir, StringComparison.OrdinalIgnoreCase) || Path.GetFileName(app) != "AvatarSwitchSync.exe") throw new ArgumentException("安装位置无效。");
            Verify(installer, args[2]);
            Process parent = null;
            try { parent = Process.GetProcessById(Int32.Parse(args[0])); } catch (ArgumentException) {}
            if (parent != null) using (parent) { if (!parent.WaitForExit(60000)) throw new IOException("软件尚未退出，请停止共享后重新更新。"); }
            using (var input = new FileStream(installer, FileMode.Open, FileAccess.Read, FileShare.Read)) {
                Verify(installer, args[2]);
                var setup = new ProcessStartInfo(installer, "/SP- /SILENT /NORESTART /DIR=" + Quote(appDir) + " /LOG=" + Quote(args[7]));
                setup.UseShellExecute = false;
                using (var child = Process.Start(setup)) {
                    child.WaitForExit();
                    if (child.ExitCode != 0) throw new IOException("安装未完成（代码 " + child.ExitCode + "），原设置已保留。");
                }
            }
            File.WriteAllText(result, "ok", Encoding.UTF8);
            var restart = new ProcessStartInfo(app, args[5] == "1" ? "--start-sharing" : "");
            restart.WorkingDirectory = appDir; restart.UseShellExecute = false;
            Process.Start(restart);
            return 0;
        } catch (Exception error) {
            if (result != null) try { File.WriteAllText(result, "error: " + error.Message, Encoding.UTF8); } catch {}
            if (!quiet) MessageBox.Show(error.Message + "\n可重新打开软件，或从 GitHub 手动下载安装。", "更新未完成", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return 1;
        }
    }
}
