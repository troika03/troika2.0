"""Customer copy and keyboards. No unverified release promises.

Plan names, prices and limits come only from ``troika_product.subscription_policy``.
This module adds presentation (icons, short taglines) and never repeats prices.
"""

from html import escape

from troika_product import subscription_policy as policy


# Bot API 9.4+: InlineKeyboardButton.style colours a button. Older clients
# ignore the field and draw the default button, so it is safe to always send.
PRIMARY, SUCCESS, DANGER = "primary", "success", "danger"

PLAN_LOOK = {
    "free": ("🌱", "Попробовать голосового помощника", SUCCESS),
    "plus": ("⚡", "Для ежедневных дел", None),
    "pro": ("🚀", "Для проектов и разработки", PRIMARY),
}
FEATURES = (
    ("voice", "🎙", "Голосовое общение"),
    ("search", "🔎", "Поиск в интернете"),
    ("documents", "📄", "Документы и презентации"),
    ("snapshot", "🖼", "Снимки экрана"),
    ("deep_research", "🧭", "Глубокое исследование"),
    ("development", "🛠", "Разработка проектов"),
    ("premium", "💎", "Премиальные модели"),
)

TOPICS = {"start": "Установка и вход", "voice": "Голос и микрофон", "payment": "Тариф и оплата", "bug": "Ошибка приложения", "other": "Другой вопрос"}
TOPIC_ICONS = {"start": "📲", "voice": "🎙", "payment": "💳", "bug": "🐞", "other": "💬"}
# Public deep links: t.me/<support>?start=<payload>.
DEEP_LINKS = {"payment": "payment", "install": "start", "voice": "voice", "bug": "bug"}
FAQ = {
    "install": ("📲 Как начать?", "Скачайте Тройку с официального сайта, установите и создайте аккаунт. На телефоне и ПК входите в один аккаунт. Разрешение на микрофон нужно для голосового ввода."),
    "devices": ("🔗 Как подключить второе устройство?", "Установите Тройку на второе устройство и войдите в тот же аккаунт. История, память и дела связаны с аккаунтом. Новые документы сохраняются на устройстве, где их создали."),
    "voice": ("🎙 Тройка не слышит", "Проверьте разрешение на микрофон, интернет и выбранный аудиовыход. Попробуйте кнопку микрофона в приложении. Для фонового пробуждения на Android отдельно проверьте настройки батареи."),
    "resource": ("📊 Как расходуется ресурс?", "Ресурс обновляется каждый месяц. Учитывается весь контекст AI-запроса и ответ, поэтому число сообщений не равно расходу. Остаток виден в профиле приложения. Локальные команды AI-ресурс не расходуют."),
    "files": ("📁 Где мои документы?", "Новые файлы сохраняются на вашем устройстве. Откройте раздел «Файлы» и завершите сохранение. Автоматическое восстановление локальных документов после переустановки не обещается."),
    "payment": ("💳 Как оплатить тариф?", "Оплату пока подключаем: ни бот, ни сайт сейчас деньги не принимают и ничего не списывают. Перед запуском покажем стоимость, срок, продление и условия возврата. Не отправляйте данные карты, пароли и коды подтверждения."),
}
STATUS = {"waiting": "🟡 ждёт оператора", "answered": "🔵 есть ответ", "closed": "✅ закрыто"}


def button(text, callback=None, url=None, style=None):
    value = {"text": text, **({"url": url} if url else {"callback_data": callback})}
    if style:
        value["style"] = style
    return value


def keyboard(*rows):
    return {"inline_keyboard": [row for row in rows if row]}


def home_row():
    return [button("🏠 Главное меню", "home")]


def topic_label(key):
    return f"{TOPIC_ICONS.get(key, '💬')} {TOPICS.get(key, 'Обращение')}"


def tokens_label(value):
    if value >= 1_000_000:
        number = f"{value / 1_000_000:.1f}".rstrip("0").rstrip(".").replace(".", ",")
        return number + " млн"
    if value >= 1000:
        return f"{value // 1000} тыс."
    return str(value)


def price_label(rub):
    return "Бесплатно" if not rub else f"{rub:,}".replace(",", " ") + " ₽/мес"


def plans():
    """Plans in price order, straight from the approved policy."""
    return sorted(policy.PLANS.values(), key=lambda plan: (plan.price_rub, plan.name))


