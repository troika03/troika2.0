"""One bounded OpenRouter request for a reviewed Windows test frame."""

import json
import re
import time

import httpx

from troika_product.computer_control import ComputerControlError


_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
_MAX_REPLY_BYTES = 64 * 1024
_MODEL_ID = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?::free)?\Z")


class OpenRouterVision:
    def __init__(self, model, key):
        if (not isinstance(model, str) or len(model) > 160 or not _MODEL_ID.fullmatch(model)
                or model.casefold().startswith("openrouter/")):
            raise ValueError("set a specific OpenRouter vision model")
        if not isinstance(key, str) or not key or any(character.isspace() for character in key):
            raise ValueError("set OPENROUTER_API_KEY")
        self.model = model
        self._key = key

    @staticmethod
    def _client(timeout):
        return httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False)

    def describe(self, instruction, content, remaining):
        reply = self._complete({
            "messages": [{"role": "system", "content": instruction}, {"role": "user", "content": content}],
        }, remaining)
        try:
            choice = reply["choices"][0]
            content = choice["message"]["content"]
            if "error" in reply or choice["finish_reason"] != "stop" or not isinstance(content, str):
                raise ValueError
            summary = " ".join(content.split())
            if (not summary or "data:image/" in summary.casefold()
                    or any(ord(character) < 32 or 127 <= ord(character) < 160 for character in summary)):
                raise ValueError
        except (ValueError, KeyError, IndexError, TypeError):
            raise ComputerControlError("openrouter_invalid_reply") from None
        return summary if len(summary) <= 600 else summary[:599].rstrip() + "…"

    def tool_step(self, payload, remaining, tool_name):
        from openai.types.chat import ChatCompletion

        tools = payload.get("tools", [])
        if [tool.get("function", {}).get("name") for tool in tools] != [tool_name]:
            raise ComputerControlError("computer_tool_unavailable")
        reply = self._complete({"messages": payload["messages"], "tools": tools,
                                "tool_choice": "auto", "parallel_tool_calls": False}, remaining)
        try:
            choice = reply["choices"][0]
            message = choice["message"]
            reason = choice["finish_reason"]
            calls = message.get("tool_calls") or []
            if "error" in reply or reason not in {"stop", "tool_calls"} or len(calls) != (reason == "tool_calls"):
                raise ValueError
            normalized = {"role": "assistant", "content": None if calls else "Проверка действий завершена."}
            if calls:
                call = calls[0]
                function = call["function"]
                arguments = function["arguments"]
                if (function["name"] != tool_name or call["type"] != "function"
                        or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", call["id"])
                        or not isinstance(arguments, str) or len(arguments) > 4096):
                    raise ValueError
                normalized["tool_calls"] = [{"id": call["id"], "type": "function", "function": function}]
            return ChatCompletion.model_validate({
                "id": "computer-use-step", "object": "chat.completion", "created": 0, "model": self.model,
                "choices": [{"index": 0, "finish_reason": reason, "message": normalized}],
            })
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise ComputerControlError("openrouter_invalid_reply") from None

    def _complete(self, parameters, remaining):
        timeout = min(12, remaining)
        if timeout <= 0:
            raise ComputerControlError("frame_expired")
        deadline = time.monotonic() + timeout
        try:
            with self._client(timeout) as client, client.stream(
                "POST", _ENDPOINT, headers={"Authorization": "Bearer " + self._key},
                json={**parameters, "model": self.model, "stream": False, "max_tokens": 320,
                      "provider": {"allow_fallbacks": False, "data_collection": "deny", "zdr": True}},
            ) as response:
                if response.status_code in {401, 403}:
                    raise ComputerControlError("openrouter_authentication_failed")
                if response.status_code == 429:
                    raise ComputerControlError("openrouter_rate_limited")
                if response.status_code != 200:
                    raise ComputerControlError("openrouter_unavailable")
                body = bytearray()
                for chunk in response.iter_bytes():
                    if time.monotonic() >= deadline:
                        raise ComputerControlError("openrouter_timeout")
                    if len(body) + len(chunk) > _MAX_REPLY_BYTES:
                        raise ComputerControlError("openrouter_invalid_reply")
                    body.extend(chunk)
        except httpx.TimeoutException:
            raise ComputerControlError("openrouter_timeout") from None
        except httpx.HTTPError:
            raise ComputerControlError("openrouter_unavailable") from None
        try:
            return json.loads(body)
        except ValueError:
            raise ComputerControlError("openrouter_invalid_reply") from None
