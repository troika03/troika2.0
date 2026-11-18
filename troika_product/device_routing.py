"""Bind screen control to the device requested in the current user turn."""

import re


DEVICE_ROUTING_GUIDANCE = (
    "Для работы внутри приложения (прочитать экран, нажать, написать, прокрутить) "
    "загрузи capability control и troika_device_control, начни с action=look. "
    "phone — только отдельные базовые команды Android; screen — отдельный снимок экрана, "
    "а не управление. Недоступный screen не означает недоступный control. "
    "По умолчанию device=this: устройство, с которого пришёл текущий запрос. "
    "Не выбирай ПК потому, что он онлайн, упомянут в истории или удобнее. "
    "Другое устройство допустимо только по явному указанию в текущей просьбе. "
    "При отсутствии связи не переноси задачу на другое устройство."
)

_DEVICES = {
    "pc": r"(?:пк|компьютер\w*|комп\w*|ноутбук\w*|pc|computer|laptop|desktop)",
    "phone": r"(?:телефон\w*|смартфон\w*|андроид\w*|phone|smartphone|android)",
}
_QUOTED = re.compile(r'"[^"\n]*"|«[^»]*»|“[^”]*”|`[^`]*`|\'[^\'\n]*\'')


def requested_target(message):
    """Conservative explicit destination; history and quoted text cannot choose it.

    This only narrows routing. The existing device approval remains mandatory.
    Unclear destinations require clarification, never an arbitrary online device.
    """
    if not isinstance(message, str):
        return "this"
    text = _QUOTED.sub(" ", message).casefold()
    targets = set()
    for target, noun in _DEVICES.items():
        pattern = rf"\b(?:на|on|управляй|управлять|control)\s+(?:(?:мо[её]м|моим|my|the)\s+)?{noun}\b"
        for match in re.finditer(pattern, text):
            # A negated destination is not permission to route there.
            if re.search(r"\b(?:не|not)\s*$", text[max(0, match.start() - 12):match.start()]):
                continue
            targets.add(target)
    return next(iter(targets)) if len(targets) == 1 else "ambiguous" if targets else "this"


def route_context(registry, principal, context=None):
    device = next((item for item in registry.list_devices(principal)
                   if item.id == principal.device_id and item.status == "active"), None)
    origin = {"android": "phone", "windows": "pc"}.get(getattr(device, "platform", None), "unsupported")
    target = getattr(context, "control_target", "this")
    if target not in {"this", "phone", "pc", "ambiguous"}:
        target = "this"
    return {"origin": origin, "target": target}


def control_arguments(arguments, route):
    """Reject a model-selected destination that the current turn did not request."""
    target = route["target"]
    if target == "ambiguous":
        return None, {"ok": False, "error": "device_target_ambiguous",
                      "hint": "Уточни, на каком устройстве выполнить действие. Ничего не отправлено."}
    proposed = arguments.get("device", "this")
    effective = route["origin"] if target == "this" else target
    if proposed not in {"this", target, effective}:
        return None, {"ok": False, "error": "device_target_mismatch",
                      "hint": f"Текущая просьба относится к device={target}. Используй его; другое устройство не запрошено."}
    # Same-platform requests remain bound to this exact device, even offline.
    selected = "this" if effective == route["origin"] else target
    return {**arguments, "device": selected}, None
