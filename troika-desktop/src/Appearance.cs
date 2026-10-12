using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;

namespace Troika.Desktop {
    // The Android palette is shared visually; Windows keeps its own native layout.
    public sealed partial class MainWindow {
        private string interfaceAccent = "amber";
        private readonly Dictionary<string, Button> navigation = new Dictionary<string, Button>();
        private Brush glass, tint;

        private void ApplyPalette() {
            background = Color(light ? "#F7F4EF" : "#121110");
            surface = Color(light ? "#FFFFFF" : "#1E1C19");
            text = Color(light ? "#29241D" : "#F5F1EA");
            muted = Color(light ? "#6F665B" : "#B6AEA1");
            line = Color(light ? "#E6DFD4" : "#39342D");
            var accents = new Dictionary<string, string[]> {
                { "amber", new[] { "#E08A12", "#F5A623" } },
                { "teal", new[] { "#00695C", "#65C8B9" } },
                { "blue", new[] { "#245B9A", "#82B9F5" } },
                { "violet", new[] { "#6246A3", "#B6A2F4" } },
                { "rose", new[] { "#AD3E56", "#FFA1AE" } },
                { "green", new[] { "#537735", "#A6CF82" } }
            };
            if (!accents.ContainsKey(interfaceAccent)) interfaceAccent = "amber";
            accent = Color(accents[interfaceAccent][light ? 0 : 1]);
            accentText = Color(light ? "#FFFFFF" : "#211A11");
            glass = Color(light ? "#D9FFFFFF" : "#D91E1C19");
            var tone = ((SolidColorBrush)accent).Color;
            tint = new SolidColorBrush(System.Windows.Media.Color.FromArgb(light ? (byte)24 : (byte)40, tone.R, tone.G, tone.B));
        }

        private Button NavigationButton(string title, string icon, string panel) {
            var button = Button(title, () => { if (panel.Length == 0) ClosePanel(); else OpenPanel(panel); }, false);
            var row = new StackPanel { Orientation = Orientation.Horizontal };
            row.Children.Add(OutlineIcon(icon, text));
            var label = Label(title, 14, text); label.Margin = new Thickness(12, 0, 0, 0); label.VerticalAlignment = VerticalAlignment.Center; row.Children.Add(label);
            button.Content = row; button.MinHeight = 48; button.Margin = new Thickness(0, 0, 0, 4);
            button.HorizontalContentAlignment = HorizontalAlignment.Left; button.BorderThickness = new Thickness(0); button.Padding = new Thickness(8);
            navigation[panel] = button; return button;
        }

        private void UpdateNavigation() {
            foreach (var entry in navigation) {
                bool selected = entry.Key == openPanel;
                var button = entry.Value; button.Background = selected ? tint : Brushes.Transparent;
                var row = (StackPanel)button.Content;
                ((Path)row.Children[0]).Stroke = selected ? accent : muted;
                ((TextBlock)row.Children[1]).Foreground = selected ? accent : text;
                ((TextBlock)row.Children[1]).FontWeight = selected ? FontWeights.SemiBold : FontWeights.Normal;
                AutomationProperties.SetHelpText(button, selected ? "Текущий раздел" : "Открыть раздел");
            }
        }

