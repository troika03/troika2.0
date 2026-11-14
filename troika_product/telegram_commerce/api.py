"""Bounded Bot API client. Exceptions never contain credential-bearing URLs."""

import json
from pathlib import Path

import aiohttp


class TelegramError(RuntimeError):
    def __init__(self, code, retry_after=None):
        self.code, self.retry_after = code, retry_after
        super().__init__(f"Telegram API error {code}")


class Telegram:
    def __init__(self, session, token, assets: Path):
        self.session, self.token, self.assets = session, token, assets

    async def call(self, method, payload):
        body = dict(payload)
        photo = body.pop("_photo", None)
        profile = body.pop("_profile_photo", None)
        body.pop("_ticket_id", None)
        file = None
        try:
            if photo or profile:
                photo = photo or profile
                # Only shipped asset names are accepted, never a customer path.
                if photo not in {"welcome.jpg", "support.jpg", "plans.jpg", "shop-avatar.jpg", "support-avatar.jpg"}:
                    raise ValueError("Unknown bot asset")
                file = (self.assets / photo).open("rb")
                form = aiohttp.FormData()
                for key, value in body.items():
                    form.add_field(key, json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list, bool)) else str(value))
                form.add_field("avatar" if profile else "photo", file, filename=photo, content_type="image/jpeg")
                request = {"data": form}
            else:
                request = {"json": body}
            async with self.session.post("https://api.telegram.org/bot" + self.token + "/" + method, **request, timeout=aiohttp.ClientTimeout(total=45), allow_redirects=False) as response:
                raw = await response.content.read(8_000_001)
                if len(raw) > 8_000_000:
                    raise TelegramError(502)
                value = json.loads(raw)
                if not value.get("ok"):
                    raise TelegramError(value.get("error_code", response.status), value.get("parameters", {}).get("retry_after"))
                return value["result"]
        except (aiohttp.ClientError, TimeoutError, json.JSONDecodeError):
            raise TelegramError(503) from None
        finally:
            if file:
                file.close()
