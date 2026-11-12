using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using Troika.Desktop;

// The lab starts its own classic Notepad. The system launch path may redirect
// to the packaged app and restore the owner's existing tabs.
internal sealed class ComputerUseNotepad : IComputerUseEditor, IDisposable {
    internal static readonly UTF8Encoding FileEncoding = new UTF8Encoding(true, true);
    private const int MaxReadCharacters = 513;
    private const uint WmGetText = 0x000D;
    private const uint EmReplaceSel = 0x00C2;
    private const uint WmCommand = 0x0111;
    private const uint MessageFlags = 0x0023; // SMTO_BLOCK | SMTO_ABORTIFHUNG | SMTO_ERRORONEXIT
    private const uint MenuByPosition = 0x0400;
    private const uint MessageTimeoutMs = 1500;
    private const int ShowWithoutActivation = 4;
    private const uint NoZOrderOrActivation = 0x0014;

    private readonly ComputerUseSession session;
    private readonly Process process;
    private readonly string image;
    private readonly string resources;
    private readonly string title;
    private readonly IntPtr window;
    private readonly IntPtr editor;

    internal IntPtr WindowHandle { get { return window; } }
    internal int ProcessId { get { return process.Id; } }

    internal ComputerUseNotepad(ComputerUseSession session, string output, bool showForCapture = false) {
        this.session = session;
        string directory = Path.GetDirectoryName(output);
        string system = Environment.SystemDirectory;
        image = Path.ChangeExtension(output, ".exe");
        resources = Path.Combine(directory, "en-US", Path.GetFileName(image) + ".mui");
        title = Path.GetFileName(output) + " - Notepad";
        try {
            Directory.CreateDirectory(Path.GetDirectoryName(resources));
            File.Copy(Path.Combine(system, "notepad.exe"), image);
            File.Copy(Path.Combine(system, "en-US", "notepad.exe.mui"), resources);
            using (var file = new FileStream(output, FileMode.CreateNew, FileAccess.Write, FileShare.None)) {
                byte[] preamble = FileEncoding.GetPreamble();
                file.Write(preamble, 0, preamble.Length);
            }
            if (session.State != ComputerUseState.Active) throw new InvalidOperationException();
            process = Process.Start(new ProcessStartInfo(image, "\"" + output + "\"") {
                UseShellExecute = false, WorkingDirectory = directory, WindowStyle = ProcessWindowStyle.Minimized,
            });
            if (process == null) throw new InvalidOperationException("Could not start the lab Notepad.");
            window = WaitForWindow(out editor);
            CheckTarget();
            if (showForCapture && (!ShowWindowAsync(window, ShowWithoutActivation)
                    || !SetWindowPos(window, IntPtr.Zero, 36, 120, 700, 360, NoZOrderOrActivation)))
                throw new IOException("Could not show the lab Notepad window for capture.");
        } catch {
            Dispose();
            throw;
        }
    }

    private IntPtr WaitForWindow(out IntPtr field) {
        var time = Stopwatch.StartNew();
        if (!process.WaitForInputIdle(4000)) throw new IOException("The lab Notepad did not open.");
        while (session.State == ComputerUseState.Active && !process.HasExited && time.ElapsedMilliseconds < 4000) {
            process.Refresh();
            var handle = process.MainWindowHandle;
            if (handle != IntPtr.Zero) {
                field = FindWindowEx(handle, IntPtr.Zero, "Edit", null);
                if (field != IntPtr.Zero) return handle;
            }
            Thread.Sleep(25);
        }
        throw new IOException("The lab Notepad did not open.");
    }

    public string ReadEditor() {
        CheckTarget();
        var text = new StringBuilder(MaxReadCharacters + 1);
        UIntPtr length;
        if (ReadMessage(editor, WmGetText, new UIntPtr((uint)text.Capacity), text, MessageFlags, MessageTimeoutMs, out length) == IntPtr.Zero
                || length.ToUInt64() >= MaxReadCharacters)
            throw new IOException("Could not read the lab Notepad field.");
        return text.ToString();
    }

    internal bool IsBlank() {
        try { return ReadEditor().Length == 0; }
        catch (IOException) { return false; }
    }

    public void Apply(ComputerUseStep step, string text) {
        CheckTarget();
        bool writing = step == ComputerUseStep.Write;
        uint save = writing ? 0 : SaveCommand();
        var permit = session.Consume(step, text);
        if (permit == null) throw new IOException("The Notepad permission is no longer valid.");
        bool applied = false;
        try {
            if (session.State != ComputerUseState.Active) return;
            UIntPtr result;
            applied = writing
                ? ReplaceSelection(editor, EmReplaceSel, new UIntPtr(1), text, MessageFlags, MessageTimeoutMs, out result) != IntPtr.Zero
                : SendCommand(window, WmCommand, new UIntPtr(save), IntPtr.Zero, MessageFlags, MessageTimeoutMs, out result) != IntPtr.Zero;
        } finally { session.Report(permit, applied); }
    }

