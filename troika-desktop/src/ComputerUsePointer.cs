using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Shapes;
using ScreenPoint = System.Drawing.Point;

namespace Troika.Desktop {
    internal sealed class ComputerUsePointer : IDisposable {
        private const int TipOffset = 19;
        private const int ExStyle = -20;
        private const int TransparentToolWindow = 0x080000A0; // No activate, tool window, transparent input.
        private const uint MoveWithoutActivating = 0x0011;
        private readonly Window overlay;
        private readonly Canvas surface = new Canvas { IsHitTestVisible = false };
        private readonly Ellipse ring;
        private readonly Border badge;
        private readonly TextBlock label;
        private IntPtr handle;
        private ScreenPoint? lastPoint;

        internal ComputerUsePointer() {
            overlay = new Window { Title = "Указатель Тройки", WindowStyle = WindowStyle.None,
                AllowsTransparency = true, Background = Brushes.Transparent, ShowInTaskbar = false,
                ShowActivated = false, Topmost = true, Focusable = false, IsHitTestVisible = false,
                ResizeMode = ResizeMode.NoResize, Width = 175, Height = 69, Content = surface };
            overlay.SourceInitialized += (sender, args) => {
                handle = new WindowInteropHelper(overlay).Handle;
                int style = GetWindowLong(handle, ExStyle);
                if (SetWindowLong(handle, ExStyle, style | TransparentToolWindow) == 0 && Marshal.GetLastWin32Error() != 0)
                    throw new Win32Exception(Marshal.GetLastWin32Error());
            };

            var ink = new SolidColorBrush(Color.FromRgb(25, 77, 56));
            ring = new Ellipse { Width = 29, Height = 29, Stroke = ink, StrokeThickness = 2,
                Fill = new SolidColorBrush(Color.FromArgb(67, 69, 218, 121)), Visibility = Visibility.Hidden };
            Canvas.SetLeft(ring, 5);
            Canvas.SetTop(ring, 5);
            surface.Children.Add(ring);
            var arrow = new Polygon { Fill = ink, Stroke = Brushes.White, StrokeThickness = 2,
                Points = new PointCollection { new Point(0, 0), new Point(24, 13), new Point(13, 15),
                    new Point(18, 26), new Point(12, 29), new Point(7, 17), new Point(2, 24) } };
            Canvas.SetLeft(arrow, TipOffset);
            Canvas.SetTop(arrow, TipOffset);
            surface.Children.Add(arrow);
            label = new TextBlock { Foreground = Brushes.White, FontFamily = BrandAssets.Font, FontSize = 13,
                FontWeight = FontWeights.SemiBold };
            badge = new Border { Background = ink, CornerRadius = new CornerRadius(5),
                Padding = new Thickness(8, 3, 8, 4), Child = label, Visibility = Visibility.Hidden };
            Canvas.SetLeft(badge, 46);
            Canvas.SetTop(badge, 35);
            surface.Children.Add(badge);
        }

        internal async Task Preview(ComputerUseNotepad document, ComputerUseStep step,
                Func<bool> isFresh, CancellationToken cancellation) {
            document.RaiseForAction();
            ScreenPoint target;
            if (!document.TryGetActionPoint(step, out target)) { Hide(); return; }
            var start = lastPoint ?? new ScreenPoint(target.X + 70, target.Y + 38);
            lastPoint = target;
            int frames = SystemParameters.ClientAreaAnimation ? 8 : 1;
            label.Text = step == ComputerUseStep.Write ? "Ввод" : "Сохранение";
            for (int frame = 1; frame <= frames; frame++) {
                cancellation.ThrowIfCancellationRequested();
                if (!isFresh()) throw new OperationCanceledException();
                ScreenPoint currentTarget;
                if (!document.TryGetActionPoint(step, out currentTarget) || currentTarget != target) { Hide(); return; }
                var point = new ScreenPoint(start.X + (target.X - start.X) * frame / frames,
                    start.Y + (target.Y - start.Y) * frame / frames);
                if (!document.IsActionPointVisible(point)) continue;
                Move(point, frame == frames);
                await Task.Delay(frame == frames ? 150 : 20, cancellation);
            }
        }

        private void Move(ScreenPoint point, bool arrived) {
            if (handle == IntPtr.Zero) new WindowInteropHelper(overlay).EnsureHandle();
            var source = HwndSource.FromHwnd(handle);
            var offset = source.CompositionTarget.TransformToDevice.Transform(new Point(TipOffset, TipOffset));
            if (!SetWindowPos(handle, new IntPtr(-1), point.X - (int)offset.X, point.Y - (int)offset.Y, 0, 0, MoveWithoutActivating))
                throw new Win32Exception(Marshal.GetLastWin32Error());
            ring.Visibility = badge.Visibility = arrived ? Visibility.Visible : Visibility.Hidden;
            if (!overlay.IsVisible) overlay.Show();
        }

        internal void Hide() { if (overlay.IsVisible) overlay.Hide(); }

        public void Dispose() { overlay.Close(); }

        [DllImport("user32.dll", EntryPoint = "GetWindowLongW", SetLastError = true)]
        private static extern int GetWindowLong(IntPtr window, int index);
        [DllImport("user32.dll", EntryPoint = "SetWindowLongW", SetLastError = true)]
        private static extern int SetWindowLong(IntPtr window, int index, int style);
        [DllImport("user32.dll", SetLastError = true)]
        private static extern bool SetWindowPos(IntPtr window, IntPtr after, int x, int y, int width, int height, uint flags);
    }
}
