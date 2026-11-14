"""Run both bots or apply their public profile settings."""

import argparse
import asyncio
import logging
import os
from pathlib import Path
import sys

import aiohttp
from dotenv import load_dotenv

from hermes_constants import get_hermes_home
from .api import Telegram, TelegramError
from .config import Settings
from .service import Service
from .store import Store


async def configure(settings, clients):
    for role, client in clients.items():
        shop = role == "shop"
        await client.call("setMyName", {"name": "Тройка | " + ("Магазин" if shop else "Поддержка")})
        await client.call("setMyDescription", {"description": (
            "🎙 Тройка — голосовой помощник для Android и Windows.\n\n💎 Тарифы Free, Plus и Pro\n📲 Скачать приложение\n🔗 Подключить устройство\n🛟 Помощь\n\nОплату подключаем — сейчас деньги не списываются.\n\nПоддержка: @" + settings.support_username
            if shop else "🛟 Поддержка Тройки: установка, аккаунт, голос и тариф.\n\nНажмите «Начать», выберите тему и опишите проблему — оператор ответит в этом чате.\n\n🔒 Не отправляйте пароли, ключи и коды подтверждения."
        )})
        await client.call("setMyShortDescription", {"short_description": "Тарифы, загрузка, подключение устройств и помощь." if shop else "Помощь с Тройкой: установка, голос, аккаунт и тариф."})
        commands = [("start", "Главное меню"), ("tariffs", "Тарифы"), ("download", "Скачать для Android и Windows"), ("device", "Подключить устройство"), ("pay", "Оплата"), ("support", "Помощь"), ("paysupport", "Вопрос об оплате")] if shop else [("start", "Главное меню"), ("support", "Написать оператору"), ("tickets", "Мои обращения"), ("paysupport", "Вопрос об оплате")]
        commands += [("privacy", "Данные и приватность"), ("stop", "Отключить уведомления"), ("delete_me", "Удалить данные ботов")]
        await client.call("setMyCommands", {"commands": [{"command": command, "description": description} for command, description in commands]})
        await client.call("setChatMenuButton", {"menu_button": {"type": "commands"}})
        await client.call("setMyProfilePhoto", {"photo": {"type": "static", "photo": "attach://avatar"}, "_profile_photo": role + "-avatar.jpg"})


async def run(settings, command):
    connector = aiohttp.TCPConnector(limit=8)
    async with aiohttp.ClientSession(connector=connector, trust_env=False) as session:
        clients = {role: Telegram(session, token, settings.assets) for role, token in (("shop", settings.shop_token), ("support", settings.support_token))}
        for role, client in clients.items():
            identity = await client.call("getMe", {})
            expected = settings.shop_username if role == "shop" else settings.support_username
            if identity.get("username", "").lower() != expected.lower():
                raise ValueError("Token and configured bot username do not match")
            webhook = await client.call("getWebhookInfo", {})
            if webhook.get("url"):
                raise ValueError("An existing webhook must be migrated explicitly")
        if command == "profile":
            await configure(settings, clients)
            print("Both bot profiles configured")
            return
        if command == "check":
            print("Both bot credentials verified; payments disabled")
            return
        settings.state.mkdir(parents=True, exist_ok=True)
        store = Store(settings.state / "support.sqlite", settings.encryption_key)
        service = Service(settings, store, clients)
        print("Troika shop and support started; payments disabled", flush=True)
        async with asyncio.TaskGroup() as tasks:
            for role in clients:
                tasks.create_task(service.poll(role))
                tasks.create_task(service.deliveries(role))


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="Troika Telegram shop and support")
    root = get_hermes_home() / "troika-telegram"
    parser.add_argument("--config", type=Path, default=root / "config.yaml")
    parser.add_argument("--secrets", type=Path, default=root / ".env")
    parser.add_argument("command", choices=("run", "profile", "check"), nargs="?", default="run")
    args = parser.parse_args()
    load_dotenv(args.secrets, override=False)
    # HTTP client exceptions contain bot URLs. Never log request objects.
    logging.getLogger("aiohttp").setLevel(logging.CRITICAL)
    try:
        settings = Settings.load(args.config)
        asyncio.run(run(settings, args.command))
    except KeyboardInterrupt:
        return 0
    except (ValueError, OSError, TelegramError) as error:
        # Only our validated errors have safe text. Never print client traces.
        print(str(error) if isinstance(error, (ValueError, TelegramError)) else "Private settings or assets are unavailable", file=sys.stderr)
        return 1
    except Exception:
        print("Bot worker stopped; inspect private state and restart", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
