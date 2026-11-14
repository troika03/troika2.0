"""Validated operator settings. Credentials live outside the checkout."""

from dataclasses import dataclass
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

import yaml

from hermes_constants import get_hermes_home


@dataclass(frozen=True)
class Settings:
    shop_username: str
    support_username: str
    operator_ids: tuple[int, ...]
    operator_chat_id: int
    website: str
    assets: Path
    state: Path
    shop_token: str
    support_token: str
    encryption_key: str

    @classmethod
    def load(cls, path: Path):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Bot settings must be a mapping")
        if data.get("payments_enabled", False) is not False:
            raise ValueError("Payments are not released; keep payments_enabled: false")
        names = [data.get(key, "") for key in ("shop_username", "support_username")]
        if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", name) or not name.lower().endswith("bot") for name in names):
            raise ValueError("Two valid BotFather usernames are required")
        if names[0].lower() == names[1].lower():
            raise ValueError("Shop and support must be separate bots")
        operators = data.get("operator_ids", [])
        if not operators or any(type(value) is not int or value <= 0 for value in operators):
            raise ValueError("Explicit numeric operator_ids are required")
        chat = data.get("operator_chat_id", operators[0])
        if type(chat) is not int or not chat or (chat > 0 and chat not in operators):
            raise ValueError("Operator inbox must be an operator or a private group")
        website = data.get("website", "https://cm444726.tw1.ru").rstrip("/")
        url = urlsplit(website)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment or url.path:
            raise ValueError("Website must be a plain HTTPS origin")
        secrets = [os.environ.get(key, "") for key in ("TROIKA_SHOP_BOT_TOKEN", "TROIKA_SUPPORT_BOT_TOKEN", "TROIKA_TELEGRAM_ENCRYPTION_KEY")]
        if any(not re.fullmatch(r"\d{7,}:[A-Za-z0-9_-]{30,}", token) for token in secrets[:2]):
            raise ValueError("Set both Telegram bot tokens in the private environment")
        if secrets[0] == secrets[1]:
            raise ValueError("Separate bot credentials are required")
        from cryptography.fernet import Fernet

        Fernet(secrets[2].encode("ascii"))
        assets = Path(data.get("assets", Path(__file__).parent / "assets"))
        state = Path(data.get("state_directory", get_hermes_home() / "troika-telegram"))
        return cls(*names, tuple(operators), chat, website, assets, state, *secrets)

    def bot_url(self, role):
        return "https://t.me/" + (self.shop_username if role == "shop" else self.support_username)
