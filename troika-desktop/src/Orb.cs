using System;
using System.Windows;
using System.Windows.Media;
using System.Windows.Threading;

namespace Troika.Desktop {
    public sealed class Orb : FrameworkElement {
        private readonly DispatcherTimer timer;
        private double phase;
        public string State = "idle";
        public bool Motion = SystemParameters.ClientAreaAnimation;
        public Orb() {
            IsHitTestVisible = false;
            timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(40) };
            timer.Tick += delegate { phase += State == "idle" ? 0.009 : 0.045; InvalidateVisual(); };
            Unloaded += delegate { timer.Stop(); };
            Loaded += delegate { SetState(State); };
        }
        public void SetState(string value) { State = value; timer.Interval = TimeSpan.FromMilliseconds(value == "idle" ? 100 : 40); if (Motion && IsLoaded) timer.Start(); else timer.Stop(); InvalidateVisual(); }
        private static Color ColorOf(string text) { return (Color)ColorConverter.ConvertFromString(text); }
        protected override void OnRender(DrawingContext drawing) {
            var center = new Point(ActualWidth / 2, ActualHeight / 2);
            double radius = Math.Min(ActualWidth, ActualHeight) * .27;
            var halo = new RadialGradientBrush(); halo.GradientStops.Add(new GradientStop(ColorOf("#605CDFFF"), 0)); halo.GradientStops.Add(new GradientStop(ColorOf("#205578D8"), .48)); halo.GradientStops.Add(new GradientStop(Colors.Transparent, 1));
            drawing.DrawEllipse(halo, null, center, radius * 2, radius * 2);
            double pulse = State == "listening" || State == "speaking" ? Math.Sin(phase * 2) * .04 : 0;
            for (int ring = 0; ring < 4; ring++) {
                var geometry = new StreamGeometry();
                using (var ctx = geometry.Open()) {
                    for (int i = 0; i <= 180; i++) {
                        double angle = i * Math.PI * 2 / 180;
                        double r = radius * (1 + ring * .16 + pulse) * (1 + .09 * Math.Sin(angle * 3 + phase + ring * .75) + .035 * Math.Cos(angle * 5 - phase));
                        var point = new Point(center.X + Math.Cos(angle + ring * .24) * r, center.Y + Math.Sin(angle + ring * .24) * r * .83);
                        if (i == 0) ctx.BeginFigure(point, false, true); else ctx.LineTo(point, true, false);
                    }
                }
                geometry.Freeze();
                var brush = new LinearGradientBrush(ColorOf(ring % 2 == 0 ? "#A561FAFF" : "#BEAB83FF"), ColorOf(ring % 2 == 0 ? "#204079CC" : "#206B4BA5"), new Point(0, 0), new Point(1, 1));
                drawing.DrawGeometry(null, new Pen(brush, ring == 0 ? 2.1 : 1.1), geometry);
            }
            var core = new RadialGradientBrush(); core.GradientOrigin = new Point(.32, .26); core.Center = new Point(.43, .42); core.RadiusX = .72; core.RadiusY = .72; core.GradientStops.Add(new GradientStop(ColorOf("#ECFEFF"), 0)); core.GradientStops.Add(new GradientStop(ColorOf("#258DAB"), .36)); core.GradientStops.Add(new GradientStop(ColorOf("#233557"), .78)); core.GradientStops.Add(new GradientStop(ColorOf("#10203D"), 1));
            double sphere = radius * .75;
            drawing.DrawEllipse(core, new Pen(new SolidColorBrush(ColorOf("#79ECFA")), 1.1), center, sphere, sphere);
            drawing.PushClip(new EllipseGeometry(center, sphere, sphere));
            for (int band = -3; band <= 3; band++) {
                double y = band * sphere * .22; double rx = Math.Sqrt(sphere * sphere - y * y);
                drawing.DrawEllipse(null, new Pen(new SolidColorBrush(ColorOf("#5657F3FA")), .65), new Point(center.X, center.Y + y), rx, Math.Max(1, sphere * .15));
            }
            for (int band = -3; band <= 3; band++) drawing.DrawEllipse(null, new Pen(new SolidColorBrush(ColorOf("#5AA19AFF")), .65), center, Math.Abs(Math.Sin(band * .31 + phase * .15)) * sphere, sphere);
            drawing.Pop();
            var star = new SolidColorBrush(ColorOf("#B2EFFFFF"));
            for (int i = 0; i < 9; i++) { double a = i * 2.4 + phase * .22; var point = new Point(center.X + Math.Cos(a) * radius * (1.28 + i % 3 * .13), center.Y + Math.Sin(a) * radius * (1.06 + i % 3 * .12)); drawing.DrawEllipse(star, null, point, i % 3 == 0 ? 2 : 1, i % 3 == 0 ? 2 : 1); }
        }
    }
}
