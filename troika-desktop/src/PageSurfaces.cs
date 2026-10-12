using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Markup;

namespace Troika.Desktop {
    public sealed partial class MainWindow {
        private Brush CardSurface() {
            var tone = ((SolidColorBrush)surface).Color;
            return new LinearGradientBrush(
                System.Windows.Media.Color.FromArgb(245, tone.R, tone.G, tone.B),
                System.Windows.Media.Color.FromArgb(190, tone.R, tone.G, tone.B), 45);
        }

        // Reparent controls without replacing their values or event handlers.
        private Border SurfaceGroup(int start, string title, string caption, string icon) {
            var content = new StackPanel();
            if (title.Length > 0) {
                var heading = new DockPanel { Margin = new Thickness(0, 0, 0, 12) };
                var symbol = OutlineIcon(icon, accent); symbol.Margin = new Thickness(0, 0, 10, 0); DockPanel.SetDock(symbol, Dock.Left); heading.Children.Add(symbol);
                var name = Label(title, 17, text); name.FontWeight = FontWeights.SemiBold; heading.Children.Add(name); content.Children.Add(heading);
            }
            if (caption.Length > 0) { var hint = Label(caption, 12, muted); hint.Margin = new Thickness(0, 0, 0, 14); content.Children.Add(hint); }
            while (panelContent.Children.Count > start) { var child = panelContent.Children[start]; panelContent.Children.RemoveAt(start); content.Children.Add(child); }
            var card = new Border { Background = CardSurface(), BorderBrush = line, BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(12), Padding = new Thickness(18), Margin = new Thickness(0, 0, 0, 14), Child = content };
            panelContent.Children.Add(card);
            return card;
        }

        private void CollapsibleGroup(Border card, string title, bool expanded) {
            int index = panelContent.Children.IndexOf(card); panelContent.Children.Remove(card);
            card.Margin = new Thickness(0); var heading = Label(title, 14, text);
            var section = new Expander { Header = heading, Content = card, IsExpanded = expanded, Margin = new Thickness(0, 0, 0, 14) };
            AccessibleName(section, title); panelContent.Children.Insert(index, section);
        }

        private void CompactActions(int start) {
            var actions = new WrapPanel { Margin = new Thickness(0, 8, 0, 0) };
            while (panelContent.Children.Count > start) {
                var button = (Button)panelContent.Children[start]; panelContent.Children.RemoveAt(start);
                button.Margin = new Thickness(0, 0, 8, 8); button.HorizontalAlignment = HorizontalAlignment.Left; actions.Children.Add(button);
            }
            panelContent.Children.Add(actions);
        }

        private void EmptyState(string title, string description, string icon) {
            SurfaceGroup(panelContent.Children.Count, title, description, icon);
        }

