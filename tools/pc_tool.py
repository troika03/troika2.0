"""
PC control tools — Тройка управляет самим ПК (Windows), local-first.

В отличие от ``android_tool`` (который шлёт команды на телефон через
``phone_bridge``), здесь мозг и машина — на одном ПК, поэтому мост НЕ нужен:
хендлеры исполняются прямо в процессе gateway.

Два пути (см. docs/TROIKA_PC_AGENT_PLAN.md):
- путь А (надёжный): генерация файла существующими tools + ``pc_open_file`` /
  ``pc_open_app`` чтобы показать результат на экране;
- путь Б (живое управление): ``pc_gui_control`` — клик/ввод/скриншот через
  pyautogui (ставится отдельно: ``pip install pyautogui``).

Все хендлеры принимают ``**_kw`` (иначе registry падает на task_id —
см. память tool-handler-kwargs). Хендлеры синхронные: локальные операции
быстрые, WebSocket-ожидания тут нет.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any, Dict

from tools.registry import registry


# ---------------------------------------------------------------------------
# check_fn — PC-tools имеют смысл только когда gateway крутится на Windows.
# На Linux-VPS (мозг в облаке) они просто не показываются.
# ---------------------------------------------------------------------------

def _check_pc_available() -> bool:
    return os.name == "nt"


def _ok(**data: Any) -> str:
    return json.dumps({"ok": True, **data}, ensure_ascii=False)


def _err(msg: str, **data: Any) -> str:
    return json.dumps({"ok": False, "error": msg, **data}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Известные приложения: русские/английские имена → как запускать.
# Значение — либо имя exe (ищем через shutil.which / App Paths), либо None
# (тогда отдаём Windows-shell `start <name>`, который резолвит по реестру).
# ---------------------------------------------------------------------------

_KNOWN_APPS: Dict[str, str] = {
    "блокнот": "notepad", "notepad": "notepad",
    "калькулятор": "calc", "calc": "calc", "calculator": "calc",
    "проводник": "explorer", "explorer": "explorer", "файлы": "explorer",
    "браузер": "chrome", "хром": "chrome", "chrome": "chrome",
    "edge": "msedge", "эдж": "msedge",
    "word": "winword", "ворд": "winword",
    "powerpoint": "powerpnt", "поинт": "powerpnt", "презентация": "powerpnt",
    "excel": "excel", "эксель": "excel",
    "paint": "mspaint", "пейнт": "mspaint",
    "cmd": "cmd", "терминал": "cmd", "powershell": "powershell",
    "spotify": "spotify", "спотифай": "spotify",
    "telegram": "telegram", "телеграм": "telegram",
    "настройки": "ms-settings:", "settings": "ms-settings:",
}


def _handle_open_app(args: Dict[str, Any], **_kw) -> str:
    name = (args.get("app") or args.get("name") or "").strip()
    if not name:
        return _err("missing 'app'")

    key = name.lower()
    target = _KNOWN_APPS.get(key, name)

    # ms-settings: и подобные URI — открываем через explorer
    if target.endswith(":"):
        try:
            os.startfile(target)  # type: ignore[attr-defined]
            return _ok(opened=target)
        except Exception as e:  # noqa: BLE001
            return _err(f"open_failed: {e}", target=target)

    # Пытаемся найти exe в PATH / App Paths
    exe = shutil.which(target) or shutil.which(target + ".exe")
    try:
        if exe:
            subprocess.Popen([exe])  # noqa: S603
            return _ok(launched=exe)
        # Фолбэк: Windows-shell `start` резолвит многое по реестру App Paths.
        # start — встроенная команда cmd, поэтому через cmd /c.
        subprocess.Popen(["cmd", "/c", "start", "", target], shell=False)  # noqa: S603,S607
        return _ok(launched_via_shell=target)
    except Exception as e:  # noqa: BLE001
        return _err(f"launch_failed: {e}", target=target)


def _handle_open_file(args: Dict[str, Any], **_kw) -> str:
    """Открыть файл/папку в дефолтной программе Windows (показ результата пути А)."""
    path = (args.get("path") or args.get("file") or "").strip().strip('"')
    if not path:
        return _err("missing 'path'")
    if not os.path.exists(path):
        return _err(f"not_found: {path}")
    try:
        os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606
        return _ok(opened=path)
    except Exception as e:  # noqa: BLE001
        return _err(f"open_failed: {e}", path=path)


def _handle_gui_control(args: Dict[str, Any], **_kw) -> str:
    """Живое управление экраном (путь Б): click/type/hotkey/press/move/screenshot.

    Требует ``pip install pyautogui``. Хрупкий путь — использовать только когда
    задача не сводится к генерации файла.
    """
    action = (args.get("action") or "").strip().lower()
    if not action:
        return _err("missing 'action' (click|type|hotkey|press|move|screenshot)")

    try:
        import pyautogui  # type: ignore
    except Exception:  # noqa: BLE001
        return _err("pyautogui_not_installed", hint="pip install pyautogui")

    pyautogui.FAILSAFE = True
    try:
        if action == "click":
            x, y = args.get("x"), args.get("y")
            clicks = int(args.get("clicks", 1))
            button = args.get("button", "left")
            if x is None or y is None:
                pyautogui.click(clicks=clicks, button=button)
            else:
                pyautogui.click(int(x), int(y), clicks=clicks, button=button)
            return _ok(action="click", x=x, y=y)

        if action == "type":
            text = args.get("text") or ""
            if not text:
                return _err("missing 'text'")
            pyautogui.typewrite(text, interval=float(args.get("interval", 0.02)))
            return _ok(action="type", chars=len(text))

        if action == "hotkey":
            keys = args.get("keys") or args.get("combo") or ""
            parts = keys.split("+") if isinstance(keys, str) else list(keys)
            parts = [p.strip() for p in parts if p.strip()]
            if not parts:
                return _err("missing 'keys' (e.g. 'ctrl+s')")
            pyautogui.hotkey(*parts)
            return _ok(action="hotkey", keys=parts)

        if action == "press":
            key = args.get("key") or ""
            if not key:
                return _err("missing 'key'")
            pyautogui.press(key, presses=int(args.get("presses", 1)))
            return _ok(action="press", key=key)

        if action == "move":
            x, y = args.get("x"), args.get("y")
            if x is None or y is None:
                return _err("move needs 'x' and 'y'")
            pyautogui.moveTo(int(x), int(y), duration=float(args.get("duration", 0.2)))
            return _ok(action="move", x=x, y=y)

        if action == "screenshot":
            import tempfile
            import time
            path = args.get("path") or os.path.join(
                tempfile.gettempdir(), f"troika_screen_{int(time.time())}.png"
            )
            pyautogui.screenshot(path)
            return _ok(action="screenshot", path=path)

        return _err(f"unknown_action: {action}")
    except Exception as e:  # noqa: BLE001
        return _err(f"gui_failed: {e}", action=action)


def _handle_run(args: Dict[str, Any], **_kw) -> str:
    """Быстрые системные действия: громкость, свернуть окна, буфер обмена."""
    action = (args.get("action") or "").strip().lower()
    if not action:
        return _err("missing 'action' (volume_up|volume_down|mute|minimize_all|"
                    "clipboard_get|clipboard_set)")

    try:
        if action in ("volume_up", "volume_down", "mute"):
            try:
                import pyautogui  # type: ignore
            except Exception:  # noqa: BLE001
                return _err("pyautogui_not_installed", hint="pip install pyautogui")
            key = {"volume_up": "volumeup", "volume_down": "volumedown",
                   "mute": "volumemute"}[action]
            presses = int(args.get("amount", 1)) if action != "mute" else 1
            pyautogui.press(key, presses=presses)
            return _ok(action=action)

        if action == "minimize_all":
            try:
                import pyautogui  # type: ignore
            except Exception:  # noqa: BLE001
                return _err("pyautogui_not_installed", hint="pip install pyautogui")
            pyautogui.hotkey("win", "d")
            return _ok(action="minimize_all")

        if action == "clipboard_get":
            text = _clipboard_get()
            return _ok(action="clipboard_get", text=text)

        if action == "clipboard_set":
            _clipboard_set(args.get("text") or "")
            return _ok(action="clipboard_set")

        return _err(f"unknown_action: {action}")
    except Exception as e:  # noqa: BLE001
        return _err(f"run_failed: {e}", action=action)


def _capture_screen(path: str, monitor: int = 1, region=None) -> Dict[str, Any]:
    """Снять экран в PNG. mss надёжнее pyautogui на мультимониторах.

    monitor: индекс монитора mss (0 = все вместе, 1 = основной). region:
    [x, y, w, h] — снять кусок экрана. Возвращает {width, height}.
    """
    import mss
    import mss.tools

    with mss.mss() as sct:
        mons = sct.monitors  # [0]=виртуальный «все», [1..]=реальные
        if region and len(region) == 4:
            x, y, w, h = region
            bbox = {"left": int(x), "top": int(y), "width": int(w), "height": int(h)}
        else:
            idx = int(monitor)
            if idx < 0 or idx >= len(mons):
                idx = 1 if len(mons) > 1 else 0
            bbox = mons[idx]
        shot = sct.grab(bbox)
        mss.tools.to_png(shot.rgb, shot.size, output=path)
        return {"width": shot.width, "height": shot.height}


async def _handle_see_screen(args: Dict[str, Any], **_kw) -> str:
    """Тройка «смотрит» на экран: снимок → vision-модель отвечает на вопрос.

    Путь как у android_screenshot: сохраняем PNG и зовём vision_analyze.
    analyze=false → просто вернуть путь к скриншоту без разбора.
    """
    import tempfile
    import time

    path = args.get("path") or os.path.join(
        tempfile.gettempdir(), f"troika_screen_{int(time.time())}.png"
    )
    try:
        meta = _capture_screen(
            path,
            monitor=int(args.get("monitor", 1)),
            region=args.get("region"),
        )
    except Exception as e:  # noqa: BLE001
        return _err(f"capture_failed: {e}")

    if args.get("analyze") is False:
        return _ok(action="see_screen", screenshot_path=path, **meta)

    question = (
        args.get("question")
        or args.get("prompt")
        or "Что сейчас на экране? Опиши кратко и по делу."
    )
    try:
        from tools.vision_tools import _handle_vision_analyze

        analysis = await _handle_vision_analyze(
            {"image_url": path, "question": question}
        )
        return _ok(
            action="see_screen",
            screenshot_path=path,
            question=question,
            analysis=analysis,
            **meta,
        )
    except Exception as e:  # noqa: BLE001
        return _err(f"vision_failed: {e}", screenshot_path=path)


def _clipboard_get() -> str:
    # Через временный файл в UTF-8 — консольный вывод PowerShell калечит кириллицу
    # (память powershell-utf8-body).
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    try:
        subprocess.run(  # noqa: S603
            ["powershell", "-NoProfile", "-Command",
             f"Get-Clipboard -Raw | Set-Content -Path '{tmp}' -Encoding UTF8 -NoNewline"],
            timeout=10,
        )
        with open(tmp, encoding="utf-8-sig") as f:
            return f.read()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _clipboard_set(text: str) -> None:
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        subprocess.run(  # noqa: S603
            ["powershell", "-NoProfile", "-Command",
             f"Set-Clipboard -Value (Get-Content -Raw -Encoding UTF8 '{tmp}')"],
            timeout=10,
        )
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Схемы
# ---------------------------------------------------------------------------

OPEN_APP_SCHEMA = {
    "name": "pc_open_app",
    "description": (
        "Запустить программу на ПК по имени. Русские и английские имена: "
        "'блокнот', 'калькулятор', 'проводник', 'браузер', 'word', 'powerpoint', "
        "'excel', 'spotify', 'настройки'. «Открой …», «запусти …»."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "app": {"type": "string", "description": "Имя программы (рус/англ)."},
        },
        "required": ["app"],
    },
}

OPEN_FILE_SCHEMA = {
    "name": "pc_open_file",
    "description": (
        "Открыть файл или папку на ПК в стандартной программе Windows. "
        "Используется чтобы ПОКАЗАТЬ на экране результат (готовую презентацию, "
        "документ, таблицу, картинку). «Открой …», «покажи файл …»."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Полный путь к файлу/папке."},
        },
        "required": ["path"],
    },
}

GUI_CONTROL_SCHEMA = {
    "name": "pc_gui_control",
    "description": (
        "Живое управление экраном ПК: клик мышью, ввод текста, горячие клавиши, "
        "скриншот. Хрупкий путь — применять только когда задачу нельзя решить "
        "генерацией файла. Требует установленного pyautogui."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["click", "type", "hotkey", "press", "move", "screenshot"],
            },
            "x": {"type": "integer"},
            "y": {"type": "integer"},
            "text": {"type": "string", "description": "Текст для action=type."},
            "keys": {"type": "string", "description": "Комбо для hotkey, напр. 'ctrl+s'."},
            "key": {"type": "string", "description": "Клавиша для press, напр. 'enter'."},
            "clicks": {"type": "integer"},
            "button": {"type": "string", "enum": ["left", "right", "middle"]},
            "path": {"type": "string", "description": "Куда сохранить скриншот."},
        },
        "required": ["action"],
    },
}

SEE_SCREEN_SCHEMA = {
    "name": "pc_see_screen",
    "description": (
        "Тройка СМОТРИТ на экран ПК: делает скриншот и понимает, что на нём. "
        "«Что у меня на экране?», «посмотри на экран», «что здесь написано», "
        "«помоги с тем что вижу». Можно задать конкретный вопрос про экран."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "Что именно спросить про экран. Если пусто — общее описание.",
            },
            "monitor": {
                "type": "integer",
                "description": "Монитор: 1 = основной (по умолч.), 0 = все сразу, 2+ = доп.",
            },
            "region": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Снять кусок экрана [x, y, ширина, высота].",
            },
            "analyze": {
                "type": "boolean",
                "description": "false — только снимок без разбора (вернёт путь).",
            },
        },
        "required": [],
    },
}

RUN_SCHEMA = {
    "name": "pc_run",
    "description": (
        "Быстрые системные действия на ПК: громкость (volume_up/volume_down/mute), "
        "свернуть все окна (minimize_all), буфер обмена (clipboard_get/clipboard_set)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["volume_up", "volume_down", "mute", "minimize_all",
                         "clipboard_get", "clipboard_set"],
            },
            "amount": {"type": "integer", "description": "Шагов громкости."},
            "text": {"type": "string", "description": "Текст для clipboard_set."},
        },
        "required": ["action"],
    },
}


# ---------------------------------------------------------------------------
# Регистрация (toolset "pc"; в toolsets.py добавлен в core + troika-voice)
# ---------------------------------------------------------------------------

registry.register(name="pc_open_app", toolset="pc", schema=OPEN_APP_SCHEMA,
                  handler=_handle_open_app, check_fn=_check_pc_available,
                  is_async=False, emoji="🖥")
registry.register(name="pc_open_file", toolset="pc", schema=OPEN_FILE_SCHEMA,
                  handler=_handle_open_file, check_fn=_check_pc_available,
                  is_async=False, emoji="📂")
registry.register(name="pc_gui_control", toolset="pc", schema=GUI_CONTROL_SCHEMA,
                  handler=_handle_gui_control, check_fn=_check_pc_available,
                  is_async=False, emoji="🖱")
registry.register(name="pc_run", toolset="pc", schema=RUN_SCHEMA,
                  handler=_handle_run, check_fn=_check_pc_available,
                  is_async=False, emoji="🎚")
registry.register(name="pc_see_screen", toolset="pc", schema=SEE_SCREEN_SCHEMA,
                  handler=_handle_see_screen, check_fn=_check_pc_available,
                  is_async=True, emoji="👁")


__all__ = [
    "_handle_open_app",
    "_handle_open_file",
    "_handle_gui_control",
    "_handle_run",
    "_handle_see_screen",
]
