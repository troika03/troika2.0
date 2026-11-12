using System;
using System.Diagnostics;
using System.Threading.Tasks;

namespace Troika.Desktop {
    internal enum ComputerUseState { Pending, Active, Stopped, Expired, Verified, Failed, Completed }
    internal enum ComputerUseStep { Write, Save }

    internal sealed class ComputerUsePermit {
        internal readonly ComputerUseStep Step;
        internal readonly string Text;
        internal readonly Func<bool> ObservationIsFresh;
        internal readonly TaskCompletionSource<bool> Result = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        internal bool Consumed;
        internal bool ObservationExpired;

        internal ComputerUsePermit(ComputerUseStep step, string text, Func<bool> observationIsFresh) {
            Step = step; Text = text; ObservationIsFresh = observationIsFresh;
        }
    }

    internal sealed class ComputerUseSession {
        internal const int ConsentSeconds = 120;
        private readonly object gate = new object();
        private readonly Func<TimeSpan> clock;
        private TimeSpan expires;
        private ComputerUseState state;
        private ComputerUsePermit permit;
        private int completedSteps;

        internal ComputerUseSession() : this(() => StopwatchClock.Elapsed) { }
        private static readonly Stopwatch StopwatchClock = Stopwatch.StartNew();

        internal ComputerUseSession(Func<TimeSpan> clock) { this.clock = clock; }

        internal ComputerUseState State {
            get { lock (gate) { Expire(); return state; } }
        }

        internal int SecondsRemaining {
            get {
                lock (gate) {
                    Expire();
                    return state == ComputerUseState.Active ? Math.Max(0, (int)Math.Ceiling((expires - clock()).TotalSeconds)) : 0;
                }
            }
        }

        internal bool Allow() {
            lock (gate) {
                if (state != ComputerUseState.Pending) return false;
                expires = clock().Add(TimeSpan.FromSeconds(ConsentSeconds));
                state = ComputerUseState.Active;
                return true;
            }
        }

        internal void Shorten(TimeSpan remaining) {
            lock (gate) {
                if (state != ComputerUseState.Active) return;
                var limit = clock().Add(remaining);
                if (limit < expires) expires = limit;
                Expire();
            }
        }

        internal ComputerUsePermit Arm(ComputerUseStep step, string text, Func<bool> observationIsFresh = null) {
            lock (gate) {
                Expire();
                if (state != ComputerUseState.Active || permit != null || completedSteps != (int)step) return null;
                permit = new ComputerUsePermit(step, text, observationIsFresh);
                return permit;
            }
        }

        internal ComputerUsePermit Consume(ComputerUseStep step) {
            lock (gate) {
                Expire();
                if (state != ComputerUseState.Active || permit == null || permit.Consumed || permit.Step != step) return null;
                if (permit.ObservationIsFresh != null && !permit.ObservationIsFresh()) {
                    permit.ObservationExpired = true;
                    permit.Result.TrySetResult(false);
                    permit = null;
                    return null;
                }
                permit.Consumed = true;
                return permit;
            }
        }

        internal void Report(ComputerUsePermit used, bool applied) {
            lock (gate) {
                Expire();
                if (state != ComputerUseState.Active || used == null || permit != used || !used.Consumed) return;
                if (!applied) { Close(ComputerUseState.Failed); return; }
                completedSteps++;
                permit = null;
                used.Result.TrySetResult(true);
            }
        }

        internal ComputerUseState Finish(bool verified) {
            lock (gate) {
                Expire();
                if (state == ComputerUseState.Active)
                    Close(verified && completedSteps == 2 ? ComputerUseState.Verified : ComputerUseState.Failed);
                return state;
            }
        }

        internal ComputerUseState Complete() {
            lock (gate) {
                Expire();
                if (state == ComputerUseState.Active) Close(ComputerUseState.Completed);
                return state;
            }
        }

        internal void Stop() {
            lock (gate) {
                Expire();
                if (state == ComputerUseState.Active || state == ComputerUseState.Pending) Close(ComputerUseState.Stopped);
            }
        }

        private void Expire() {
            if (state == ComputerUseState.Active && clock() >= expires) Close(ComputerUseState.Expired);
        }

        private void Close(ComputerUseState terminal) {
            state = terminal;
            if (permit != null) permit.Result.TrySetResult(false);
            permit = null;
        }
    }
}
