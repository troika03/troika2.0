using System;
using System.Windows.Automation.Peers;
using System.Windows.Automation.Provider;
using System.Windows.Controls;

namespace Troika.Desktop {
    internal sealed class ComputerUseEditorField : TextBox {
        private readonly ComputerUseSession session;

        internal ComputerUseEditorField(ComputerUseSession session) {
            this.session = session;
        }

        protected override AutomationPeer OnCreateAutomationPeer() {
            return new EditorPeer(this);
        }

        private void SetPermittedValue(string value) {
            if (value == null) throw new ArgumentNullException("value");
            var permit = session.Consume(ComputerUseStep.Write, value);
            if (permit == null) throw new InvalidOperationException();
            bool applied = false;
            try {
                if (Text.Length != 0) throw new InvalidOperationException();
                Text = value;
                applied = Text == value;
            } finally { session.Report(permit, applied); }
        }

        private sealed class EditorPeer : TextBoxAutomationPeer, IValueProvider {
            private readonly ComputerUseEditorField field;

            internal EditorPeer(ComputerUseEditorField field) : base(field) { this.field = field; }

            bool IValueProvider.IsReadOnly { get { return field.session.State != ComputerUseState.Active; } }
            string IValueProvider.Value { get { return field.Text; } }
            void IValueProvider.SetValue(string value) { field.SetPermittedValue(value); }
        }
    }
}
