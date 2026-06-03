"""
gemini_code — делегирует кодинг-задачу Gemini CLI на PC, упаковывает
результат в ZIP, отдаёт на телефон, поднимает preview-сервер, умеет
итерации в существующем workspace и деплой через Vercel CLI.

Операции (через arg `action`):
  • create   (default) — новый проект. Создаёт workspace, запускает Gemini,
              опционально открывает preview + отдаёт ZIP на телефон.
  • iterate  — продолжение в последнем (или указанном) workspace.
              «доделай меню», «поменяй цвета на тёмные», «добавь анимацию».
  • preview  — поднять (или вернуть URL) preview-сервер для workspace.
  • deploy   — деплой workspace через `vercel --prod` (нужен vercel CLI + логин).
  • last     — вернуть путь и список файлов последнего workspace.

State: ~/.troika/workspaces/_last_workspace.json — указывает на последний
проект, чтобы iterate/preview/deploy без аргументов работали как "в текущем".

Preview-сервер:
  Один процесс на gateway лайвтайм, http.server в отдельной thread'е,
  слушает на 0.0.0.0:<port> где port = 7800 + hash(workspace) % 100.
  Возвращает Tailscale-URL (100.114.51.123:port).
"""

from __future__ import annotations

import asyncio
import base64
import http.server
import json
import logging
import os
import re
import shutil
import socket
import socketserver
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from tools.registry import registry

logger = logging.getLogger(__name__)


_TROIKA_HOME = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".troika"))
_WORKSPACES = _TROIKA_HOME / "workspaces"
_LAST_STATE = _WORKSPACES / "_last_workspace.json"
_DEFAULT_TIMEOUT = 300

# Один реестр активных preview-серверов на процесс gateway.
# key: workspace path → {"port": int, "thread": Thread, "httpd": server}
_PREVIEW_SERVERS: Dict[str, Dict[str, Any]] = {}
_PREVIEW_LOCK = threading.Lock()


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-zа-яё0-9\-_ ]+", "", text)
    text = re.sub(r"\s+", "-", text)
    return text[:40] or "task"


def _find_cli(name: str) -> Optional[str]:
    """Найти CLI: PATH → npm global → None."""
    found = shutil.which(name) or shutil.which(f"{name}.cmd") or shutil.which(f"{name}.exe")
    if found:
        return found
    for candidate in [
        Path(rf"C:\nvm4w\nodejs\{name}.cmd"),
        Path(rf"C:\nvm4w\nodejs\{name}.exe"),
        Path.home() / "AppData" / "Roaming" / "npm" / f"{name}.cmd",
        Path.home() / "AppData" / "Roaming" / "npm" / name,
    ]:
        if candidate.exists():
            return str(candidate)
    return None


def _find_gemini_cli() -> Optional[str]:
    explicit = os.environ.get("GEMINI_CLI_PATH", "").strip()
    if explicit and Path(explicit).exists():
        return explicit
    return _find_cli("gemini")


def _bridge():
    from gateway.platforms.phone_bridge import bridge
    return bridge


