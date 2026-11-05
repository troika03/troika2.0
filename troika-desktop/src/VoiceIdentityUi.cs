using System;
using System.Collections.Generic;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;

namespace Troika.Desktop {
    public sealed partial class MainWindow {
        private VoiceIdentityStore voiceIdentities;
        private VoskVoiceSignatureExtractor voiceSignatures;
        private VoiceRequestGate voiceRequestGate;
        private readonly List<VoiceSignature> voiceEnrollmentSamples = new List<VoiceSignature>();
        private bool voiceEnrollment, voiceProcessing;
        private string voiceEnrollmentOwner = "", voiceRecordingOwner = "", voiceIdentityMessage = "";
        private int voiceIdentityEpoch, voiceRecordingEpoch;
        private static readonly string[] VoiceEnrollmentPhrases = {
            "Тройка, это мой голос. Сегодня я хочу спокойно составить план на день и записать важные дела.",
            "Тройка, помоги мне подготовить полезный документ, проверить результат и сохранить готовый файл на этом компьютере.",
            "Тройка, напомни мне вечером закончить работу, немного отдохнуть и подготовить всё необходимое на следующий день."
        };
        private void InitializeVoiceIdentity() {
            voiceIdentities = new VoiceIdentityStore(store.Root);
            voiceSignatures = new VoskVoiceSignatureExtractor(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "assets", "voice-id"));
            voiceRequestGate = new VoiceRequestGate(voiceIdentities, voiceSignatures);
        }
        private bool VoiceIdentityCurrent(string owner, int epoch) { return !closed && api.Account.SignedIn && api.Account.Email == owner && voiceIdentityEpoch == epoch; }
        private void InvalidateVoiceIdentity() {
            voiceIdentityEpoch++; voiceEnrollment = false; voiceEnrollmentOwner = ""; voiceRecordingOwner = ""; voiceEnrollmentSamples.Clear(); voiceIdentityMessage = "";
            if (voiceProcessing && operation != null) operation.Cancel();
        }
        private void CancelVoiceEnrollment() {
            if (!voiceEnrollment) return;
            if (recorder.Recording) { recordingLimit.Stop(); recorder.Dispose(); }
            InvalidateVoiceIdentity(); if (!voiceProcessing) Idle();
        }
        private bool VoiceIdentityIdle() {
            if (busy || recorder.Recording || speaking || localCheck != null) { SetStatus("Сначала остановите текущую запись или задачу.", true); return false; }
            return true;
        }
        private void RenderVoiceIdentity() {
            panelContent.Children.Clear();
            if (!api.Account.SignedIn) { panelContent.Children.Add(Label("Для регистрации голоса войдите в аккаунт.", 14, muted)); AddPanelButton("Войти", () => OpenPanel("Аккаунт"), true); return; }
            string owner = api.Account.Email; var saved = voiceIdentities.Load(owner);
            panelContent.Children.Add(Label("Образец только на этом ПК.", 13, muted)); Gap();
            if (voiceEnrollment && voiceEnrollmentOwner == owner) {
                int index = voiceEnrollmentSamples.Count;
                panelContent.Children.Add(Label("Образец " + (index + 1) + " из 3", 20, text));
                panelContent.Children.Add(Label(VoiceEnrollmentPhrases[Math.Min(index, 2)], 18, text));
                panelContent.Children.Add(Label("Читайте 5–8 с обычным голосом.", 13, muted));
                if (voiceProcessing) panelContent.Children.Add(Label("Проверяю образец на этом ПК…", 13, muted));
                else AddPanelButton(recorder.Recording ? "Закончить запись" : "Записать образец", () => { var task = ToggleVoiceEnrollment(); }, true);
                AddPanelButton("Отменить регистрацию", () => { var task = Stop(); }, false);
            } else {
                panelContent.Children.Add(Label(saved.Damaged ? "Образец повреждён. Голосовые запросы заблокированы." : saved.Exists ? (saved.Enabled ? "Проверка включена" : "Голос зарегистрирован") : "Голос не зарегистрирован", 15, text));
                if (saved.Exists && !saved.Damaged) Check("Отзываться только на мой голос", saved.Enabled, enabled => {
                    if (!VoiceIdentityIdle() || api.Account.Email != owner || !api.Account.SignedIn) { RenderVoiceIdentity(); return; }
                    try { voiceIdentityEpoch++; voiceIdentities.SetEnabled(owner, enabled); voiceIdentityMessage = ""; }
                    catch (Exception error) { voiceIdentityMessage = error.Message; SetStatus("Не удалось изменить проверку голоса. Повторите действие.", true); }
                    RenderVoiceIdentity();
                });
                if (saved.Enabled && !saved.Damaged) panelContent.Children.Add(Label("Говорите не меньше 4 секунд. Текстовый ввод доступен.", 12, muted));
                AddPanelButton(saved.Exists ? "Зарегистрировать голос заново" : "Зарегистрировать мой голос", () => {
                    if (!VoiceIdentityIdle() || !api.Account.SignedIn || api.Account.Email != owner) return;
                    voiceIdentityEpoch++; voiceEnrollment = true; voiceEnrollmentOwner = owner; voiceEnrollmentSamples.Clear(); voiceIdentityMessage = ""; RenderVoiceIdentity();
                }, true);
                if (saved.Exists) AddPanelButton("Удалить образец голоса", () => {
                    if (!VoiceIdentityIdle() || !api.Account.SignedIn || api.Account.Email != owner) return;
                    try { InvalidateVoiceIdentity(); voiceIdentities.Delete(owner); voiceIdentityMessage = "Образец удалён. Проверка выключена."; }
                    catch (Exception error) { voiceIdentityMessage = error.Message; SetStatus("Не удалось удалить образец голоса. Повторите действие.", true); }
                    RenderVoiceIdentity();
                }, false);
            }
            if (voiceIdentityMessage.Length > 0) { Gap(); panelContent.Children.Add(Label(voiceIdentityMessage, 13, muted)); }
            var details = new StackPanel();
            details.Children.Add(Label("Три образца сохраняются отдельно для аккаунта под защитой Windows. Записи регистрации и образец не отправляются на сервер. Выход сохраняет образец; удаление образца выключает проверку.", 12, muted));
            details.Children.Add(Label("Для проверки нужно не менее 4 секунд речи без учёта пауз. Короткий запрос или несовпавший голос не отправляются. В шуме возможен отказ; повторите фразу или используйте текст.", 12, muted));
            details.Children.Add(Label("Проверка может ошибаться. Запись или имитация голоса может пройти проверку. Это не замена паролю и подтверждениям действий.", 12, muted));
            panelContent.Children.Add(new Expander { Header = Label("Подробнее", 13, muted), Content = details, Margin = new Thickness(0, 12, 0, 8) });
            AddPanelButton("Назад в настройки", () => OpenPanel("Аккаунт"), false);
        }
        private async Task ToggleVoiceEnrollment() {
            await Safe(async () => {
                if (busy) { await Stop(); return; }
                string owner = voiceEnrollmentOwner; int epoch = voiceIdentityEpoch;
                if (!voiceEnrollment || !VoiceIdentityCurrent(owner, epoch)) { CancelVoiceEnrollment(); return; }
                if (!recorder.Recording) {
                    recorder.Start(); recordingLimit.Start(); microphone.Content = "Закончить запись"; send.IsEnabled = false; orb.SetState("listening"); voiceIdentityMessage = ""; SetStatus("Записываю образец голоса", false); RenderVoiceIdentity(); return;
                }
                recordingLimit.Stop(); byte[] audio = recorder.Stop();
                var active = new CancellationTokenSource(TimeSpan.FromSeconds(90)); operation = active; voiceProcessing = true; busy = true; UpdateStop(); RenderVoiceIdentity();
                try {
                    var signature = await Task.Run(() => voiceSignatures.Extract(audio, active.Token), active.Token);
                    active.Token.ThrowIfCancellationRequested(); if (!VoiceIdentityCurrent(owner, epoch) || !voiceEnrollment) throw new OperationCanceledException();
                    if (!VoiceSignature.Consistent(voiceEnrollmentSamples, signature)) throw new InvalidDataException("Голос не совпал. Повторите образец.");
                    voiceEnrollmentSamples.Add(signature);
                    if (voiceEnrollmentSamples.Count == 3) {
                        voiceIdentities.Enroll(owner, voiceEnrollmentSamples); voiceEnrollment = false; voiceEnrollmentOwner = ""; voiceEnrollmentSamples.Clear(); voiceIdentityEpoch++;
                        voiceIdentityMessage = "Голос сохранён. Включите проверку.";
                    } else voiceIdentityMessage = "Образец принят.";
                } catch (OperationCanceledException) { throw; }
                catch (Exception error) { if (VoiceIdentityCurrent(owner, epoch)) voiceIdentityMessage = error.Message; }
                finally {
                    Array.Clear(audio, 0, audio.Length); voiceProcessing = false;
                    if (operation == active) { operation = null; busy = false; Idle(); }
                    active.Dispose(); if (!closed && api.Account.SignedIn && api.Account.Email == owner && openPanel == "Мой голос") RenderVoiceIdentity();
                }
            });
        }
    }
}
