"""Send native mouse input to a verified Chromium content window."""

from contextlib import contextmanager
import ctypes as ct
from ctypes import wintypes as win


_INPUT_MOUSE = 0
_MOUSE_LEFT_DOWN, _MOUSE_LEFT_UP = 0x0002, 0x0004
_MOUSE_RIGHT_DOWN, _MOUSE_RIGHT_UP = 0x0008, 0x0010
_MOUSE_WHEEL = 0x0800
_SWAPPED_BUTTONS = 23
_ROOT_WINDOW = 2
_WHEEL_ROUTING, _WHEEL_UNDER_CURSOR = 0x201C, 2
_RAISE_WITHOUT_ACTIVATING = 0x0013
_WINDOW_EX_STYLE, _TOPMOST = -20, 0x00000008
_INPUT_KEYS = (0x01, 0x02, 0x04, 0x05, 0x06, 0x10, 0x11, 0x12)
_ENUM_WINDOW = ct.WINFUNCTYPE(win.BOOL, win.HWND, win.LPARAM) if hasattr(ct, "WINFUNCTYPE") else None


class _MouseInput(ct.Structure):
    _fields_ = [("dx", win.LONG), ("dy", win.LONG), ("data", win.DWORD),
                ("flags", win.DWORD), ("time", win.DWORD), ("extra", ct.c_size_t)]


class _Input(ct.Structure):
    _fields_ = [("kind", win.DWORD), ("mouse", _MouseInput)]