def _save_last(workspace: Path) -> None:
    try:
        _LAST_STATE.parent.mkdir(parents=True, exist_ok=True)
        _LAST_STATE.write_text(
            json.dumps({"workspace": str(workspace),
                        "updated_at": datetime.now().isoformat(timespec="seconds")}),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("save_last failed: %s", e)


def _load_last() -> Optional[Path]:
    try:
        if not _LAST_STATE.exists():
            return None
        data = json.loads(_LAST_STATE.read_text(encoding="utf-8"))
        p = Path(data.get("workspace") or "")
        return p if p.exists() else None
    except Exception:
        return None


def _save_deploy_url(workspace: Path, url: str) -> None:
    """Кладём URL последнего деплоя в _last_workspace.json вместе с workspace."""
    try:
        data = {"workspace": str(workspace), "deploy_url": url,
                "updated_at": datetime.now().isoformat(timespec="seconds")}
        _LAST_STATE.parent.mkdir(parents=True, exist_ok=True)
        _LAST_STATE.write_text(json.dumps(data), encoding="utf-8")
    except Exception as e:
        logger.warning("save_deploy_url failed: %s", e)


def _load_deploy_url() -> Optional[str]:
    try:
        if not _LAST_STATE.exists():
            return None
        data = json.loads(_LAST_STATE.read_text(encoding="utf-8"))
        return data.get("deploy_url") or None
    except Exception:
        return None


def _resolve_workspace(args: Dict[str, Any]) -> Optional[Path]:
    """Найти workspace: явный arg → name lookup → last."""
    explicit = (args.get("workspace") or args.get("workspace_path") or "").strip()
    if explicit:
        p = Path(explicit)
        if p.is_absolute() and p.exists():
            return p
        # Может быть указано имя папки внутри _WORKSPACES
        p = _WORKSPACES / explicit
        if p.exists():
            return p

    name = (args.get("project") or args.get("name") or "").strip()
    if name:
        slug = _slugify(name)
        # Найдём самый свежий по mtime, имя начинается со slug
        candidates = sorted(
            (p for p in _WORKSPACES.glob(f"{slug}-*") if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            return candidates[0]

    return _load_last()


def _list_files(workspace: Path) -> list[str]:
    out: list[str] = []
    for p in sorted(workspace.rglob("*")):
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(workspace).parts):
            try:
                out.append(str(p.relative_to(workspace)).replace("\\", "/"))
            except ValueError:
                pass
    return out


def _zip_workspace(workspace: Path, zip_name: str) -> Path:
    zip_path = workspace.parent / zip_name
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in workspace.rglob("*"):
            if p.is_file():
                if any(part.startswith(".") for part in p.relative_to(workspace).parts):
                    continue
                arcname = p.relative_to(workspace)
                zf.write(p, arcname=arcname)
    return zip_path


async def _send_zip_to_phone(zip_path: Path, filename: str) -> Dict[str, Any]:
    data = zip_path.read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    timeout = max(60.0, len(encoded) / 30_000)
    return await _bridge().send_command(
        "file_write",
        {"path": filename, "content": encoded, "encoding": "base64", "append": False},
        timeout=timeout,
    )


async def _open_url_on_phone(url: str) -> Dict[str, Any]:
    """Открыть URL в браузере на телефоне через phone_bridge."""
    try:
        return await _bridge().send_command("open_url", {"url": url}, timeout=10)
    except Exception as e:
        return {"ok": False, "error": f"bridge_unavailable: {e}"}


# ---------------------------------------------------------------------------
# Preview server
# ---------------------------------------------------------------------------

def _tailscale_ip() -> Optional[str]:
    """Получить Tailscale-IP этого PC."""
    candidates = [
        r"C:\Program Files\Tailscale\tailscale.exe",
        shutil.which("tailscale"),
    ]
    for cli in candidates:
        if not cli or not Path(cli).exists():
            continue
        try:
            out = os.popen(f'"{cli}" ip -4').read().strip()
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("100."):
                    return line
        except Exception:
            pass
    # Fallback: localhost
    return None


def _pick_port(workspace: Path) -> int:
    """Стабильный порт по hash(workspace.name)."""
    return 7800 + (abs(hash(workspace.name)) % 100)


def _start_preview(workspace: Path) -> Dict[str, Any]:
    """Поднять http.server для workspace (если ещё не поднят)."""
    key = str(workspace)
    with _PREVIEW_LOCK:
        if key in _PREVIEW_SERVERS:
            srv = _PREVIEW_SERVERS[key]
            ip = _tailscale_ip() or "127.0.0.1"
            return {"ok": True, "url": f"http://{ip}:{srv['port']}/", "port": srv["port"], "reused": True}

        port = _pick_port(workspace)
        # Если порт занят — ищем рядом
        for tryport in range(port, port + 50):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("0.0.0.0", tryport))
                    port = tryport
                    break
                except OSError:
                    continue
        else:
            return {"ok": False, "error": "no free port in 7800-7850"}

        ws_str = str(workspace)

        class WorkspaceHandler(http.server.SimpleHTTPRequestHandler):
            def __init__(self_inner, *a, **kw):
                super().__init__(*a, directory=ws_str, **kw)

            def log_message(self_inner, fmt, *a):
                # Тихо, не плюёмся в gateway лог
                pass

        httpd = socketserver.ThreadingTCPServer(("0.0.0.0", port), WorkspaceHandler)
        httpd.daemon_threads = True
        thread = threading.Thread(target=httpd.serve_forever, daemon=True, name=f"preview-{port}")
        thread.start()

        _PREVIEW_SERVERS[key] = {"port": port, "thread": thread, "httpd": httpd}
        ip = _tailscale_ip() or "127.0.0.1"
        return {"ok": True, "url": f"http://{ip}:{port}/", "port": port, "reused": False}


# ---------------------------------------------------------------------------
# Run Gemini CLI
# ---------------------------------------------------------------------------

_HEADLESS_RULES = (
    "You are a senior product engineer + designer running HEADLESS. No human will "
    "approve plans. Execute immediately.\n\n"

    "═══ HARD RULES ═══\n"
    "1. Do NOT output a plan or ask questions. Just build.\n"
    "2. Create/modify files in current directory.\n"
    "3. ASCII filenames only (index.html, style.css, app.py).\n"
    "4. Match the EXACT request: language, content, colors, target audience. "
    "Russian if Russian asked. Real items with real prices. NEVER Lorem ipsum.\n"
    "5. Semantic HTML5, CSS Custom Properties, mobile-first responsive.\n"
    "6. Write/update README.md (what was built, how to run).\n"
    "7. Use MCP servers if available: context7 for fresh docs, shadcn-ui for React.\n"
    "8. Follow ~/.gemini/GEMINI.md if exists.\n"
    "9. When done — stop. No long summaries.\n"
    "10. SHELL COMMANDS — never run blocking/long-running or foreground-server "
    "commands; they hang the session forever. FORBIDDEN: `flutter run`, "
    "`flutter precache`, `flutter doctor`, any `* run dev`/`npm run dev`/`next dev`/"
    "`vite`, `* build_runner watch`, `* serve`, `docker`, anything that waits or "
    "starts a watcher/daemon. Allowed only quick one-shot commands that exit on "
    "their own (`npm install`, `dart run build_runner build --delete-conflicting-outputs`, "
    "`flutter pub get`). If a step would need a long-running command, just WRITE the "
    "code/config and move on — do NOT execute it.\n\n"

    "═══ DESIGN — ANTI-AI-SLOP MANDATE ═══\n"
    "Most AI-generated sites look the same: purple-pink gradients, glassy cards in 3-col "
    "grid, big hero with vague headline, rocket/lightning emoji on CTAs, 'FAST SECURE "
    "RELIABLE' feature trio, fake testimonials, gradient text. This look is INSTANTLY "
    "recognized as AI and screams cheap. AVOID IT.\n\n"

    "BANNED design clichés (NEVER do these):\n"
    "  ✗ Purple-to-pink, blue-to-cyan, or any rainbow/duotone gradients on backgrounds, "
    "buttons, or text. Solid colors only unless brand demands otherwise.\n"
    "  ✗ Glassmorphism (backdrop-filter: blur on cards) UNLESS the request literally "
    "demands it. It's the #1 AI tell.\n"
    "  ✗ Generic placeholder copy: 'Welcome to', 'Get started today', 'Join thousands of "
    "happy users', 'Unlock your potential', 'The future of X is here'.\n"
    "  ✗ Lorem ipsum, placeholder.com, picsum.photos, Unsplash random.\n"
    "  ✗ Emoji as decoration on buttons/headers (🚀⚡✨💎🔥). Use real icons (Lucide, "
    "Heroicons, Phosphor) via SVG or icon font.\n"
    "  ✗ Three feature cards: 'FAST / SECURE / RELIABLE' or 'Easy / Powerful / Beautiful'. "
    "  ✗ Fake testimonials with stock-photo avatars.\n"
    "  ✗ Hero h1 in 96px gradient text centered on emoji-pattern background.\n"
    "  ✗ 'Powered by AI' badges, sparkle emojis anywhere.\n\n"

    "INSTEAD — pick ONE coherent visual direction and commit to it:\n\n"

    "  • SWISS / EDITORIAL: black on warm off-white (#FAFAF7), one accent color "
    "(usually red #E63946 or electric blue #2D5BFF), thin grid lines as structure, "
    "generous whitespace, sans like Inter/Helvetica Neue/Söhne for body, serif like "
    "Tiempos/Source Serif for display. Numbers big, labels tiny uppercase tracking-wide. "
    "Inspired by: Linear, Vercel, Stripe Press, Bloomberg, Things, FT.\n\n"

    "  • NEO-BRUTALIST: thick black borders (2-3px), hard offset shadows (5px 5px 0 "
    "#000), saturated solid colors (yellow #FFD600, blue #5B8DEF, pink #FF7AB6), zero "
    "gradients, blocky sans (Space Grotesk, IBM Plex Sans), sharp corners or tiny radii "
    "(2-4px), playful but disciplined. Inspired by: Gumroad, Cron (old), Figma early.\n\n"

    "  • MODERN MINIMAL: near-white background (#FFFFFF or #FAFAFA), one neutral dark "
    "(#0A0A0A), thin sans (Inter 400/500), 8px grid, restrained micro-interactions, "
    "soft 1px borders (rgba 0,0,0,.06), tiny rounded corners (6-10px), no shadows or "
    "very faint ones. Inspired by: Notion, Linear, Raycast, Arc.\n\n"

    "  • SCANDINAVIAN WARM: cream background (#F5F1E8), forest-green or terracotta "
    "accents (#3A5A40 / #BC4B51), classy serif headlines (Fraunces, Source Serif Pro), "
    "humanist sans body (Inter, Söhne), generous line-height (1.6-1.8), wooden/cream "
    "tones, no harsh black — use #1A1A1A. Inspired by: Hem, Muuto, Norse Projects.\n\n"

    "  • TECH / DEVELOPER: dark navy or true-black background (#0A0E1A or #000), "
    "monospace accents for data/keys (JetBrains Mono, Fira Code), one bright accent "
    "(green #00D9A3, cyan #06B6D4, amber #F59E0B), grid backdrop subtle, terminal-like "
    "blocks, copy-paste-friendly. Inspired by: Vercel dashboard, Linear dark, Railway.\n\n"

    "If no direction fits the request — default to SWISS / EDITORIAL. It is timeless "
    "and never looks AI.\n\n"

    "TYPOGRAPHY rules (apply regardless of direction):\n"
    "  - Use Google Fonts via <link> or @import. Load max 2 families (1 sans + 1 serif "
    "or 1 sans + 1 mono).\n"
    "  - Body: 16-18px, line-height 1.5-1.7, max-width 60-72ch for prose.\n"
    "  - Headings: clear hierarchy (h1 > h2 > h3), letter-spacing -0.02em on display sizes.\n"
    "  - Numbers/data: tabular-nums (font-variant-numeric: tabular-nums).\n"
    "  - Never use system font stack alone — looks unfinished.\n\n"

    "COLOR rules:\n"
    "  - 60-30-10: 60% neutral background, 30% secondary, 10% accent. Not 33-33-33.\n"
    "  - WCAG AA contrast minimum (4.5:1 body, 3:1 large).\n"
    "  - No more than 1 accent color. Restraint > variety.\n"
    "  - Use OKLCH or HSL when defining custom properties — easier to derive variants.\n\n"

    "LAYOUT rules:\n"
    "  - Use CSS Grid for page-level structure, Flexbox for components.\n"
    "  - 8px or 4px base unit for all spacing. Stick to scale.\n"
    "  - Asymmetric layouts > centered-everything. Off-center hero is more interesting.\n"
    "  - Real content sets layout, not the other way around.\n\n"

    "INTERACTIONS:\n"
    "  - Subtle: 150-200ms ease-out for hovers, 250-300ms for state changes.\n"
    "  - Hover: small transform (translateY -1px) or border shift, not big scale.\n"
    "  - Focus rings visible (accessibility) but tasteful.\n"
    "  - Smooth scroll, prefers-reduced-motion respected.\n\n"

    "IMAGES & ICONS:\n"
    "  - If real images aren't available, use inline SVG illustrations (geometric, "
    "branded) NOT stock photos.\n"
    "  - Icons: SVG inline (Lucide/Phosphor/Heroicons), stroke 1.5-2px, currentColor.\n"
    "  - Never link to external image services with hotlinks unless explicitly OK.\n\n"

    "CONTENT:\n"
    "  - Real-world specific copy. If it's a bakery — name 5 real pastries with prices. "
    "If portfolio — name 3 real project examples. Specifics beat polish.\n"
    "  - Headlines say WHAT the thing is, not how amazing it is. "
    "'Bookings for hair salons' > 'Revolutionize your salon experience'.\n"
    "  - Cut all marketing fluff. Confident, calm, informative tone.\n\n"

    "═══ CODE QUALITY ═══\n"
    "  - Semantic HTML (<header>/<main>/<nav>/<article>/<section>/<footer>).\n"
    "  - aria-labels on icon buttons, alt on every <img>.\n"
    "  - CSS Custom Properties for all colors/spacing/radii — no magic numbers.\n"
    "  - No CSS frameworks unless asked. Hand-write CSS — it's faster and cleaner "
    "for this scale.\n"
    "  - For React/Vue/Svelte projects: shadcn-ui (via MCP if available) for primitives, "
    "build the rest. No Material-UI/Antd unless asked — they look 2018.\n"
    "  - JS: vanilla or Alpine.js for sprinkles, framework only when needed.\n"
    "  - Optimize: lazy-load below-fold images, preload critical fonts.\n\n"

    "═══ NON-SECURE CONTEXT GOTCHAS ═══\n"
    "The site may be opened over HTTP by IP (not localhost, not HTTPS). In that case "
    "browser blocks several APIs. Always provide fallbacks:\n"
    "  - crypto.randomUUID() → falls back to Date.now() + Math.random()\n"
    "  - navigator.clipboard.writeText() → fallback document.execCommand('copy')\n"
    "  - navigator.mediaDevices.* → check availability first, show friendly message if blocked\n"
    "  - Service Workers / push notifications — don't assume available\n"
    "Use feature-detection: `if (typeof crypto !== 'undefined' && crypto.randomUUID) {...} else {...}`\n\n"

    "═══ FINAL CHECK before stopping ═══\n"
    "Re-read the final HTML/CSS/JS. If ANY of these are present — REWRITE:\n"
    "  □ Gradient backgrounds or gradient text on body\n"
    "  □ Emoji used as UI element (not as content)\n"
    "  □ 'Lorem ipsum' or placeholder text\n"
    "  □ Three feature cards in a row with abstract benefits\n"
    "  □ Headline like 'Welcome to', 'The future of', 'Unlock your'\n"
    "  □ More than 2 font families loaded\n"
    "  □ More than 1 accent color\n"
    "  □ Backdrop-filter blur (unless theme requires)\n"
    "  □ crypto.randomUUID() without fallback (breaks on HTTP-by-IP)\n"
    "  □ navigator.clipboard.* without document.execCommand fallback\n"
    "Pass = ship. Fail = rewrite that section.\n"
)


_DESIGN_STYLE_DIRECTIVES = {
    "swiss": (
        "DESIGN DIRECTION: SWISS / EDITORIAL.\n"
        "Background: warm off-white (#FAFAF7). Text: near-black (#0F0F0F). "
        "ONE accent color — pick from #E63946 (red) or #2D5BFF (electric blue).\n"
        "Fonts: Inter or Söhne for body; Tiempos, Source Serif Pro, or Fraunces for display.\n"
        "Layout: thin 1px grid lines, generous whitespace, asymmetric. "
        "Big numbers, tiny uppercase labels with letter-spacing. Tabular-nums on data.\n"
        "References: Linear.app, Vercel, Stripe Press, Bloomberg, FT.\n"
        "NO gradients, NO emoji, NO glassmorphism, NO three-feature-cards row."
    ),
    "brutalist": (
        "DESIGN DIRECTION: NEO-BRUTALIST.\n"
        "Solid saturated colors: yellow #FFD600, electric blue #5B8DEF, hot pink #FF7AB6, "
        "off-white #F4F1ED background, hard black #000 text/borders.\n"
        "Borders: thick 2-3px solid #000. Shadows: hard offset (box-shadow: 5px 5px 0 #000), no blur.\n"
        "Fonts: Space Grotesk or IBM Plex Sans (blocky sans). Optional mono accent.\n"
        "Corners: sharp (0px) or tiny (2-4px). Buttons feel like real buttons.\n"
        "References: Gumroad, Cron app (early), Figma 2018, Anthropic's blog.\n"
        "Playful but disciplined. NO gradients, NO soft shadows, NO Material Design."
    ),
    "modern_minimal": (
        "DESIGN DIRECTION: MODERN MINIMAL.\n"
        "Background: pure white #FFFFFF or #FAFAFA. Text: #0A0A0A. "
        "Borders: faint 1px rgba(0,0,0,0.06). Corners: 6-10px radius.\n"
        "Font: Inter (400/500/600 only). No serif unless explicitly needed.\n"
        "Layout: 8px base unit, restrained, lots of breathing room. "
        "Subtle micro-interactions (150-200ms ease-out, hover translateY -1px).\n"
        "References: Notion, Linear, Raycast, Arc, Things.\n"
        "Avoid: heavy shadows, more than 2 grays, decorative elements."
    ),
    "scandinavian_warm": (
        "DESIGN DIRECTION: SCANDINAVIAN WARM.\n"
        "Background: cream #F5F1E8 or paper #F8F3EA. Text: warm dark #1A1A1A (not pure black).\n"
        "Accents: forest green #3A5A40 or terracotta #BC4B51. Both, never neon.\n"
        "Display font: Fraunces, Source Serif Pro, or Cormorant. Body: Inter or Söhne.\n"
        "Generous line-height (1.6-1.8). Soft, calm tone. Real photos > illustrations.\n"
        "References: Hem, Muuto, Norse Projects, Goldune.\n"
        "Warm and crafted. NO neon, NO harsh contrast, NO Tailwind defaults."
    ),
    "tech_dev": (
        "DESIGN DIRECTION: TECH / DEVELOPER.\n"
        "Background: deep navy #0A0E1A or true black #000. Text: #E5E7EB or #FAFAFA.\n"
        "One bright accent — green #00D9A3, cyan #06B6D4, or amber #F59E0B.\n"
        "Display: Inter or Geist. Mono for code/data: JetBrains Mono or Fira Code.\n"
        "Subtle grid backdrop. Terminal-style code blocks with copy buttons. "
        "Show real API examples / curl commands inline.\n"
        "References: Vercel dashboard, Linear dark, Railway, Supabase.\n"
        "Speak to engineers — concrete, dense, no marketing fluff."
    ),
}


async def _run_gemini(workspace: Path, task: str, timeout: int, *,
                     iterate: bool = False, use_mcp: bool = False,
                     design_style: Optional[str] = None,
                     extra_constraints: Optional[str] = None) -> Dict[str, Any]:
    cli = _find_gemini_cli()
    if not cli:
        return {"ok": False, "error": "gemini_cli_not_found",
                "hint": "npm install -g @google/gemini-cli"}
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    oauth_creds = Path.home() / ".gemini" / "oauth_creds.json"
    if not api_key and not oauth_creds.exists():
        return {"ok": False, "error": "no_gemini_auth"}

    env = os.environ.copy()
    if api_key:
        env["GEMINI_API_KEY"] = api_key
    env["GEMINI_CLI_TRUST_WORKSPACE"] = "true"
    # Сеть нестабильна: DNS отдаёт IPv6, маршрута к IPv6 нет → node висит/ECONNRESET.
    # Заставляем node (gemini-cli) предпочитать IPv4 — не требует админ-прав.
    env["NODE_OPTIONS"] = (env.get("NODE_OPTIONS", "") + " --dns-result-order=ipv4first").strip()

    prefix = _HEADLESS_RULES
    if design_style and design_style in _DESIGN_STYLE_DIRECTIVES:
        prefix += "\n\n═══ CHOSEN DIRECTION (overrides defaults) ═══\n" + _DESIGN_STYLE_DIRECTIVES[design_style] + "\n"
    if extra_constraints:
        prefix += f"\n\nADDITIONAL CONSTRAINTS FROM USER:\n{extra_constraints}\n"
    if iterate:
        existing = _list_files(workspace)
        prefix += (
            "\nNOTE: This is an ITERATION on existing project. Existing files:\n"
            + "\n".join(f"  - {f}" for f in existing[:30])
            + "\nModify them in-place. Do NOT delete unrelated files.\n"
        )

    wrapped = f"{prefix}\nUSER TASK:\n{task}"

    # Windows cmdline limit ~32K. Если длинный — пишем в файл, prompt укорачиваем.
    if len(wrapped) > 8000:
        task_file = workspace / ".CODE_TASK.md"
        task_file.write_text(wrapped, encoding="utf-8")
        wrapped = (
            "Read .CODE_TASK.md in current directory — it has your full instructions "
            "(rules, project context, task). Execute it. "
            "When done, delete .CODE_TASK.md (it's not part of the product)."
        )
        logger.info("Code task written to file (%d chars original)", task_file.stat().st_size)

    args = [cli, "--yolo"]
    if not use_mcp:
        args += ["--allowed-mcp-server-names", "__none__"]
    args += ["--prompt", wrapped]
    logger.info("Spawning gemini-cli in %s (iterate=%s, mcp=%s)", workspace, iterate, use_mcp)

    # КРИТИЧНО: НЕ используем PIPE — gemini-cli (node) пишет много, буфер PIPE
    # переполняется, proc.communicate() блокируется, потом не дочитывает после
    # taskkill (пайпы рвутся грязно) → worker висит навсегда.
    # Решение: писать stdout/stderr в файлы, никаких пайпов.
    log_out = workspace / ".gemini_run.log"
    log_err = workspace / ".gemini_run.err"
    try:
        f_out = open(log_out, "wb")
        f_err = open(log_err, "wb")
    except Exception as e:
        return {"ok": False, "error": f"cannot open log files: {e}"}

    # Windows console handling (важно, иначе gemini-cli либо падает, либо висит):
    #  • БЕЗ флагов: child наследует (скрытую) консоль gateway. node-pty форкает
    #    conpty_console_list_agent → AttachConsole(shellPid). Раньше это падало
    #    «AttachConsole failed» → теперь агент пропатчен (try/catch, fallback на
    #    [shellPid]), поэтому безопасно.
    #  • С CREATE_NO_WINDOW: gemini-cli ЗАВИСАЕТ headless (ink/терминал не может
    #    рендерить в отвязанную консоль) — проверено: 200с таймаут vs 12с без флага.
    # Поэтому creationflags=0. Окно не всплывает: child наследует консоль родителя.
    creation_flags = 0
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=str(workspace),
            stdout=f_out, stderr=f_err,
            env=env,
            creationflags=creation_flags,
        )
        try:
            rc = await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            # Windows: proc.kill() убивает только cmd.exe, дочка-node живёт.
            # taskkill /T /F рекурсивно убивает всё дерево.
            try:
                import subprocess as _sp
                _sp.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                        capture_output=True, timeout=10)
            except Exception as _kill_err:
                logger.warning("taskkill failed for pid %s: %s", proc.pid, _kill_err)
                try:
                    proc.kill()
                except Exception:
                    pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except Exception:
                pass
            return {"ok": False, "error": f"timed out after {timeout}s"}
        finally:
            try: f_out.close()
            except Exception: pass
            try: f_err.close()
            except Exception: pass

        out = log_out.read_text(encoding="utf-8", errors="replace") if log_out.exists() else ""
        err = log_err.read_text(encoding="utf-8", errors="replace") if log_err.exists() else ""
        if rc != 0:
            return {"ok": False, "error": f"gemini-cli exit {rc}",
                    "stderr_tail": err[-800:], "stdout_tail": out[-400:]}
        return {"ok": True, "rc": rc, "stdout_tail": out[-400:]}
    except FileNotFoundError as e:
        try: f_out.close()
        except Exception: pass
        try: f_err.close()
        except Exception: pass
        return {"ok": False, "error": f"spawn failed: {e}"}


