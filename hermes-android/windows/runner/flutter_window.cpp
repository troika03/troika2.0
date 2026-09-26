#include "flutter_window.h"

#include <algorithm>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include <wincodec.h>
#include <wrl/client.h>
#include <shellapi.h>

#include "flutter/generated_plugin_registrant.h"

namespace {

using Microsoft::WRL::ComPtr;

std::wstring Utf16FromUtf8(const std::string& value) {
  if (value.empty()) return {};
  const int length = MultiByteToWideChar(
      CP_UTF8, MB_ERR_INVALID_CHARS, value.data(),
      static_cast<int>(value.size()), nullptr, 0);
  if (length <= 0) return {};
  std::wstring result(length, L'\0');
  MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, value.data(),
                      static_cast<int>(value.size()), result.data(), length);
  return result;
}

void PlaceWindow(HWND window, int logical_width, int logical_height,
                 bool bottom_right, HWND z_order) {
  const UINT dpi = GetDpiForWindow(window);
  const int width = MulDiv(logical_width, dpi, 96);
  const int height = MulDiv(logical_height, dpi, 96);
  HMONITOR monitor = MonitorFromWindow(window, MONITOR_DEFAULTTONEAREST);
  MONITORINFO info{sizeof(info)};
  GetMonitorInfo(monitor, &info);
  const RECT work = info.rcWork;
  const int x = bottom_right ? work.right - width - 24
                             : work.left + (work.right - work.left - width) / 2;
  const int y = bottom_right ? work.bottom - height - 24
                             : work.top + (work.bottom - work.top - height) / 2;
  SetWindowPos(window, z_order, x, y, width, height,
               SWP_SHOWWINDOW | SWP_FRAMECHANGED);
  ShowWindow(window, SW_RESTORE);
  SetForegroundWindow(window);
}

std::optional<std::vector<uint8_t>> CaptureVirtualScreenPng() {
  const int x = GetSystemMetrics(SM_XVIRTUALSCREEN);
  const int y = GetSystemMetrics(SM_YVIRTUALSCREEN);
  const int width = GetSystemMetrics(SM_CXVIRTUALSCREEN);
  const int height = GetSystemMetrics(SM_CYVIRTUALSCREEN);
  if (width <= 0 || height <= 0) return std::nullopt;

  HDC screen_dc = GetDC(nullptr);
  if (!screen_dc) return std::nullopt;
  HDC memory_dc = CreateCompatibleDC(screen_dc);
  HBITMAP bitmap = CreateCompatibleBitmap(screen_dc, width, height);
  if (!memory_dc || !bitmap) {
    if (bitmap) DeleteObject(bitmap);
    if (memory_dc) DeleteDC(memory_dc);
    ReleaseDC(nullptr, screen_dc);
    return std::nullopt;
  }
  HGDIOBJ old_bitmap = SelectObject(memory_dc, bitmap);
  const BOOL copied = BitBlt(memory_dc, 0, 0, width, height, screen_dc, x, y,
                             SRCCOPY | CAPTUREBLT);
  SelectObject(memory_dc, old_bitmap);
  DeleteDC(memory_dc);
  ReleaseDC(nullptr, screen_dc);
  if (!copied) {
    DeleteObject(bitmap);
    return std::nullopt;
  }

  ComPtr<IWICImagingFactory> factory;
  HRESULT hr = CoCreateInstance(CLSID_WICImagingFactory, nullptr,
                                CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&factory));
  ComPtr<IWICBitmap> source_bitmap;
  if (SUCCEEDED(hr)) {
    hr = factory->CreateBitmapFromHBITMAP(bitmap, nullptr,
                                          WICBitmapUsePremultipliedAlpha,
                                          &source_bitmap);
  }
  DeleteObject(bitmap);
  if (FAILED(hr)) return std::nullopt;

  IWICBitmapSource* source = source_bitmap.Get();
  ComPtr<IWICBitmapScaler> scaler;
  UINT output_width = static_cast<UINT>(width);
  UINT output_height = static_cast<UINT>(height);
  constexpr UINT kMaxWidth = 1920;
  constexpr UINT kMaxHeight = 1080;
  if (output_width > kMaxWidth || output_height > kMaxHeight) {
    const double scale = std::min(
        static_cast<double>(kMaxWidth) / output_width,
        static_cast<double>(kMaxHeight) / output_height);
    output_width = std::max(1U, static_cast<UINT>(output_width * scale));
    output_height = std::max(1U, static_cast<UINT>(output_height * scale));
    hr = factory->CreateBitmapScaler(&scaler);
    if (SUCCEEDED(hr)) {
      hr = scaler->Initialize(source_bitmap.Get(), output_width, output_height,
                              WICBitmapInterpolationModeFant);
      source = scaler.Get();
    }
  }
  if (FAILED(hr)) return std::nullopt;

  ComPtr<IStream> stream;
  hr = CreateStreamOnHGlobal(nullptr, TRUE, &stream);
  ComPtr<IWICBitmapEncoder> encoder;
  ComPtr<IWICBitmapFrameEncode> frame;
  if (SUCCEEDED(hr)) {
    hr = factory->CreateEncoder(GUID_ContainerFormatPng, nullptr, &encoder);
  }
  if (SUCCEEDED(hr)) hr = encoder->Initialize(stream.Get(), WICBitmapEncoderNoCache);
  if (SUCCEEDED(hr)) hr = encoder->CreateNewFrame(&frame, nullptr);
  if (SUCCEEDED(hr)) hr = frame->Initialize(nullptr);
  if (SUCCEEDED(hr)) hr = frame->SetSize(output_width, output_height);
  WICPixelFormatGUID format = GUID_WICPixelFormat32bppBGRA;
  if (SUCCEEDED(hr)) hr = frame->SetPixelFormat(&format);
  if (SUCCEEDED(hr)) hr = frame->WriteSource(source, nullptr);
  if (SUCCEEDED(hr)) hr = frame->Commit();
  if (SUCCEEDED(hr)) hr = encoder->Commit();
  if (FAILED(hr)) return std::nullopt;

  HGLOBAL global = nullptr;
  hr = GetHGlobalFromStream(stream.Get(), &global);
  if (FAILED(hr) || !global) return std::nullopt;
  const SIZE_T size = GlobalSize(global);
  const auto* data = static_cast<const uint8_t*>(GlobalLock(global));
  if (!data || size == 0) {
    if (data) GlobalUnlock(global);
    return std::nullopt;
  }
  std::vector<uint8_t> bytes(data, data + size);
  GlobalUnlock(global);
  return bytes;
}

}  // namespace

