using System;
using System.Collections.Generic;
using System.IO;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace Troika.Desktop {
    /// <summary>Local brand files shipped alongside the desktop executable.</summary>
    public static class BrandAssets {
        private static readonly Dictionary<string, BitmapSource> images = new Dictionary<string, BitmapSource>();
        public static FontFamily Font {
            get {
                string folder = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "assets", "fonts") + Path.DirectorySeparatorChar;
                return Directory.Exists(folder) ? new FontFamily(new Uri(folder), "./#Golos Text") : new FontFamily("Segoe UI");
            }
        }
        public static BitmapSource Load(string name) {
            BitmapSource result;
            if (images.TryGetValue(name, out result)) return result;
            string file = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "assets", "brand", name);
            if (!File.Exists(file)) return null;
            var bitmap = new BitmapImage(); bitmap.BeginInit(); bitmap.CacheOption = BitmapCacheOption.OnLoad;
            bitmap.UriSource = new Uri(file); bitmap.EndInit(); bitmap.Freeze(); images[name] = bitmap; return bitmap;
        }
        public static Image Logo(bool light) {
            return new Image { Source = Load(light ? "logo-ru-primary.png" : "logo-ru-reverse.png"), Width = 124, Height = 32, Stretch = Stretch.Uniform };
        }
    }
}