# ---------------------------------------------------------------------------
# Deploy via Vercel
# ---------------------------------------------------------------------------

async def _deploy_vercel(workspace: Path, timeout: int = 180) -> Dict[str, Any]:
    cli = _find_cli("vercel")
    if not cli:
        return {"ok": False, "error": "vercel_cli_not_found",
                "hint": "npm install -g vercel  (и vercel login)"}
    args = [cli, "--prod", "--yes"]
    logger.info("vercel deploy from %s", workspace)
    log_out = workspace / ".vercel_deploy.log"
    log_err = workspace / ".vercel_deploy.err"
    try:
        f_out = open(log_out, "wb")
        f_err = open(log_err, "wb")
    except Exception as e:
        return {"ok": False, "error": f"cannot open log files: {e}"}
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=str(workspace),
            stdout=f_out, stderr=f_err,
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                import subprocess as _sp
                _sp.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                        capture_output=True, timeout=10)
            except Exception:
                try: proc.kill()
                except Exception: pass
            try: await asyncio.wait_for(proc.wait(), timeout=5)
            except Exception: pass
            return {"ok": False, "error": "vercel deploy timeout"}
        finally:
            try: f_out.close()
            except Exception: pass
            try: f_err.close()
            except Exception: pass
        out = log_out.read_text(encoding="utf-8", errors="replace") if log_out.exists() else ""
        err = log_err.read_text(encoding="utf-8", errors="replace") if log_err.exists() else ""
        # vercel печатает URL и в stdout и в stderr (info)
        combined = out + "\n" + err
        url_match = re.search(r"https?://[^\s]+\.vercel\.app[^\s]*", combined)
        url = url_match.group(0) if url_match else None
        if proc.returncode != 0 and not url:
            return {"ok": False, "error": f"vercel exit {proc.returncode}",
                    "stderr_tail": err[-800:], "hint": "Возможно нужен `vercel login`"}
        return {"ok": True, "url": url, "stdout_tail": out[-400:]}
    except FileNotFoundError as e:
        return {"ok": False, "error": f"spawn failed: {e}"}


