"""Early ordinary narration while completion claims await final verification."""

import re

from troika_product.completion import CompletionEvidence, _CLAIMS, _DONE


class GuardedTextStream:
    """Use the completion guard's lexicon conservatively before any final result.

    This is the same deterministic backstop as completion verification, not a
    semantic verifier. Even a currently proved action is held until the final
    answer; later tool failures must not invalidate something already spoken.
    Reasoning/context scrubbing remains the agent's upstream responsibility.
    """

    _boundary = re.compile(r"[!?…](?:\s|$)|\.\s|(?<=\S)\n")

    def __init__(self, emit, user_message):
        self.emit = emit
        self.user_message = user_message
        self.pending = ""
        self.sent = ""
        self.blocked = False
        self.closed = False

    def feed(self, delta):
        if self.closed or self.blocked or not isinstance(delta, str) or not delta:
            return
        self.pending += delta
        if not self.sent:
            self.pending = self.pending.lstrip()
        while match := self._boundary.search(self.pending):
            # Forward the known separator so speech clients can release a
            # period-terminated sentence before another model phrase arrives.
            phrase = self.pending[:match.end()]
            if not phrase.strip():
                break
            if ("```" in phrase or _DONE.search(phrase)
                    or any(pattern.search(phrase) for pattern in _CLAIMS.values())
                    or CompletionEvidence().unsupported(phrase, self.user_message)):
                self.blocked = True
                self.pending = ""
                return
            self.pending = self.pending[len(phrase):]
            self.sent += phrase
            self.emit(phrase)
            if len(self.sent) >= 65536:
                self.blocked = True
                self.pending = ""
                return
        if len(self.pending) > 4096:
            self.blocked = True
            self.pending = ""

    def finish_result(self, result):
        """Emit only the runtime-checked suffix, once, including buffered providers."""
        if self.closed:
            return
        self.closed = True
        self.pending = ""
        if not isinstance(result, dict):
            return
        result["_product_streamed"] = True
        if result.get("failed") or result.get("error_code") or result.get("completed") is False:
            return
        final = result.get("final_response") or ""
        if not isinstance(final, str) or not final:
            return
        if final.startswith(self.sent):
            suffix = final[len(self.sent):]
        elif self.sent and final.startswith(self.sent.rstrip()):
            # Final formatting may replace the emitted separator with a
            # newline before a footer. Do not repeat the spoken sentence.
            suffix = final[len(self.sent.rstrip()):]
        elif final.rstrip() == self.sent.rstrip():
            suffix = ""
        else:
            # A safe preamble can precede a guard correction. Never append the
            # rejected draft, and never pretend an already spoken word vanished.
            suffix = ("\n" if self.sent else "") + final
        if suffix:
            self.emit(suffix)