class WindowsPointer:
    def __init__(self):
        user = ct.WinDLL("user32")
        for name, result, arguments in (
            ("GetForegroundWindow", win.HWND, ()),
            ("GetWindowThreadProcessId", win.DWORD, (win.HWND, ct.POINTER(win.DWORD))),
            ("GetClassNameW", ct.c_int, (win.HWND, win.LPWSTR, ct.c_int)),
            ("GetClientRect", win.BOOL, (win.HWND, ct.POINTER(win.RECT))),
            ("GetWindowRect", win.BOOL, (win.HWND, ct.POINTER(win.RECT))),
            ("GetDpiForWindow", win.UINT, (win.HWND,)),
            ("ClientToScreen", win.BOOL, (win.HWND, ct.POINTER(win.POINT))),
            ("WindowFromPoint", win.HWND, (win.POINT,)),
            ("GetAncestor", win.HWND, (win.HWND, win.UINT)),
            ("GetCursorPos", win.BOOL, (ct.POINTER(win.POINT),)),
            ("SetCursorPos", win.BOOL, (ct.c_int, ct.c_int)),
            ("GetAsyncKeyState", ct.c_short, (ct.c_int,)),
            ("GetSystemMetrics", ct.c_int, (ct.c_int,)),
            ("SendInput", win.UINT, (win.UINT, ct.POINTER(_Input), ct.c_int)),
            ("SetThreadDpiAwarenessContext", win.HANDLE, (win.HANDLE,)),
            ("EnumChildWindows", win.BOOL, (win.HWND, _ENUM_WINDOW, win.LPARAM)),
            ("EnumWindows", win.BOOL, (_ENUM_WINDOW, win.LPARAM)),
            ("IsWindowVisible", win.BOOL, (win.HWND,)),
            ("IsIconic", win.BOOL, (win.HWND,)),
            ("GetWindowLongW", win.LONG, (win.HWND, ct.c_int)),
            ("SetWindowPos", win.BOOL, (win.HWND, win.HWND, ct.c_int, ct.c_int, ct.c_int, ct.c_int, win.UINT)),
            ("SystemParametersInfoW", win.BOOL, (win.UINT, win.UINT, ct.POINTER(win.DWORD), win.UINT)),
        ):
            function = getattr(user, name)
            function.restype, function.argtypes = result, arguments
        self.user = user

    def __enter__(self):
        self._dpi = self.user.SetThreadDpiAwarenessContext(-4)  # Per-monitor DPI aware v2.
        if not self._dpi:
            raise OSError("Windows pointer DPI unavailable")
        return self

    def __exit__(self, *_):
        self.user.SetThreadDpiAwarenessContext(self._dpi)

    def _owns_window(self, handle, pid, class_name):
        owner, name = win.DWORD(), ct.create_unicode_buffer(64)
        return (handle and self.user.GetWindowThreadProcessId(handle, ct.byref(owner)) and owner.value == pid
                and self.user.GetClassNameW(handle, name, len(name)) and name.value == class_name)

    def bind(self, browser_pid, bounds):
        matches = []

        @_ENUM_WINDOW
        def visit(handle, _):
            if not self.user.IsWindowVisible(handle) or not self._owns_window(handle, browser_pid, "Chrome_WidgetWin_1"):
                return True
            rect = win.RECT()
            scale = self.user.GetDpiForWindow(handle) / 96
            if scale and self.user.GetWindowRect(handle, ct.byref(rect)):
                native = (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
                if all(abs(actual - expected * scale) <= 4 for actual, expected in zip(native, bounds)):
                    matches.append(handle)
            return True

        self.user.EnumWindows(visit, 0)
        return matches[0] if len(matches) == 1 else None

    def can_scroll(self, window):
        if self.user.GetForegroundWindow() == window:
            return True
        routing = win.DWORD()
        return (self.user.SystemParametersInfoW(_WHEEL_ROUTING, 0, ct.byref(routing), 0)
                and routing.value == _WHEEL_UNDER_CURSOR)

    @contextmanager
    def reveal(self, window, pid):
        if not self._owns_window(window, pid, "Chrome_WidgetWin_1"):
            yield
            return
        topmost = self.user.GetWindowLongW(window, _WINDOW_EX_STYLE) & _TOPMOST
        changed = not topmost and self.user.SetWindowPos(window, -1, 0, 0, 0, 0, _RAISE_WITHOUT_ACTIVATING)
        try:
            yield
        finally:
            if changed and self._owns_window(window, pid, "Chrome_WidgetWin_1"):
                self.user.SetWindowPos(window, -2, 0, 0, 0, 0, _RAISE_WITHOUT_ACTIVATING)

    def content_point(self, window, browser_pid, viewport, point):
        if (not self._owns_window(window, browser_pid, "Chrome_WidgetWin_1")
                or not self.user.IsWindowVisible(window) or self.user.IsIconic(window)):
            return None
        width, height = viewport
        scale = self.user.GetDpiForWindow(window) / 96
        if not scale:
            return None
        candidates = []

        @_ENUM_WINDOW
        def visit(handle, _):
            if self.user.IsWindowVisible(handle) and self._owns_window(handle, browser_pid, "Chrome_RenderWidgetHostHWND"):
                rect, origin = win.RECT(), win.POINT()
                if self.user.GetClientRect(handle, ct.byref(rect)) and self.user.ClientToScreen(handle, ct.byref(origin)):
                    if abs(rect.right - width * scale) <= 2 and abs(rect.bottom - height * scale) <= 2:
                        x, y = round(point[0] * scale), round(point[1] * scale)
                        if 0 <= x < rect.right and 0 <= y < rect.bottom:
                            candidates.append((handle, origin.x + x, origin.y + y))
            return True

        self.user.EnumChildWindows(window, visit, 0)
        if len(candidates) != 1:
            return None
        handle, x, y = candidates[0]
        if self.user.WindowFromPoint(win.POINT(x, y)) != handle or self.user.GetAncestor(handle, _ROOT_WINDOW) != window:
            return None
        return window, handle, x, y

    def position(self):
        point = win.POINT()
        return (point.x, point.y) if self.user.GetCursorPos(ct.byref(point)) else None

    def input_held(self):
        return any(self.user.GetAsyncKeyState(key) < 0 for key in _INPUT_KEYS)

    def move(self, point):
        return bool(self.user.SetCursorPos(*point))

    def send(self, action, direction=None):
        if action == "click":
            swapped = self.user.GetSystemMetrics(_SWAPPED_BUTTONS)
            flags = (_MOUSE_RIGHT_DOWN, _MOUSE_RIGHT_UP) if swapped else (_MOUSE_LEFT_DOWN, _MOUSE_LEFT_UP)
            inputs = (_Input * 2)(*(_Input(_INPUT_MOUSE, _MouseInput(flags=flag)) for flag in flags))
        else:
            inputs = (_Input * 1)(_Input(_INPUT_MOUSE, _MouseInput(data=-480 if direction == "down" else 480, flags=_MOUSE_WHEEL)))
        sent = self.user.SendInput(len(inputs), inputs, ct.sizeof(_Input))
        if len(inputs) == 2 and sent == 1:
            release = (_Input * 1)(inputs[1])
            self.user.SendInput(1, release, ct.sizeof(_Input))
        return sent == len(inputs)