        private static Path OutlineIcon(string name, Brush tone) {
            string geometry;
            switch (name) {
                case "home": geometry = "M3,10 L12,3 21,10 M5,9 L5,21 10,21 10,15 14,15 14,21 19,21 19,9"; break;
                case "tasks": geometry = "M3,6 L5,8 8,4 M11,6 L21,6 M3,14 L5,16 8,12 M11,14 L21,14 M11,21 L21,21"; break;
                case "files": geometry = "M3,6 L10,6 12,8 21,8 21,20 3,20 Z M3,6 L3,4 9,4 11,6"; break;
                case "profile": geometry = "M16,7 A4,4 0 1 1 8,7 A4,4 0 1 1 16,7 M4,21 L4,19 C4,12 20,12 20,19 L20,21"; break;
                case "memory": geometry = "M9,3 C5,2 4,6 5,9 C1,11 3,16 6,16 C5,21 10,23 12,19 L12,5 C12,3 11,2 9,3 M15,3 C19,2 20,6 19,9 C23,11 21,16 18,16 C19,21 14,23 12,19 M7,9 L10,10 M17,9 L14,10 M6,16 L9,15 M18,16 L15,15"; break;
                case "code": geometry = "M8,5 L2,12 8,19 M16,5 L22,12 16,19 M14,3 L10,21"; break;
                default: geometry = "M12,3 L12,8 M12,16 L12,21 M3,12 L8,12 M16,12 L21,12 M6,6 L9,9 M15,15 L18,18 M18,6 L15,9 M9,15 L6,18"; break;
            }
            return new Path { Data = Geometry.Parse(geometry), Stroke = tone, StrokeThickness = 1.6, StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round, StrokeLineJoin = PenLineJoin.Round, Width = 20, Height = 20, Stretch = Stretch.Uniform, VerticalAlignment = VerticalAlignment.Center };
        }

        private void AddAppearanceSettings() {
            panelContent.Children.Add(Label("Интерфейс", 20, text));
            Check("Светлая тема", light, value => {
                if (busy || recorder.Recording || speaking || localCheck != null || developmentRelay != null && developmentRelay.Checking) { SetStatus("Сначала остановите текущую задачу.", true); return; }
                light = value; RebuildAppearance();
            });
            var choices = new[] { "amber", "teal", "blue", "violet", "rose", "green" };
            var names = new[] { "Янтарный", "Бирюзовый", "Синий", "Фиолетовый", "Розовый", "Зелёный" };
            var picker = new ComboBox { ItemsSource = names, SelectedIndex = Array.IndexOf(choices, interfaceAccent), MinHeight = 44, FontSize = 14, Margin = new Thickness(0, 8, 0, 16), Foreground = Color("#29241D"), Background = Brushes.White };
            AccessibleName(picker, "Цвет акцента");
            picker.SelectionChanged += delegate {
                if (picker.SelectedIndex < 0) return;
                if (busy || recorder.Recording || speaking || localCheck != null || developmentRelay != null && developmentRelay.Checking) { SetStatus("Сначала остановите текущую задачу.", true); picker.SelectedIndex = Array.IndexOf(choices, interfaceAccent); return; }
                interfaceAccent = choices[picker.SelectedIndex]; RebuildAppearance();
            };
            panelContent.Children.Add(Label("Цвет акцента", 14, muted)); panelContent.Children.Add(picker);
        }

        private void RebuildAppearance() {
            // Preserve the conversation, draft and received file buttons when only styling changes.
            var messages = new List<UIElement>();
            foreach (UIElement message in transcript.Children) messages.Add(message);
            var draft = composer.Text; bool showingConversation = conversationScroll.Visibility == Visibility.Visible;
            transcript.Children.Clear(); SaveSettings(); Build();
            foreach (var message in messages) { Restyle(message); transcript.Children.Add(message); }
            composer.Text = draft;
            if (showingConversation) { hero.Visibility = Visibility.Collapsed; conversationScroll.Visibility = Visibility.Visible; }
            OpenPanel("Аккаунт");
        }

        private void Restyle(DependencyObject element, Brush inherited = null) {
            var block = element as TextBlock; if (block != null) block.Foreground = inherited ?? text;
            var button = element as Button;
            if (button != null) {
                bool primary = button.Tag is bool && (bool)button.Tag;
                inherited = primary ? accentText : text; button.Foreground = inherited;
                button.Background = primary ? accent : Brushes.Transparent; button.BorderBrush = primary ? Brushes.Transparent : line;
            }
            int count = VisualTreeHelper.GetChildrenCount(element);
            for (int i = 0; i < count; i++) Restyle(VisualTreeHelper.GetChild(element, i), inherited);
        }
    }
}