FlutterWindow::FlutterWindow(const flutter::DartProject& project)
    : project_(project) {}

FlutterWindow::~FlutterWindow() {}

bool FlutterWindow::OnCreate() {
  if (!Win32Window::OnCreate()) {
    return false;
  }

  RECT frame = GetClientArea();

  // The size here must match the window dimensions to avoid unnecessary surface
  // creation / destruction in the startup path.
  flutter_controller_ = std::make_unique<flutter::FlutterViewController>(
      frame.right - frame.left, frame.bottom - frame.top, project_);
  // Ensure that basic setup of the controller was successful.
  if (!flutter_controller_->engine() || !flutter_controller_->view()) {
    return false;
  }
  RegisterPlugins(flutter_controller_->engine());
  SetChildContent(flutter_controller_->view()->GetNativeWindow());

  windows_channel_ =
      std::make_unique<flutter::MethodChannel<flutter::EncodableValue>>(
          flutter_controller_->engine()->messenger(), "troika/windows",
          &flutter::StandardMethodCodec::GetInstance());
  windows_channel_->SetMethodCallHandler(
      [this](const auto& call, auto result) {
        if (call.method_name() == "registerHotkey") {
          const auto* preset = std::get_if<std::string>(call.arguments());
          result->Success(flutter::EncodableValue(
              RegisterSelectedHotkey(preset ? *preset : "ctrlAltSpace")));
          return;
        }
        if (call.method_name() == "showCompact") {
          const auto* pinned = std::get_if<bool>(call.arguments());
          ShowCompactWindow(pinned && *pinned);
          result->Success();
          return;
        }
        if (call.method_name() == "showCommandCenter") {
          ShowCommandCenterWindow();
          result->Success();
          return;
        }
        if (call.method_name() == "setAlwaysOnTop") {
          const auto* enabled = std::get_if<bool>(call.arguments());
          SetAlwaysOnTop(enabled && *enabled);
          result->Success();
          return;
        }
        if (call.method_name() == "hide") {
          ShowWindow(GetHandle(), SW_HIDE);
          result->Success();
          return;
        }
        if (call.method_name() == "captureScreen") {
          auto bytes = CaptureVirtualScreenPng();
          if (!bytes) {
            result->Error("capture_failed", "Не удалось сделать снимок экрана");
          } else {
            result->Success(flutter::EncodableValue(std::move(*bytes)));
          }
          return;
        }
        if (call.method_name() == "openPath" ||
            call.method_name() == "showInFolder") {
          const auto* utf8_path = std::get_if<std::string>(call.arguments());
          if (!utf8_path) {
            result->Success(flutter::EncodableValue(false));
            return;
          }
          const std::wstring path = Utf16FromUtf8(*utf8_path);
          bool ok = false;
          if (!path.empty() &&
              GetFileAttributes(path.c_str()) != INVALID_FILE_ATTRIBUTES) {
            HINSTANCE launched = nullptr;
            if (call.method_name() == "openPath") {
              launched = ShellExecute(GetHandle(), L"open", path.c_str(),
                                      nullptr, nullptr, SW_SHOWNORMAL);
            } else {
              const std::wstring arguments = L"/select,\"" + path + L"\"";
              launched = ShellExecute(GetHandle(), L"open", L"explorer.exe",
                                      arguments.c_str(), nullptr,
                                      SW_SHOWNORMAL);
            }
            ok = reinterpret_cast<INT_PTR>(launched) > 32;
          }
          result->Success(flutter::EncodableValue(ok));
          return;
        }
        result->NotImplemented();
      });
  RegisterSelectedHotkey("ctrlAltSpace");

  flutter_controller_->engine()->SetNextFrameCallback([&]() {
    this->Show();
  });

  // Flutter can complete the first frame before the "show window" callback is
  // registered. The following call ensures a frame is pending to ensure the
  // window is shown. It is a no-op if the first frame hasn't completed yet.
  flutter_controller_->ForceRedraw();

  return true;
}