def look(plan):
    icon, tagline, _ = PLAN_LOOK.get(plan.name, ("⭐", "", None))
    return icon, plan.name.capitalize(), tagline


def plan_features(plan):
    lines = []
    for feature, icon, title in FEATURES:
        limit = plan.feature_limit(feature)
        if limit is None:
            lines.append(f"{icon} {title}")
        elif limit > 0:
            lines.append(f"{icon} {title} — до {limit} в месяц")
    if plan.concurrent_runs > 1:
        lines.append(f"⚙️ До {plan.concurrent_runs} активных задач одновременно")
    return lines


def plans_text():
    lines = ["<b>💎 Тарифы Тройки</b>", ""]
    for plan in plans():
        icon, name, tagline = look(plan)
        lines.append(f"{icon} <b>{name}</b> — {price_label(plan.price_rub)}")
        lines.append(f"      {tokens_label(plan.monthly_tokens)} AI-токенов в месяц" + (f" · {tagline.lower()}" if tagline else ""))
    lines += [
        "",
        f"➕ Докупка: {tokens_label(policy.TOP_UP_TOKENS)} за {policy.TOP_UP_PRICE_RUB} ₽, действует {policy.TOP_UP_DAYS} дней.",
        "",
        "<i>Оплату подключаем — сейчас деньги не списываются. Free доступен сразу.</i>",
    ]
    return "\n".join(lines)


def plan_text(plan):
    icon, name, tagline = look(plan)
    text = [f"<b>{icon} Тройка {name}</b>"]
    if tagline:
        text.append(f"<i>{tagline}</i>")
    text += ["", f"💰 <b>{price_label(plan.price_rub)}</b>", f"🔋 {tokens_label(plan.monthly_tokens)} AI-токенов в месяц", "", "<b>Что входит</b>", *plan_features(plan), ""]
    if plan.price_rub:
        text.append("Оплату подключаем — сейчас деньги не списываются. Можно получить одно уведомление о старте продаж.")
    else:
        text.append("Установите приложение и создайте аккаунт — оплата не нужна.")
    return "\n".join(text)


def home(settings, role):
    if role == "shop":
        return ("<b>Тройка — от слов к делу</b>\n\nГолосовой помощник для Android и Windows: разговор, поиск, документы и ваши дела.\n\n🌱 Начните бесплатно — оплата не нужна.\n👇 Выберите, что нужно", keyboard(
            [button("💎 Тарифы", "plans", style=PRIMARY), button("📲 Скачать", "download", style=SUCCESS)],
            [button("🔗 Подключить устройство", "device")],
            [button("💳 Оплата", "pay"), button("✨ О Тройке", "about")],
            [button("🛟 Помощь", "help")],
        ))
    return ("<b>🛟 Поддержка Тройки</b>\n\nПоможем с установкой, голосом, аккаунтом и тарифом.\n👇 Найдите ответ или напишите оператору\n\n🔒 Пароли, ключи и коды подтверждения присылать не нужно.", keyboard(
        [button("✍️ Написать оператору", "contact", style=PRIMARY)],
        [button("💡 Частые вопросы", "faq"), button("📋 Мои обращения", "tickets")],
        [button("📶 Статус сервиса", url=settings.website + "/status/")],
        [button("💎 Тарифы и приложение", url=settings.bot_url("shop"))],
    ))


def download_buttons(settings):
    return [button("🤖 Android", url=settings.website + "/download/#android", style=SUCCESS), button("🪟 Windows", url=settings.website + "/download/#windows", style=SUCCESS)]


def screen(settings, role, action):
    """Return (html, reply_markup, photo or None) for a navigation action."""
    if action == "home":
        return (*home(settings, role), "welcome.jpg" if role == "shop" else "support.jpg")
    if role == "shop":
        found = shop_screen(settings, action)
        if found:
            return found
    elif action == "faq":
        return "<b>💡 Частые вопросы</b>\n\nВыберите вопрос 👇", keyboard(*[[button(title, "faq:" + key)] for key, (title, _) in FAQ.items()], [button("✍️ Написать оператору", "contact", style=PRIMARY)], home_row()), None
    elif action.startswith("faq:") and action[4:] in FAQ:
        title, text = FAQ[action[4:]]
        return f"<b>{escape(title)}</b>\n\n{text}", keyboard([button("✍️ Написать оператору", "contact", style=PRIMARY)], [button("← Другие вопросы", "faq")], home_row()), None
    elif action == "contact":
        return "<b>✍️ С чем нужна помощь?</b>\n\nВыберите тему — затем опишите проблему одним сообщением.", keyboard(*[[button(topic_label(key), "topic:" + key)] for key in TOPICS], home_row()), None
    return "⌛ Кнопка устарела. Откройте главное меню.", keyboard(home_row()), None