# ---------------------------------------------------------------------------
# Handlers per action
# ---------------------------------------------------------------------------

async def _do_create_work(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Тяжёлая часть create — запускается в фоне через job_runner."""
    task = payload["task"]
    workspace = Path(payload["workspace"])
    slug = payload["slug"]
    timestamp = payload["timestamp"]
    timeout = payload["timeout"]
    use_mcp = payload["use_mcp"]
    deliver = payload["deliver"]
    want_preview = payload["want_preview"]
    design_style = payload.get("design_style")
    extra_constraints = payload.get("extra_constraints")

    gemini = await _run_gemini(workspace, task, timeout, use_mcp=use_mcp,
                              design_style=design_style,
                              extra_constraints=extra_constraints)
    files = _list_files(workspace)

    # Сохраняем указатель на workspace ВСЕГДА, если там есть пользовательские файлы.
    # Тогда даже частичный результат можно открыть/итерировать.
    if files:
        try: _save_last(workspace)
        except Exception as _e: logger.warning("_save_last failed: %s", _e)

    if not gemini.get("ok") and not files:
        return {"ok": False, "stage": "gemini-cli", "workspace": str(workspace),
                **gemini, "say_to_user": "Не получилось сделать сайт. Попробуй переформулировать."}
    if not files:
        return {"ok": False, "workspace": str(workspace), "error": "no_files",
                "say_to_user": "Gemini ничего не сгенерировал."}

    zip_info: Dict[str, Any] = {}
    if deliver != "none":
        zip_name = f"{slug}-{timestamp}.zip"
        try:
            zip_path = _zip_workspace(workspace, zip_name)
            zip_info = {"zip_name": zip_name, "zip_size_kb": zip_path.stat().st_size // 1024}
            if deliver == "phone":
                resp = await _send_zip_to_phone(zip_path, zip_name)
                zip_info["delivered"] = bool(resp.get("ok"))
        except Exception as e:
            zip_info = {"zip_error": str(e)}

    preview = None
    has_index = "index.html" in files
    if want_preview is None:
        want_preview = has_index
    if want_preview:
        preview = _start_preview(workspace)

    parts = [f"Готов проект, {len(files)} файлов"]
    if zip_info.get("delivered"):
        parts.append("архив в Downloads")
    if preview and preview.get("ok"):
        parts.append("Открыть превью?")
    say = ". ".join(parts) + ("" if parts[-1].endswith("?") else ".")

    return {"ok": True, "action": "create", "workspace": str(workspace),
            "files_count": len(files), "files": files[:30],
            "files_truncated": len(files) > 30,
            "zip": zip_info, "preview": preview, "say_to_user": say,
            "next_action_hint": "open" if preview and preview.get("ok") else None}


async def _action_create(args: Dict[str, Any]) -> Dict[str, Any]:
    task = (args.get("task") or "").strip()
    if not task:
        return {"ok": False, "error": "missing 'task'"}
    project = (args.get("project") or " ".join(task.split()[:5])).strip()
    slug = _slugify(project)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    workspace = _WORKSPACES / f"{slug}-{timestamp}"
    workspace.mkdir(parents=True, exist_ok=True)

    timeout = max(30, min(int(args.get("timeout_seconds") or _DEFAULT_TIMEOUT), 3600))
    use_mcp = bool(args.get("use_mcp", False))
    deliver = (args.get("deliver") or "phone").strip().lower()
    want_preview = args.get("preview")
    async_mode = args.get("async_mode")
    if async_mode is None:
        async_mode = True  # default: всегда в фоне

    payload = {
        "task": task, "workspace": str(workspace), "slug": slug, "timestamp": timestamp,
        "timeout": timeout, "use_mcp": use_mcp, "deliver": deliver, "want_preview": want_preview,
        "design_style": (args.get("design_style") or "").strip().lower() or None,
        "extra_constraints": (args.get("extra_constraints") or "").strip() or None,
    }

    if not async_mode:
        # Синхронный режим — для debug или явного запроса
        return await _do_create_work(payload)

    # Фоновый режим: проверяем лимит, ставим job, сразу возвращаем
    from tools import job_runner
    if job_runner.active_count() >= 6:
        return {"ok": False, "error": "too_many_active",
                "say_to_user": "У меня уже шесть задач в работе, подожди пока одна закончится."}
    session_id = args.get("_session_id") or "phone-misha-main"
    label = f"сайт {project[:40]}"
    task_id = job_runner.submit("gemini_code_create", payload, session_id=session_id, short_label=label)
    return {"ok": True, "action": "create", "task_id": task_id, "status": "queued",
            "workspace": str(workspace), "async_mode": True,
            "say_to_user": "Принял, делаю в фоне. Скажу когда готово."}


async def _action_iterate(args: Dict[str, Any]) -> Dict[str, Any]:
    task = (args.get("task") or args.get("changes") or "").strip()
    if not task:
        return {"ok": False, "error": "missing 'task' (что изменить)"}
    workspace = _resolve_workspace(args)
    if not workspace or not workspace.exists():
        return {"ok": False, "error": "no_workspace",
                "say_to_user": "Не нашёл проект. Скажи имя или сначала сделай новый."}

    timeout = max(30, min(int(args.get("timeout_seconds") or _DEFAULT_TIMEOUT), 3600))
    use_mcp = bool(args.get("use_mcp", False))
    deliver = (args.get("deliver") or "phone").strip().lower()
    async_mode = args.get("async_mode")
    if async_mode is None:
        async_mode = True

    payload = {
        "task": task, "workspace": str(workspace),
        "timeout": timeout, "use_mcp": use_mcp, "deliver": deliver,
        "design_style": (args.get("design_style") or "").strip().lower() or None,
        "extra_constraints": (args.get("extra_constraints") or "").strip() or None,
    }

    if not async_mode:
        return await _do_iterate_work(payload)

    from tools import job_runner
    if job_runner.active_count() >= 6:
        return {"ok": False, "error": "too_many_active",
                "say_to_user": "У меня уже шесть задач в работе, подожди пока одна закончится."}
    session_id = args.get("_session_id") or "phone-misha-main"
    label = f"правка {workspace.name[:30]}"
    task_id = job_runner.submit("gemini_code_iterate", payload, session_id=session_id, short_label=label)
    return {"ok": True, "action": "iterate", "task_id": task_id, "status": "queued",
            "workspace": str(workspace), "async_mode": True,
            "say_to_user": "Принял правки, делаю в фоне. Скажу когда готово."}


async def _do_iterate_work(payload: Dict[str, Any]) -> Dict[str, Any]:
    task = payload["task"]
    workspace = Path(payload["workspace"])
    timeout = payload["timeout"]
    use_mcp = payload["use_mcp"]
    deliver = payload["deliver"]
    design_style = payload.get("design_style")
    extra_constraints = payload.get("extra_constraints")

    gemini = await _run_gemini(workspace, task, timeout, iterate=True, use_mcp=use_mcp,
                              design_style=design_style,
                              extra_constraints=extra_constraints)
    files = _list_files(workspace)

    if files:
        try: _save_last(workspace)
        except Exception as _e: logger.warning("_save_last failed: %s", _e)

    if not gemini.get("ok") and not files:
        return {"ok": False, "stage": "gemini-cli", "workspace": str(workspace), **gemini,
                "say_to_user": "Не получилось изменить."}

    zip_info: Dict[str, Any] = {}
    if deliver != "none":
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = workspace.name.rsplit("-", 2)[0] if "-" in workspace.name else workspace.name
        zip_name = f"{slug}-iter-{timestamp}.zip"
        try:
            zip_path = _zip_workspace(workspace, zip_name)
            zip_info = {"zip_name": zip_name, "zip_size_kb": zip_path.stat().st_size // 1024}
            if deliver == "phone":
                resp = await _send_zip_to_phone(zip_path, zip_name)
                zip_info["delivered"] = bool(resp.get("ok"))
        except Exception as e:
            zip_info = {"zip_error": str(e)}

    preview = _start_preview(workspace) if "index.html" in files else None

    parts = ["Доделал правки"]
    if zip_info.get("delivered"):
        parts.append("новый архив в Downloads")
    if preview and preview.get("ok"):
        parts.append("Открыть превью?")
    say = ". ".join(parts) + ("" if parts[-1].endswith("?") else ".")

    return {"ok": True, "action": "iterate", "workspace": str(workspace),
            "files_count": len(files), "files": files[:30],
            "zip": zip_info, "preview": preview, "say_to_user": say,
            "next_action_hint": "open" if preview and preview.get("ok") else None}


async def _action_preview(args: Dict[str, Any]) -> Dict[str, Any]:
    workspace = _resolve_workspace(args)
    if not workspace:
        return {"ok": False, "error": "no_workspace",
                "say_to_user": "Не нашёл проект, скажи имя."}
    if not (workspace / "index.html").exists():
        return {"ok": False, "error": "no_index_html",
                "say_to_user": "В проекте нет index.html, превью не подниму."}
    res = _start_preview(workspace)
    if res.get("ok"):
        return {"ok": True, "action": "preview", "workspace": str(workspace),
                "url": res["url"], "port": res["port"],
                "say_to_user": "Превью готово. Открыть?",
                "next_action_hint": "open"}
    return {"ok": False, **res, "say_to_user": "Не получилось поднять превью."}


async def _action_deploy(args: Dict[str, Any]) -> Dict[str, Any]:
    workspace = _resolve_workspace(args)
    if not workspace:
        return {"ok": False, "error": "no_workspace",
                "say_to_user": "Не нашёл проект, скажи имя."}
    res = await _deploy_vercel(workspace)
    if res.get("ok") and res.get("url"):
        # Сохраним URL чтобы action=open мог его открыть
        _save_deploy_url(workspace, res["url"])
        return {"ok": True, "action": "deploy", "workspace": str(workspace),
                "url": res["url"],
                "say_to_user": "Задеплоил. Открыть сайт?",
                "next_action_hint": "open"}
    return {"ok": False, **res,
            "say_to_user": "Не получилось задеплоить. Может нужен vercel login."}


async def _action_open(args: Dict[str, Any]) -> Dict[str, Any]:
    """Открыть превью/деплой URL на телефоне в браузере.

    Приоритет: explicit url arg → deploy_url из state → preview-сервер последнего workspace.
    """
    url = (args.get("url") or "").strip()
    target = (args.get("target") or "auto").strip().lower()  # auto|preview|deploy

    if not url:
        if target == "deploy":
            url = _load_deploy_url() or ""
        elif target == "preview":
            ws = _resolve_workspace(args)
            if ws and (ws / "index.html").exists():
                res = _start_preview(ws)
                if res.get("ok"):
                    url = res["url"]
        else:  # auto
            # Сначала смотрим preview активный, если index.html есть в last workspace
            ws = _resolve_workspace(args)
            if ws and (ws / "index.html").exists():
                res = _start_preview(ws)
                if res.get("ok"):
                    url = res["url"]
            if not url:
                url = _load_deploy_url() or ""

    if not url:
        return {"ok": False, "error": "no_url_to_open",
                "say_to_user": "Нечего открывать — нет ни превью, ни деплоя."}

    bridge_resp = await _open_url_on_phone(url)
    if bridge_resp.get("ok"):
        return {"ok": True, "action": "open", "url": url,
                "say_to_user": "Открыл."}
    return {"ok": False, "url": url, **bridge_resp,
            "say_to_user": "Не получилось открыть на телефоне."}


async def _action_last(args: Dict[str, Any]) -> Dict[str, Any]:
    workspace = _resolve_workspace(args) or _load_last()
    if not workspace:
        return {"ok": False, "error": "no_previous_workspace",
                "say_to_user": "Ещё ничего не делал."}
    files = _list_files(workspace)
    return {"ok": True, "action": "last", "workspace": str(workspace),
            "files_count": len(files), "files": files[:30],
            "say_to_user": f"Последний проект — {workspace.name}, {len(files)} файлов."}


# ---------------------------------------------------------------------------
# Tool entrypoint
# ---------------------------------------------------------------------------

async def _handle(args: Dict[str, Any], **_kw) -> str:
    action = (args.get("action") or "create").strip().lower()
    try:
        if action == "create":
            result = await _action_create(args)
        elif action == "iterate":
            result = await _action_iterate(args)
        elif action == "preview":
            result = await _action_preview(args)
        elif action == "deploy":
            result = await _action_deploy(args)
        elif action == "open":
            result = await _action_open(args)
        elif action == "last":
            result = await _action_last(args)
        else:
            result = {"ok": False, "error": f"unknown_action: {action}",
                      "allowed": ["create", "iterate", "preview", "deploy", "open", "last"]}
    except Exception as e:
        logger.exception("gemini_code handler crashed")
        result = {"ok": False, "error": f"{type(e).__name__}: {e}",
                  "say_to_user": "Внутренняя ошибка, посмотри логи."}
    return json.dumps(result, ensure_ascii=False)


GEMINI_CODE_SCHEMA = {
    "name": "gemini_code",
    "description": (
        "Делегирование кодинга Gemini CLI на PC. Действия (action):\n"
        "• create (default): новый проект. Параметры: task (что сделать), "
        "project (имя для папки/ZIP), preview (true=поднять локальный сервер), "
        "deliver (phone=ZIP в Downloads / none=только PC).\n"
        "• iterate: продолжение в последнем (или указанном) проекте. "
        "Параметры: task (что изменить), workspace/project (опционально — "
        "иначе берётся последний).\n"
        "• preview: поднять локальный превью-сервер. Возвращает URL.\n"
        "• deploy: задеплоить через vercel CLI, вернуть публичный URL.\n"
        "• open: ОТКРЫТЬ браузер на телефоне со ссылкой (превью или деплой). "
        "Используется после того как Миша голосом сказал «да» в ответ на "
        "«открыть?». target=auto (preview если есть, иначе deploy) / preview / deploy. "
        "Можно явно передать url.\n"
        "• last: показать что сейчас в последнем проекте.\n"
        "ВАЖНО: say_to_user в ответе — готовый к озвучке текст. ВСЕГДА "
        "озвучь его пользователю вслух после вызова. **НЕ диктуй URL по символам** — "
        "вместо этого предложение «Открыть?» уже в say_to_user, и если Миша скажет "
        "«да» — вызови gemini_code(action='open')."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "iterate", "preview", "deploy", "open", "last"],
                "description": "Что делать. Default 'create' для нового проекта. 'open' = открыть URL на телефоне.",
            },
            "url": {
                "type": "string",
                "description": "Для action=open: явный URL (опционально). Иначе берётся preview/deploy последнего проекта.",
            },
            "target": {
                "type": "string",
                "enum": ["auto", "preview", "deploy"],
                "description": "Для action=open: что предпочитать. Default 'auto' (preview если есть, иначе deploy).",
            },
            "task": {
                "type": "string",
                "description": (
                    "Для create: что сделать ('сайт визитку кофейни'). "
                    "Для iterate: что изменить ('поменяй цвета на тёмные'). "
                    "Для preview/deploy/last: не нужно."
                ),
            },
            "project": {
                "type": "string",
                "description": "Имя проекта (создаст слаг для папки). Для iterate/preview/deploy — может уточнить какой именно проект.",
            },
            "workspace": {
                "type": "string",
                "description": "Альтернатива project — явный путь или имя папки в ~/.troika/workspaces/.",
            },
            "preview": {
                "type": "boolean",
                "description": "Для create: явно поднять превью. По умолчанию авто для HTML-проектов.",
            },
            "deliver": {
                "type": "string",
                "enum": ["phone", "none"],
                "description": "По умолчанию 'phone' — ZIP в Downloads. 'none' — только на PC.",
            },
            "timeout_seconds": {
                "type": "integer",
                "description": "Сколько ждать Gemini (30..1800, default 300).",
            },
            "use_mcp": {
                "type": "boolean",
                "description": "Включить MCP-серверы Gemini (context7 для свежей доки, shadcn-ui для React). По умолчанию false — заметно ускоряет старт. Включай только если задача требует свежей доки или React-компонентов.",
            },
            "design_style": {
                "type": "string",
                "enum": ["swiss", "brutalist", "modern_minimal", "scandinavian_warm", "tech_dev"],
                "description": (
                    "Визуальный стиль для frontend/UI задач. Без этого Gemini "
                    "промахнётся в AI-эстетику (фиолетовые градиенты, glassy). "
                    "swiss=Linear/Vercel/Stripe; brutalist=Gumroad/Figma early; "
                    "modern_minimal=Notion/Raycast/Arc; scandinavian_warm=Hem/Muuto; "
                    "tech_dev=Vercel dashboard/Railway. См. skill 'web-design-styles' для маппинга голос→стиль."
                ),
            },
            "extra_constraints": {
                "type": "string",
                "description": "Дополнительные ограничения: палитра, шрифты, референсы ('как у Linear'), что НЕ хотим. Передаётся как есть в prompt.",
            },
            "async_mode": {
                "type": "boolean",
                "description": "Запускать ли в фоне (default true). Тройка получит task_id сразу, продолжит общение, и озвучит результат когда фон-задача готова. Поставь false ТОЛЬКО если нужно ждать результат прямо сейчас (редко).",
            },
        },
    },
}


# Регистрируем фоновые handlers в job_runner.
try:
    from tools import job_runner as _job_runner
    _job_runner.register_handler("gemini_code_create", _do_create_work)
    _job_runner.register_handler("gemini_code_iterate", _do_iterate_work)
except Exception as _e:
    logger.warning("job_runner handler registration failed: %s", _e)


def _check_gemini_cli() -> bool:
    return _find_gemini_cli() is not None


registry.register(
    name="gemini_code",
    toolset="gemini_code",
    schema=GEMINI_CODE_SCHEMA,
    handler=_handle,
    check_fn=_check_gemini_cli,
    is_async=True,
    emoji="🧠",
)
