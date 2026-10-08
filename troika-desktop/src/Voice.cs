using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

namespace Troika.Desktop {
    // PCM capture stays in RAM. No microphone access before an explicit user action.
    public sealed class VoiceRecorder : IDisposable {
        [StructLayout(LayoutKind.Sequential, Pack = 2)] private struct Format { public ushort Tag, Channels; public uint Rate, Average; public ushort Align, Bits, Extra; }
        [StructLayout(LayoutKind.Sequential)] private struct Header { public IntPtr Data; public uint Length, Recorded; public IntPtr User; public uint Flags, Loops; public IntPtr Next, Reserved; }
        [DllImport("winmm.dll")] private static extern uint waveInOpen(out IntPtr handle, uint device, ref Format format, IntPtr callback, IntPtr instance, uint flags);
        [DllImport("winmm.dll")] private static extern uint waveInPrepareHeader(IntPtr handle, IntPtr header, uint size);
        [DllImport("winmm.dll")] private static extern uint waveInUnprepareHeader(IntPtr handle, IntPtr header, uint size);
        [DllImport("winmm.dll")] private static extern uint waveInAddBuffer(IntPtr handle, IntPtr header, uint size);
        [DllImport("winmm.dll")] private static extern uint waveInStart(IntPtr handle);
        [DllImport("winmm.dll")] private static extern uint waveInReset(IntPtr handle);
        [DllImport("winmm.dll")] private static extern uint waveInClose(IntPtr handle);
        private IntPtr device, buffer, header;
        public bool Recording { get { return device != IntPtr.Zero; } }
        public void Start() {
            if (Recording) throw new InvalidOperationException("Запись уже идёт.");
            var format = new Format { Tag = 1, Channels = 1, Rate = 16000, Average = 32000, Align = 2, Bits = 16, Extra = 0 };
            if (waveInOpen(out device, uint.MaxValue, ref format, IntPtr.Zero, IntPtr.Zero, 0) != 0) { device = IntPtr.Zero; throw new InvalidOperationException("Микрофон недоступен. Проверьте подключение и разрешение Windows."); }
            try {
                buffer = Marshal.AllocHGlobal(32000 * 60); header = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(Header)));
                Marshal.StructureToPtr(new Header { Data = buffer, Length = 32000 * 60 }, header, false);
                Check(waveInPrepareHeader(device, header, (uint)Marshal.SizeOf(typeof(Header))));
                Check(waveInAddBuffer(device, header, (uint)Marshal.SizeOf(typeof(Header)))); Check(waveInStart(device));
            } catch { Dispose(); throw; }
        }
        private static void Check(uint result) { if (result != 0) throw new InvalidOperationException("Не удалось начать запись микрофона."); }
        public byte[] Stop() {
            if (!Recording) return new byte[0];
            try {
                waveInReset(device);
                var value = (Header)Marshal.PtrToStructure(header, typeof(Header));
                var audio = new byte[value.Recorded - value.Recorded % 2];
                Marshal.Copy(buffer, audio, 0, audio.Length);
                return Wav(audio);
            } finally { Dispose(); }
        }
        public static byte[] Wav(byte[] pcm) {
            using (var stream = new MemoryStream()) using (var writer = new BinaryWriter(stream, Encoding.ASCII)) {
                writer.Write(Encoding.ASCII.GetBytes("RIFF")); writer.Write(pcm.Length + 36); writer.Write(Encoding.ASCII.GetBytes("WAVEfmt "));
                writer.Write(16); writer.Write((short)1); writer.Write((short)1); writer.Write(16000); writer.Write(32000); writer.Write((short)2); writer.Write((short)16);
                writer.Write(Encoding.ASCII.GetBytes("data")); writer.Write(pcm.Length); writer.Write(pcm); return stream.ToArray();
            }
        }
        public void Dispose() {
            if (device != IntPtr.Zero) { waveInReset(device); if (header != IntPtr.Zero) waveInUnprepareHeader(device, header, (uint)Marshal.SizeOf(typeof(Header))); waveInClose(device); device = IntPtr.Zero; }
            if (header != IntPtr.Zero) { Marshal.FreeHGlobal(header); header = IntPtr.Zero; }
            if (buffer != IntPtr.Zero) { Marshal.FreeHGlobal(buffer); buffer = IntPtr.Zero; }
        }
    }
}
