using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace Troika.Desktop {
    public sealed partial class MainWindow {
        private WrapPanel CapabilityCards() {
            var grid = new WrapPanel { HorizontalAlignment = HorizontalAlignment.Stretch };
            grid.SizeChanged += delegate {
                double available = grid.ActualWidth;
                if (available <= 0) return;
                int columns = available >= 660 ? 3 : available >= 420 ? 2 : 1;
                double width = (available - (columns - 1) * 12) / columns;
                for (int i = 0; i < grid.Children.Count; i++) {
                    var card = (Button)grid.Children[i]; card.Width = width;
                    card.Margin = new Thickness(0, 0, i % columns == columns - 1 ? 0 : 12, 12);
                }
            };
            return grid;
        }

        private void AddCapabilityCard(WrapPanel grid, string title, string subtitle, string icon, Action action) {
            var card = Button(title, action, false);
            card.Width = 210; card.MinHeight = 140; card.Padding = new Thickness(16);
            card.HorizontalContentAlignment = HorizontalAlignment.Stretch;
            card.Margin = new Thickness(0, 0, 12, 12);
            var fill = CardSurface();
            card.Background = fill;
            var content = new Grid(); content.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto }); content.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto }); content.RowDefinitions.Add(new RowDefinition());
            var header = new DockPanel { Margin = new Thickness(0, 0, 0, 12) };
            var forward = Label("›", 18, muted); DockPanel.SetDock(forward, Dock.Right); header.Children.Add(forward);
            var symbol = OutlineIcon(icon, accent); symbol.HorizontalAlignment = HorizontalAlignment.Left; header.Children.Add(symbol); content.Children.Add(header);
            var name = Label(title, 16, text); name.FontWeight = FontWeights.SemiBold; name.Margin = new Thickness(0, 0, 0, 6); Grid.SetRow(name, 1); content.Children.Add(name);
            var hint = Label(subtitle, 12, muted); Grid.SetRow(hint, 2); content.Children.Add(hint); card.Content = content;
            card.MouseEnter += delegate { card.Background = tint; };
            card.MouseLeave += delegate { card.Background = fill; };
            grid.Children.Add(card);
        }
    }
}