    private uint SaveCommand() {
        var fileMenu = GetSubMenu(GetMenu(window), 0);
        var label = new StringBuilder(64);
        for (uint index = 0; index < GetMenuItemCount(fileMenu); index++) {
            if (GetMenuString(fileMenu, index, label, label.Capacity, MenuByPosition) <= 0) continue;
            if (label.ToString().Replace("&", "").Split('\t')[0] != "Save") continue;
            uint command = GetMenuItemID(fileMenu, (int)index);
            if (command > 0 && command <= ushort.MaxValue) return command;
        }
        throw new IOException("The lab Notepad Save command is unavailable.");
    }

    private void CheckTarget() {
        if (!IsTargetAvailable()) throw new IOException("The lab Notepad window or document changed.");
    }

    internal bool IsTargetAvailable() {
        try {
            if (session.State != ComputerUseState.Active || process.HasExited || !Owned(window) || !Owned(editor)
                    || !String.Equals(process.MainModule.FileName, image, StringComparison.OrdinalIgnoreCase)
                    || GetParent(editor) != window || !IsWindowEnabled(window) || !IsWindowEnabled(editor)) return false;
            var text = new StringBuilder(128);
            return GetClassName(editor, text, text.Capacity) > 0 && text.ToString() == "Edit"
                && GetClassName(window, text, text.Capacity) > 0 && text.ToString() == "Notepad"
                && GetWindowText(window, text, text.Capacity) > 0 && (text.ToString() == title || text.ToString() == "*" + title);
        } catch (InvalidOperationException) { return false; }
        catch (System.ComponentModel.Win32Exception) { return false; }
    }

    private bool Owned(IntPtr handle) {
        uint owner;
        return handle != IntPtr.Zero && GetWindowThreadProcessId(handle, out owner) != 0 && owner == process.Id;
    }

    public void Dispose() {
        try {
            if (process != null && !process.HasExited) {
                if (!String.Equals(process.MainModule.FileName, image, StringComparison.OrdinalIgnoreCase)) return;
                process.Kill();
                if (!process.WaitForExit(3000)) return;
            }
            File.Delete(image);
            File.Delete(resources);
            Directory.Delete(Path.GetDirectoryName(resources), false);
        } catch (InvalidOperationException) { }
        catch (System.ComponentModel.Win32Exception) { }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
        finally { if (process != null) process.Dispose(); }
    }

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr FindWindowEx(IntPtr root, IntPtr after, string className, string title);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetClassName(IntPtr target, StringBuilder text, int count);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowText(IntPtr target, StringBuilder text, int count);
    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr target, out uint owner);
    [DllImport("user32.dll")]
    private static extern IntPtr GetParent(IntPtr target);
    [DllImport("user32.dll")]
    private static extern bool IsWindowEnabled(IntPtr target);
    [DllImport("user32.dll")]
    private static extern bool ShowWindowAsync(IntPtr target, int command);
    [DllImport("user32.dll")]
    private static extern bool SetWindowPos(IntPtr target, IntPtr after, int x, int y, int width, int height, uint flags);
    [DllImport("user32.dll")]
    private static extern IntPtr GetMenu(IntPtr target);
    [DllImport("user32.dll")]
    private static extern IntPtr GetSubMenu(IntPtr menu, int index);
    [DllImport("user32.dll")]
    private static extern int GetMenuItemCount(IntPtr menu);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetMenuString(IntPtr menu, uint index, StringBuilder text, int count, uint flags);
    [DllImport("user32.dll")]
    private static extern uint GetMenuItemID(IntPtr menu, int index);
    [DllImport("user32.dll", EntryPoint = "SendMessageTimeoutW", CharSet = CharSet.Unicode)]
    private static extern IntPtr ReadMessage(IntPtr target, uint message, UIntPtr argument, StringBuilder text,
        uint flags, uint timeout, out UIntPtr result);
    [DllImport("user32.dll", EntryPoint = "SendMessageTimeoutW", CharSet = CharSet.Unicode)]
    private static extern IntPtr ReplaceSelection(IntPtr target, uint message, UIntPtr argument, string text,
        uint flags, uint timeout, out UIntPtr result);
    [DllImport("user32.dll", EntryPoint = "SendMessageTimeoutW")]
    private static extern IntPtr SendCommand(IntPtr target, uint message, UIntPtr argument, IntPtr unused,
        uint flags, uint timeout, out UIntPtr result);
}