void FlutterWindow::OnDestroy() {
  UnregisterHotKey(GetHandle(), kTroikaHotkeyId);
  windows_channel_.reset();
  if (flutter_controller_) {
    flutter_controller_ = nullptr;
  }

  Win32Window::OnDestroy();
}

LRESULT
FlutterWindow::MessageHandler(HWND hwnd, UINT const message,
                              WPARAM const wparam,
                              LPARAM const lparam) noexcept {
  // Give Flutter, including plugins, an opportunity to handle window messages.
  if (flutter_controller_) {
    std::optional<LRESULT> result =
        flutter_controller_->HandleTopLevelWindowProc(hwnd, message, wparam,
                                                      lparam);
    if (result) {
      return *result;
    }
  }

  switch (message) {
    case WM_HOTKEY:
      if (wparam == kTroikaHotkeyId && windows_channel_) {
        ShowWindow(hwnd, SW_RESTORE);
        SetForegroundWindow(hwnd);
        windows_channel_->InvokeMethod(
            "hotkeyPressed",
            std::make_unique<flutter::EncodableValue>());
        return 0;
      }
      break;
    case WM_CLOSE:
      if (compact_mode_) {
        ShowWindow(hwnd, SW_HIDE);
        return 0;
      }
      break;
    case WM_FONTCHANGE:
      flutter_controller_->engine()->ReloadSystemFonts();
      break;
  }

  return Win32Window::MessageHandler(hwnd, message, wparam, lparam);
}

bool FlutterWindow::RegisterSelectedHotkey(const std::string& preset) {
  const UINT previous_modifiers = hotkey_modifiers_;
  const UINT previous_key = hotkey_key_;
  UnregisterHotKey(GetHandle(), kTroikaHotkeyId);
  UINT modifiers = MOD_CONTROL | MOD_ALT | MOD_NOREPEAT;
  UINT key = VK_SPACE;
  if (preset == "ctrlShiftSpace") {
    modifiers = MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT;
  } else if (preset == "ctrlAltT") {
    key = 'T';
  }
  if (RegisterHotKey(GetHandle(), kTroikaHotkeyId, modifiers, key) != FALSE) {
    hotkey_modifiers_ = modifiers;
    hotkey_key_ = key;
    return true;
  }
  if (previous_modifiers != 0 && previous_key != 0) {
    RegisterHotKey(GetHandle(), kTroikaHotkeyId, previous_modifiers,
                   previous_key);
  }
  return false;
}

void FlutterWindow::ShowCompactWindow(bool always_on_top) {
  compact_mode_ = true;
  SetWindowText(GetHandle(), L"Тройка — Compact Assistant");
  const LONG_PTR style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU |
                         WS_MINIMIZEBOX | WS_THICKFRAME;
  SetWindowLongPtr(GetHandle(), GWL_STYLE, style);
  PlaceWindow(GetHandle(), 420, 560, true,
              always_on_top ? HWND_TOPMOST : HWND_NOTOPMOST);
}

void FlutterWindow::ShowCommandCenterWindow() {
  compact_mode_ = false;
  SetWindowText(GetHandle(), L"Тройка");
  SetWindowLongPtr(GetHandle(), GWL_STYLE, WS_OVERLAPPEDWINDOW);
  PlaceWindow(GetHandle(), 1280, 800, false, HWND_NOTOPMOST);
}

void FlutterWindow::SetAlwaysOnTop(bool enabled) {
  SetWindowPos(GetHandle(), enabled ? HWND_TOPMOST : HWND_NOTOPMOST, 0, 0, 0, 0,
               SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
}
