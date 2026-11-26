// A small per-user launcher. No SteamVR, WMI service, PowerShell or game injection.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Threading;

class VRChatLauncher {
    static string StopName = @"Local\AvatarSwitchSync.VRChatLauncher.Stop";
    static string MutexName = @"Local\AvatarSwitchSync.VRChatLauncher";
    static string GameName = "VRChat";
    static int Interval = 3000;

    static void Log(string value) {
        try {
            string dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "AvatarSwitchSync");
#if TESTING
            dir = AppDomain.CurrentDomain.BaseDirectory;
#endif
            Directory.CreateDirectory(dir);
            File.WriteAllText(Path.Combine(dir, "vrchat-launcher-status.txt"), DateTime.Now.ToString("s") + " " + value);
        } catch {}
    }

    static int Stop() {
        try { using (var stop = EventWaitHandle.OpenExisting(StopName)) stop.Set(); }
        catch (WaitHandleCannotBeOpenedException) { return 0; }
        try {
            using (var mutex = Mutex.OpenExisting(MutexName)) {
                try { if (!mutex.WaitOne(8000)) return 1; }
                catch (AbandonedMutexException) {}
                mutex.ReleaseMutex();
            }
        } catch (WaitHandleCannotBeOpenedException) {}
        return 0;
    }

    [STAThread]
    static int Main(string[] args) {
#if TESTING
        string suffix = Path.GetFileName(AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar));
        StopName += suffix; MutexName += suffix; GameName = "AVSTestGame"; Interval = 100;
#endif
        if (args.Length == 1 && args[0] == "--stop") return Stop();
        bool created;
        using (var mutex = new Mutex(true, MutexName, out created)) {
            if (!created) return 0;
            try {
                using (var stop = new EventWaitHandle(false, EventResetMode.ManualReset, StopName)) {
                    string app = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "AvatarSwitchSync.exe");
                    if (!File.Exists(app)) { Log("error: application missing"); return 1; }
                    var handled = new HashSet<int>();
                    int session = Process.GetCurrentProcess().SessionId;
                    Log("waiting for VRChat");
                    do {
                        var present = new HashSet<int>();
                        try {
                            foreach (var game in Process.GetProcessesByName(GameName)) using (game) {
                                try {
                                    if (game.SessionId != session || game.HasExited) continue;
                                    present.Add(game.Id);
                                    if (handled.Contains(game.Id)) continue;
                                    var start = new ProcessStartInfo(app, "--start-sharing");
                                    start.WorkingDirectory = Path.GetDirectoryName(app);
                                    start.UseShellExecute = false;
                                    using (var launched = Process.Start(start)) {}
                                    handled.Add(game.Id);
                                    Log("VRChat detected; requested saved-state sharing");
                                } catch (Exception error) { Log("error: " + error.Message); }
                            }
                            handled.IntersectWith(present);
                        } catch (Exception error) { Log("error: " + error.Message); }
                    } while (!stop.WaitOne(Interval));
                    Log("stopped");
                }
            } finally { mutex.ReleaseMutex(); }
        }
        return 0;
    }
}