        private void ApplyControlStyles() {
            Resources["TroikaSurface"] = surface; Resources["TroikaText"] = text;
            Resources["TroikaLine"] = line; Resources["TroikaAccent"] = accent; Resources["TroikaTint"] = tint;
            var styles = (ResourceDictionary)XamlReader.Parse(@"
<ResourceDictionary xmlns='http://schemas.microsoft.com/winfx/2006/xaml/presentation' xmlns:x='http://schemas.microsoft.com/winfx/2006/xaml'>
 <Style TargetType='{x:Type TextBox}'>
  <Setter Property='SelectionBrush' Value='{DynamicResource TroikaAccent}'/>
  <Setter Property='Template'><Setter.Value><ControlTemplate TargetType='{x:Type TextBox}'>
   <Border x:Name='outline' CornerRadius='8' Background='{TemplateBinding Background}' BorderBrush='{TemplateBinding BorderBrush}' BorderThickness='{TemplateBinding BorderThickness}'>
    <ScrollViewer x:Name='PART_ContentHost'/>
   </Border>
   <ControlTemplate.Triggers><Trigger Property='IsKeyboardFocusWithin' Value='True'><Setter TargetName='outline' Property='BorderBrush' Value='{DynamicResource TroikaAccent}'/></Trigger></ControlTemplate.Triggers>
  </ControlTemplate></Setter.Value></Setter>
 </Style>
 <Style TargetType='{x:Type PasswordBox}'>
  <Setter Property='Template'><Setter.Value><ControlTemplate TargetType='{x:Type PasswordBox}'>
   <Border x:Name='outline' CornerRadius='8' Background='{TemplateBinding Background}' BorderBrush='{TemplateBinding BorderBrush}' BorderThickness='{TemplateBinding BorderThickness}'><ScrollViewer x:Name='PART_ContentHost'/></Border>
   <ControlTemplate.Triggers><Trigger Property='IsKeyboardFocusWithin' Value='True'><Setter TargetName='outline' Property='BorderBrush' Value='{DynamicResource TroikaAccent}'/></Trigger></ControlTemplate.Triggers>
  </ControlTemplate></Setter.Value></Setter>
 </Style>
 <Style TargetType='{x:Type DatePickerTextBox}'>
  <Setter Property='Background' Value='{DynamicResource TroikaSurface}'/><Setter Property='Foreground' Value='{DynamicResource TroikaText}'/><Setter Property='Padding' Value='9'/><Setter Property='BorderBrush' Value='{DynamicResource TroikaLine}'/>
  <Setter Property='Template'><Setter.Value><ControlTemplate TargetType='{x:Type DatePickerTextBox}'>
   <Border CornerRadius='8' Background='{TemplateBinding Background}' BorderBrush='{TemplateBinding BorderBrush}' BorderThickness='1'><Grid><ScrollViewer x:Name='PART_ContentHost'/><ContentControl x:Name='PART_Watermark' Content='Выберите дату' Foreground='{DynamicResource TroikaText}' IsHitTestVisible='False' Margin='9' Visibility='Collapsed'/></Grid></Border>
   <ControlTemplate.Triggers><Trigger Property='Text' Value=''><Setter TargetName='PART_Watermark' Property='Visibility' Value='Visible'/></Trigger></ControlTemplate.Triggers>
  </ControlTemplate></Setter.Value></Setter>
 </Style>
 <Style TargetType='{x:Type Expander}'>
  <Setter Property='Template'><Setter.Value><ControlTemplate TargetType='{x:Type Expander}'>
   <StackPanel>
    <ToggleButton Content='{TemplateBinding Header}' IsChecked='{Binding IsExpanded, RelativeSource={RelativeSource TemplatedParent}, Mode=TwoWay}' HorizontalContentAlignment='Left'>
     <ToggleButton.Template><ControlTemplate TargetType='{x:Type ToggleButton}'>
      <Border x:Name='outline' CornerRadius='8' BorderBrush='{DynamicResource TroikaLine}' BorderThickness='1' Background='{DynamicResource TroikaSurface}' Padding='14,12'><DockPanel><TextBlock x:Name='symbol' Text='＋' Foreground='{DynamicResource TroikaAccent}' Margin='0,0,9,0'/><ContentPresenter/></DockPanel></Border>
      <ControlTemplate.Triggers><Trigger Property='IsChecked' Value='True'><Setter TargetName='symbol' Property='Text' Value='−'/></Trigger><Trigger Property='IsMouseOver' Value='True'><Setter TargetName='outline' Property='BorderBrush' Value='{DynamicResource TroikaAccent}'/></Trigger></ControlTemplate.Triggers>
     </ControlTemplate></ToggleButton.Template>
    </ToggleButton>
    <ContentPresenter x:Name='details' ContentSource='Content' Margin='0,10,0,0' Visibility='Collapsed'/>
   </StackPanel><ControlTemplate.Triggers><Trigger Property='IsExpanded' Value='True'><Setter TargetName='details' Property='Visibility' Value='Visible'/></Trigger></ControlTemplate.Triggers>
  </ControlTemplate></Setter.Value></Setter>
 </Style>
 <Style TargetType='{x:Type ComboBox}'>
  <Setter Property='Foreground' Value='{DynamicResource TroikaText}'/><Setter Property='Background' Value='{DynamicResource TroikaSurface}'/><Setter Property='BorderBrush' Value='{DynamicResource TroikaLine}'/>
  <Setter Property='MinHeight' Value='42'/><Setter Property='Padding' Value='12,9'/><Setter Property='FontSize' Value='14'/>
  <Setter Property='Template'><Setter.Value><ControlTemplate TargetType='{x:Type ComboBox}'>
   <Grid>
    <ToggleButton Focusable='False' IsChecked='{Binding IsDropDownOpen, RelativeSource={RelativeSource TemplatedParent}, Mode=TwoWay}'>
     <ToggleButton.Template><ControlTemplate TargetType='{x:Type ToggleButton}'><Border x:Name='outline' CornerRadius='8' Background='{DynamicResource TroikaSurface}' BorderBrush='{DynamicResource TroikaLine}' BorderThickness='1'><TextBlock Text='⌄' Foreground='{DynamicResource TroikaText}' HorizontalAlignment='Right' VerticalAlignment='Center' Margin='0,0,12,0'/></Border><ControlTemplate.Triggers><Trigger Property='IsMouseOver' Value='True'><Setter TargetName='outline' Property='BorderBrush' Value='{DynamicResource TroikaAccent}'/></Trigger></ControlTemplate.Triggers></ControlTemplate></ToggleButton.Template>
    </ToggleButton>
    <ContentPresenter IsHitTestVisible='False' Content='{TemplateBinding SelectionBoxItem}' ContentTemplate='{TemplateBinding SelectionBoxItemTemplate}' Margin='12,8,36,8' VerticalAlignment='Center'/>
    <Popup x:Name='PART_Popup' Placement='Bottom' IsOpen='{TemplateBinding IsDropDownOpen}' AllowsTransparency='True' Focusable='False'>
     <Border Background='{DynamicResource TroikaSurface}' BorderBrush='{DynamicResource TroikaLine}' BorderThickness='1' CornerRadius='8' Padding='4' MinWidth='{Binding ActualWidth, RelativeSource={RelativeSource TemplatedParent}}' MaxHeight='280'><ScrollViewer><ItemsPresenter KeyboardNavigation.DirectionalNavigation='Contained'/></ScrollViewer></Border>
    </Popup>
   </Grid>
   <ControlTemplate.Triggers><Trigger Property='IsEnabled' Value='False'><Setter Property='Opacity' Value='.4'/></Trigger></ControlTemplate.Triggers>
  </ControlTemplate></Setter.Value></Setter>
 </Style>
 <Style TargetType='{x:Type ComboBoxItem}'>
  <Setter Property='Foreground' Value='{DynamicResource TroikaText}'/><Setter Property='Padding' Value='10,8'/>
  <Setter Property='Template'><Setter.Value><ControlTemplate TargetType='{x:Type ComboBoxItem}'><Border x:Name='item' CornerRadius='5' Padding='{TemplateBinding Padding}' Background='Transparent'><ContentPresenter/></Border><ControlTemplate.Triggers><Trigger Property='IsHighlighted' Value='True'><Setter TargetName='item' Property='Background' Value='{DynamicResource TroikaTint}'/></Trigger><Trigger Property='IsSelected' Value='True'><Setter TargetName='item' Property='Background' Value='{DynamicResource TroikaTint}'/></Trigger></ControlTemplate.Triggers></ControlTemplate></Setter.Value></Setter>
 </Style>
</ResourceDictionary>");
            foreach (object key in styles.Keys) Resources[key] = styles[key];
        }
    }
}