def shop_screen(settings, action):
    support = settings.bot_url("support")
    if action == "plans":
        return plans_text(), keyboard(
            *[[button(f"{look(plan)[0]} {look(plan)[1]} — подробнее", "plan:" + plan.name, style=PLAN_LOOK.get(plan.name, (None, None, None))[2])] for plan in plans()],
            [button("💳 Как оплатить", "pay")],
            home_row(),
        ), "plans.jpg"
    if action.startswith("plan:") and action[5:] in policy.PLANS:
        plan = policy.PLANS[action[5:]]
        if plan.price_rub:
            rows = [[button("🔔 Сообщить о старте продаж", "waitlist", style=PRIMARY)]]
        else:
            rows = [download_buttons(settings), [button("👤 Создать аккаунт", url=settings.website + "/account/?mode=register", style=PRIMARY)]]
        return plan_text(plan), keyboard(*rows, [button("← Все тарифы", "plans")], home_row()), None
    if action == "pay":
        return ("<b>💳 Оплата</b>\n\nОплату пока подключаем: ни бот, ни сайт сейчас деньги не принимают и ничего не списывают.\n\n🌱 Free доступен сразу — для начала оплата не нужна.\n📋 Перед покупкой покажем стоимость, срок, продление и условия возврата.\n\n🔔 Хотите узнать о старте продаж первым? Включите одно уведомление.", keyboard(
            [button("🔔 Сообщить о старте продаж", "waitlist", style=PRIMARY)],
            [button("📄 Условия оплаты", url=settings.website + "/refunds/"), button("💎 Тарифы", "plans")],
            [button("🛟 Вопрос об оплате", url=support + "?start=payment")],
            home_row(),
        ), None)
    if action == "download":
        return ("<b>📲 Скачать Тройку</b>\n\n🤖 <b>Android</b> — голосовые просьбы, дела и файлы под рукой.\n🪟 <b>Windows</b> — вызов по <code>Ctrl+Alt+T</code> прямо во время работы.\n\n🔒 Скачивайте только с официального сайта.", keyboard(
            download_buttons(settings),
            [button("🔗 Как подключить устройство", "device")],
            home_row(),
        ), None)
    if action == "device":
        return ("<b>🔗 Подключить устройство</b>\n\n1️⃣ Скачайте Тройку для Android или Windows.\n2️⃣ Войдите в один и тот же аккаунт на каждом устройстве.\n3️⃣ Разрешите микрофон, чтобы говорить голосом.\n\n✨ История, память и дела общие для аккаунта. Новые документы сохраняются на устройстве, где их создали.\n\n💡 На Windows Тройка открывается по <code>Ctrl+Alt+T</code>.", keyboard(
            download_buttons(settings),
            [button("👤 Создать аккаунт", url=settings.website + "/account/?mode=register", style=PRIMARY)],
            [button("🛟 Не получается подключить", url=support + "?start=install")],
            home_row(),
        ), None)
    if action == "about":
        return ("<b>✨ Скажите, что нужно</b>\n\nТройка помогает найти информацию, подготовить документ, вести дела и продолжить разговор на телефоне или ПК.\n\n🎙 Голос — основной способ общения, текст тоже доступен.\n🧠 Память и история связаны с аккаунтом.\n📄 Новые документы сохраняются на устройстве.\n\nДоступ зависит от тарифа и версии приложения; часть возможностей проходит проверку в beta.", keyboard(
            [button("📲 Скачать", "download", style=SUCCESS), button("💎 Тарифы", "plans")],
            [button("📖 Как начать", url=settings.website + "/help/")],
            home_row(),
        ), "welcome.jpg")
    if action == "help":
        return ("<b>🛟 Помощь</b>\n\nОтветы на частые вопросы и связь с оператором — в боте поддержки.\nСправка с инструкциями — на сайте.", keyboard(
            [button("✍️ Написать в поддержку", url=support, style=PRIMARY)],
            [button("📖 Справка на сайте", url=settings.website + "/help/"), button("👤 Личный кабинет", url=settings.website + "/account/")],
            home_row(),
        ), None)
    return None
