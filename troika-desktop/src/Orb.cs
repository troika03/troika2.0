using System;
using System.Diagnostics;
using System.Windows;
using System.Windows.Media;
using System.Windows.Threading;

namespace Troika.Desktop {
    // One amber contour, using the Android StatusOrb geometry and durations.
    public sealed class Orb : FrameworkElement {
        private readonly DispatcherTimer timer;
        private readonly Stopwatch clock = new Stopwatch();
        public string State = "idle";
        public bool Motion = SystemParameters.ClientAreaAnimation;
        public Orb() {
            IsHitTestVisible = false;
            timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(40) };
            timer.Tick += delegate { InvalidateVisual(); };
            Unloaded += delegate { timer.Stop(); clock.Stop(); };
            Loaded += delegate { SetState(State); };
        }
        public void SetState(string value) {
            if (State != value) clock.Reset();
            State = value;
            if (Motion && IsLoaded) { clock.Start(); timer.Start(); }
            else { timer.Stop(); clock.Stop(); }
            InvalidateVisual();
        }
        private static Brush Glow(Color color, double centerOpacity, double middleOpacity, double middle) {
            var brush = new RadialGradientBrush();
            brush.GradientStops.Add(new GradientStop(Color.FromArgb((byte)(255*centerOpacity),color.R,color.G,color.B),0));
            brush.GradientStops.Add(new GradientStop(Color.FromArgb((byte)(255*middleOpacity),color.R,color.G,color.B),middle));
            brush.GradientStops.Add(new GradientStop(Color.FromArgb(0,color.R,color.G,color.B),1));
            brush.Freeze(); return brush;
        }
        protected override void OnRender(DrawingContext drawing) {
            base.OnRender(drawing);
            double size = Math.Min(ActualWidth,ActualHeight); if(size<=0)return;
            var center = new Point(ActualWidth/2,ActualHeight/2);
            double elapsed=Motion?clock.Elapsed.TotalMilliseconds:0;
            bool voice=State=="listening"||State=="speaking";
            double breathDuration=State=="listening"?760:State=="speaking"?620:State=="acting"?1050:State=="thinking"?1450:2600;
            double motionDuration=voice?1200:State=="thinking"?1800:State=="acting"?2200:8000;
            double triangle=elapsed/breathDuration%2;if(triangle>1)triangle=2-triangle;
            double breath=.5-.5*Math.Cos(triangle*Math.PI),phase=elapsed/motionDuration*2*Math.PI;
            double scale=.93+breath*.08,radius=size*.34*scale;
            Color color=State=="error"?Color.FromRgb(229,96,77):Color.FromRgb(245,166,35);
            drawing.DrawEllipse(Glow(color,.28,.13,.48),null,center,size*.52,size*.52);
            drawing.DrawEllipse(Glow(color,.96,.54,.56),null,center,size*.25*scale,size*.25*scale);
            double amplitude=State=="listening"?8:State=="speaking"?10:State=="acting"?5:State=="thinking"?3:2+breath*2;
            var geometry=new StreamGeometry();
            using(var path=geometry.Open()){
                for(int i=0;i<=96;i++){
                    double angle=i/96.0*2*Math.PI;
                    double r=radius+Math.Sin(angle*3+phase)*amplitude+Math.Cos(angle*2-phase*.7)*amplitude*.45;
                    var point=new Point(center.X+Math.Cos(angle)*r,center.Y+Math.Sin(angle)*r);
                    if(i==0)path.BeginFigure(point,false,true);else path.LineTo(point,true,false);
                }
            }
            geometry.Freeze();var edge=new SolidColorBrush(Color.FromArgb(158,color.R,color.G,color.B));edge.Freeze();
            drawing.DrawGeometry(null,new Pen(edge,State=="done"?2.2:1.5),geometry);
            DrawSignal(drawing,center,size,phase);
        }
        private void DrawSignal(DrawingContext drawing,Point center,double size,double phase){
            var ink=new SolidColorBrush(Color.FromRgb(255,248,231));
            var pen=new Pen(ink,2.5){StartLineCap=PenLineCap.Round,EndLineCap=PenLineCap.Round,LineJoin=PenLineJoin.Round};
            if(State=="listening"||State=="speaking"){
                for(int i=0;i<5;i++){double h=12+(Math.Sin(phase*2+i*.9)+1)*14;drawing.DrawRoundedRectangle(ink,null,new Rect(center.X-18+i*8,center.Y-h/2,4,h),2,2);}return;
            }
            if(State=="thinking"){
                var arc=new StreamGeometry();double r=size*.08;
                using(var p=arc.Open()){p.BeginFigure(new Point(center.X+r*Math.Cos(phase),center.Y+r*Math.Sin(phase)),false,false);p.ArcTo(new Point(center.X+r*Math.Cos(phase+Math.PI*1.45),center.Y+r*Math.Sin(phase+Math.PI*1.45)),new Size(r,r),0,true,SweepDirection.Clockwise,true,false);}
                drawing.DrawGeometry(null,pen,arc);return;
            }
            if(State=="done"){drawing.DrawLine(pen,new Point(center.X-10,center.Y),new Point(center.X-2,center.Y+8));drawing.DrawLine(pen,new Point(center.X-2,center.Y+8),new Point(center.X+12,center.Y-9));return;}
            if(State=="error"){drawing.DrawLine(pen,new Point(center.X,center.Y-12),new Point(center.X,center.Y+5));drawing.DrawEllipse(ink,null,new Point(center.X,center.Y+12),1.6,1.6);return;}
            var microphone=BrandAssets.Load(State=="acting"?"voice-acting.png":State=="approval"?"voice-approval.png":"mic.png");
            if(microphone!=null){double icon=size*36/260;drawing.DrawImage(microphone,new Rect(center.X-icon/2,center.Y-icon/2,icon,icon));}
        }
    }
}
