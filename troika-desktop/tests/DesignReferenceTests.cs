using System;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Troika.Desktop;

public static class DesignReferenceTests {
    private static void Assert(bool value,string message){if(!value)throw new InvalidOperationException(message);}
    private static BitmapSource Render(FrameworkElement element,int width,int height){
        element.Measure(new Size(width,height));element.Arrange(new Rect(0,0,width,height));element.UpdateLayout();
        var result=new RenderTargetBitmap(width,height,96,96,PixelFormats.Pbgra32);result.Render(element);return result;
    }
    private static byte[] Pixels(BitmapSource image){var b=new byte[image.PixelWidth*image.PixelHeight*4];image.CopyPixels(b,image.PixelWidth*4,0);return b;}
    private static void Save(BitmapSource image,string file){var encoder=new PngBitmapEncoder();encoder.Frames.Add(BitmapFrame.Create(image));using(var stream=File.Create(file))encoder.Save(stream);}
    [STAThread] public static int Main(){
        try{
            string output=Environment.GetEnvironmentVariable("TROIKA_DESIGN_RENDERS");if(!string.IsNullOrEmpty(output))Directory.CreateDirectory(output);
            GlyphTypeface glyph;
            Assert(new Typeface(BrandAssets.Font,FontStyles.Normal,FontWeights.Normal,FontStretches.Normal).TryGetGlyphTypeface(out glyph),"Bundled Golos Text could not be loaded by WPF.");
            Assert(glyph.FontUri.LocalPath.IndexOf("assets",StringComparison.OrdinalIgnoreCase)>=0&&glyph.CharacterToGlyphMap.ContainsKey('Т'),"WPF silently fell back to a different font.");
            Assert(BrandAssets.Load("mic.png")!=null&&BrandAssets.Load("logo-ru-primary.png")!=null&&BrandAssets.Load("logo-ru-reverse.png")!=null,"Brand artwork is missing from the build.");
            Console.WriteLine("PASS bundled Golos Text renders Cyrillic and all brand assets are local");
            var orb=new Orb{Motion=false};orb.SetState("idle");var idle=Pixels(Render(orb,260,260));Thread.Sleep(100);
            Assert(idle.SequenceEqual(Pixels(Render(orb,260,260))),"Reduced motion changes a supposedly static frame.");
            var hashes=new System.Collections.Generic.HashSet<string>();
            foreach(string state in new[]{"idle","listening","thinking","acting","approval","speaking","done","error"}){
                orb.SetState(state);var image=Render(orb,260,260);var bytes=Pixels(image);hashes.Add(Convert.ToBase64String(System.Security.Cryptography.SHA256.Create().ComputeHash(bytes)));
                Assert(bytes.Any(b=>b!=0),"A voice state is blank.");if(!string.IsNullOrEmpty(output))Save(image,Path.Combine(output,"windows-voice-"+state+".png"));
            }
            Assert(hashes.Count==8,"Two voice states are visually indistinguishable.");
            Console.WriteLine("PASS reduced motion is stable and all eight voice states have distinct renders");
            var app=new Application{ShutdownMode=ShutdownMode.OnExplicitShutdown};
            var window=new MainWindow(true){Width=960,Height=680,ShowActivated=false,WindowStartupLocation=WindowStartupLocation.Manual,Left=-10000,Top=-10000};
            window.Show();
            foreach(bool light in new[]{false,true}){
                typeof(MainWindow).GetField("light",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(window,light);
                typeof(MainWindow).GetMethod("Build",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(window,null);
                var voice=(Orb)typeof(MainWindow).GetField("orb",BindingFlags.Instance|BindingFlags.NonPublic).GetValue(window);voice.Motion=false;voice.SetState("idle");
                var image=Render(window,960,680);if(!string.IsNullOrEmpty(output))Save(image,Path.Combine(output,"windows-"+(light?"light":"dark")+"-960.png"));
            }
            window.Close();app.Shutdown();Console.WriteLine("PASS native Windows home renders in both themes with a temporary profile");return 0;
        }catch(Exception e){Console.Error.WriteLine(e);return 1;}
    }
}
