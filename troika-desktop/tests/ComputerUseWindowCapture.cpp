#include <windows.h>
#include <d3d11.h>
#include <dwmapi.h>
#include <roapi.h>
#include <windows.graphics.capture.interop.h>
#include <windows.graphics.directx.direct3d11.interop.h>
#include <winrt/Windows.Foundation.Metadata.h>
#include <winrt/Windows.Graphics.Capture.h>
#include <winrt/Windows.Graphics.DirectX.Direct3D11.h>
#include <cstring>

using namespace winrt;
using namespace winrt::Windows::Graphics::Capture;
using namespace winrt::Windows::Graphics::DirectX;
using winrt::Windows::Graphics::DirectX::Direct3D11::IDirect3DDevice;
using ::Windows::Graphics::DirectX::Direct3D11::IDirect3DDxgiInterfaceAccess;

namespace {
constexpr int MaxWidth = 1280;
constexpr int MaxHeight = 800;
constexpr DWORD CaptureTimeout = 2500;

bool CanCapture(HWND window, DWORD expectedProcess) {
    DWORD process = 0;
    DWORD affinity = WDA_NONE;
    DWORD cloaked = 0;
    return GetWindowThreadProcessId(window, &process) && process == expectedProcess
        && GetAncestor(window, GA_ROOT) == window && IsWindowVisible(window) && !IsIconic(window)
        && SUCCEEDED(DwmGetWindowAttribute(window, DWMWA_CLOAKED, &cloaked, sizeof(cloaked))) && !cloaked
        && GetWindowDisplayAffinity(window, &affinity) && affinity == WDA_NONE;
}

struct RuntimeApartment {
    RuntimeApartment() { check_hresult(RoInitialize(RO_INIT_MULTITHREADED)); }
    ~RuntimeApartment() { RoUninitialize(); }
};

struct CaptureSession {
    Direct3D11CaptureFramePool pool;
    GraphicsCaptureSession session;
    ~CaptureSession() {
        try { session.Close(); } catch (...) {}
        try { pool.Close(); } catch (...) {}
    }
};

void ReadPixels(ID3D11Device* device, ID3D11DeviceContext* context, const Direct3D11CaptureFrame& frame,
        int width, int height, unsigned char* pixels, HANDLE cancel, ULONGLONG deadline) {
    auto access = frame.Surface().as<IDirect3DDxgiInterfaceAccess>();
    com_ptr<ID3D11Texture2D> texture;
    check_hresult(access->GetInterface(__uuidof(ID3D11Texture2D), texture.put_void()));
    D3D11_TEXTURE2D_DESC description{};
    texture->GetDesc(&description);
    if (description.Width != static_cast<UINT>(width) || description.Height != static_cast<UINT>(height)
            || description.Format != DXGI_FORMAT_B8G8R8A8_UNORM)
        throw hresult_error(E_INVALIDARG);

    description.Usage = D3D11_USAGE_STAGING;
    description.BindFlags = 0;
    description.MiscFlags = 0;
    description.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    com_ptr<ID3D11Texture2D> staging;
    check_hresult(device->CreateTexture2D(&description, nullptr, staging.put()));
    context->CopyResource(staging.get(), texture.get());
    D3D11_MAPPED_SUBRESOURCE mapped{};
    HRESULT ready;
    do {
        ready = context->Map(staging.get(), 0, D3D11_MAP_READ, D3D11_MAP_FLAG_DO_NOT_WAIT, &mapped);
    } while (ready == DXGI_ERROR_WAS_STILL_DRAWING && GetTickCount64() < deadline
        && WaitForSingleObject(cancel, 16) == WAIT_TIMEOUT);
    check_hresult(ready);
    auto row = static_cast<const unsigned char*>(mapped.pData);
    const auto rowBytes = static_cast<size_t>(width) * 4;
    for (int y = 0; y < height; ++y) {
        std::memcpy(pixels, row, rowBytes);
        pixels += rowBytes;
        row += mapped.RowPitch;
    }
    context->Unmap(staging.get(), 0);
}
}

extern "C" __declspec(dllexport) HRESULT CaptureWindowFrame(HWND window, DWORD process, HANDLE cancel,
        unsigned char* pixels, int capacity, int* width, int* height) noexcept {
    try {
        if (!CanCapture(window, process) || WaitForSingleObject(cancel, 0) != WAIT_TIMEOUT)
            return E_ACCESSDENIED;
        RuntimeApartment apartment;
        if (!GraphicsCaptureSession::IsSupported()) return HRESULT_FROM_WIN32(ERROR_NOT_SUPPORTED);
        auto interop = get_activation_factory<GraphicsCaptureItem, IGraphicsCaptureItemInterop>();
        GraphicsCaptureItem target{ nullptr };
        check_hresult(interop->CreateForWindow(window, guid_of<GraphicsCaptureItem>(), put_abi(target)));
        const auto size = target.Size();
        if (size.Width <= 0 || size.Height <= 0 || size.Width > MaxWidth || size.Height > MaxHeight
                || size.Width * size.Height * 4 > capacity) return E_INVALIDARG;

        com_ptr<ID3D11Device> device;
        com_ptr<ID3D11DeviceContext> context;
        check_hresult(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, D3D11_CREATE_DEVICE_BGRA_SUPPORT,
            nullptr, 0, D3D11_SDK_VERSION, device.put(), nullptr, context.put()));
        auto dxgi = device.as<IDXGIDevice>();
        com_ptr<IInspectable> inspectable;
        check_hresult(CreateDirect3D11DeviceFromDXGIDevice(dxgi.get(), inspectable.put()));
        auto pool = Direct3D11CaptureFramePool::CreateFreeThreaded(inspectable.as<IDirect3DDevice>(),
            DirectXPixelFormat::B8G8R8A8UIntNormalized, 1, size);
        CaptureSession capture{pool, pool.CreateCaptureSession(target)};
        auto& session = capture.session;
        if (winrt::Windows::Foundation::Metadata::ApiInformation::IsPropertyPresent(
                L"Windows.Graphics.Capture.GraphicsCaptureSession", L"IsCursorCaptureEnabled"))
            session.IsCursorCaptureEnabled(false);
        if (WaitForSingleObject(cancel, 0) != WAIT_TIMEOUT || !CanCapture(window, process)) return E_ABORT;
        session.StartCapture();
        const auto deadline = GetTickCount64() + CaptureTimeout;
        while (GetTickCount64() < deadline && WaitForSingleObject(cancel, 16) == WAIT_TIMEOUT) {
            auto frame = pool.TryGetNextFrame();
            if (!frame) continue;
            const auto content = frame.ContentSize();
            if (content.Width != size.Width || content.Height != size.Height || !CanCapture(window, process))
                return E_ACCESSDENIED;
            ReadPixels(device.get(), context.get(), frame, size.Width, size.Height, pixels, cancel, deadline);
            if (WaitForSingleObject(cancel, 0) != WAIT_TIMEOUT || !CanCapture(window, process))
                return E_ABORT;
            *width = size.Width;
            *height = size.Height;
            return S_OK;
        }
        return HRESULT_FROM_WIN32(ERROR_TIMEOUT);
    } catch (...) {
        return to_hresult();
    }
}
