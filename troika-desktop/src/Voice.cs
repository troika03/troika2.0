using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

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
        internal static void Listen(Func<byte[], int, bool> receive, Action ready, CancellationToken cancellation) {
            const int blockSize = 3200;
            const uint done = 1;
            var format = new Format { Tag = 1, Channels = 1, Rate = 16000, Average = 32000, Align = 2, Bits = 16, Extra = 0 };
            var size = (uint)Marshal.SizeOf(typeof(Header));
            var buffers = new IntPtr[4];
            var headers = new IntPtr[buffers.Length];
            var prepared = new bool[buffers.Length];
            var bytes = new byte[blockSize];
            using (var signal = new AutoResetEvent(false)) {
                IntPtr input;
                if (waveInOpen(out input, uint.MaxValue, ref format, signal.SafeWaitHandle.DangerousGetHandle(), IntPtr.Zero, 0x50000) != 0)
                    throw new InvalidOperationException("Микрофон недоступен. Проверьте подключение и разрешение Windows.");
                try {
                    for (int i = 0; i < buffers.Length; i++) {
                        buffers[i] = Marshal.AllocHGlobal(blockSize);
                        headers[i] = Marshal.AllocHGlobal((int)size);
                        Marshal.StructureToPtr(new Header { Data = buffers[i], Length = blockSize }, headers[i], false);
                        Check(waveInPrepareHeader(input, headers[i], size)); prepared[i] = true;
                        Check(waveInAddBuffer(input, headers[i], size));
                    }
                    cancellation.ThrowIfCancellationRequested();
                    Check(waveInStart(input));
                    ready();
                    var signals = new WaitHandle[] { cancellation.WaitHandle, signal };
                    int index = 0;
                    while (true) {
                        cancellation.ThrowIfCancellationRequested();
                        var current = (Header)Marshal.PtrToStructure(headers[index], typeof(Header));
                        if ((current.Flags & done) == 0) {
                            if (WaitHandle.WaitAny(signals, 4000) == WaitHandle.WaitTimeout)
                                throw new InvalidOperationException("Нет сигнала с микрофона. Проверьте выбранное устройство записи.");
                            continue;
                        }
                        int count = (int)Math.Min(current.Recorded, blockSize) & ~1;
                        Marshal.Copy(buffers[index], bytes, 0, count);
                        if (count > 0 && !receive(bytes, count)) return;
                        Check(waveInAddBuffer(input, headers[index], size));
                        index = (index + 1) % headers.Length;
                    }
                } finally {
                    waveInReset(input);
                    for (int i = 0; i < headers.Length; i++)
                        if (prepared[i]) waveInUnprepareHeader(input, headers[i], size);
                    waveInClose(input);
                    Array.Clear(bytes, 0, bytes.Length);
                    for (int i = 0; i < buffers.Length; i++) {
                        if (headers[i] != IntPtr.Zero) Marshal.FreeHGlobal(headers[i]);
                        if (buffers[i] != IntPtr.Zero) Marshal.FreeHGlobal(buffers[i]);
                    }
                }
            }
        }
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
