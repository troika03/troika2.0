"""Trusted entry point for a disposable, networkless project container."""

import base64
from contextlib import contextmanager
import functools
import http.server
import io
import json
import mimetypes
from pathlib import Path, PurePosixPath
import re
import resource
import subprocess
import sys
import tempfile
import threading
from urllib.parse import unquote, urlsplit
import zipfile

ROOT = Path("/work/project")


def sources(value):
    if not isinstance(value, dict) or not 1 <= len(value) <= 100:
        raise ValueError("Invalid source project")
    result = {}
    total = 0
    for name, content in value.items():
        if (
            not isinstance(name, str)
            or len(name) > 240
            or "\\" in name
            or PurePosixPath(name).is_absolute()
            or any(
                p in {"", ".", "..", ".git", ".env", "node_modules", ".preview"}
                for p in name.split("/")
            )
            or re.search(r"[\x00-\x1f:]", name)
            or not isinstance(content, str)
        ):
            raise ValueError("Unsafe source path")
        data = content.encode("utf-8")
        total += len(data)
        if total > 2 * 1024 * 1024:
            raise ValueError("Source project exceeds limit")
        result[name] = data
    return result


def command(arguments, *, timeout=40):
    # Regular files in the bounded tmpfs cannot grow beyond this process limit.
    with tempfile.TemporaryFile() as output:
        try:
            completed = subprocess.run(
                arguments,
                cwd=ROOT,
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                env={
                    "PATH": "/usr/local/bin:/usr/bin:/bin",
                    "HOME": "/tmp",
                    "LANG": "C.UTF-8",
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                },
            )
            code = completed.returncode
        except subprocess.TimeoutExpired:
            code = -1
        output.seek(0)
        text = output.read(20000).decode("utf-8", errors="replace")
    return code, text


def run_tests(kind, files):
    styles = sorted(p for p in files if p.endswith(".css"))
    if styles and kind in {"node_tests", "react_tests"}:
        code, output = command(["node", "/runner/css_check.mjs", *[str(ROOT / p) for p in styles]])
        if code:
            return {"status": "failed", "tests": 0, "exit_code": code, "output": "CSS syntax errors:\n" + output}
    if kind == "python_tests":
        code, output = command(["python", "-I", "/runner/python_tests.py"])
        counts = re.findall(
            r"(\d+) (?:passed|failed|error)",
            output.splitlines()[-1] if output.splitlines() else "",
        )
        count = sum(map(int, counts))
    elif kind == "node_tests":
        paths = [
            name
            for name in files
            if name.endswith((".js", ".mjs", ".cjs"))
            and (
                name.startswith("test_")
                or ".test." in name
                or ".spec." in name
                or any(
                    p in {"test", "tests", "__tests__"} for p in name.split("/")[:-1]
                )
            )
        ]
        if not paths:
            return {
                "status": "failed",
                "tests": 0,
                "output": "No supported tests found",
            }
        code, output = command([
            "node",
            "--test",
            "--test-reporter=tap",
            *[str(ROOT / p) for p in sorted(paths)],
        ])
        count = re.search(r"# tests (\d+)", output)
    elif kind == "react_tests":
        (ROOT / "node_modules").symlink_to(
            "/runner/node_modules", target_is_directory=True
        )
        code, output = command([
            "node",
            "/runner/node_modules/vitest/vitest.mjs",
            "run",
            "--configLoader",
            "native",
            "--config",
            "/runner/vitest.config.mjs",
        ])
        try:
            report = json.loads(Path("/tmp/vitest-result.json").read_text())
            details = "\n".join(
                str(r.get("message", "")) for r in report.get("testResults", [])
            )
            output = (output + "\n" + details)[:20000]
            total = report.get("numTotalTests", 0)
            passed = report.get("numPassedTests", 0)
            return {
                "status": "passed"
                if code == 0
                and total > 0
                and total == passed
                and report.get("success") is True
                else "failed",
                "tests": total,
                "exit_code": code,
                "output": output,
            }
        except (OSError, ValueError):
            return {"status": "failed", "tests": 0, "exit_code": code, "output": output}
    else:
        raise ValueError("Unsupported execution environment")
    total = count if isinstance(count, int) else int(count.group(1)) if count else 0
    return {
        "status": "passed" if code == 0 and total > 0 else "failed",
        "tests": total,
        "exit_code": code,
        "output": output,
    }


@contextmanager
def web_server(files):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            name = unquote(urlsplit(self.path).path).lstrip("/") or "index.html"
            if name not in files:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header(
                "Content-Type", mimetypes.guess_type(name)[0] or "text/plain"
            )
            self.send_header("Content-Length", str(len(files[name])))
            self.send_header(
                "Content-Security-Policy",
                "connect-src 'none'; object-src 'none'; form-action 'none'",
            )
            self.end_headers()
            self.wfile.write(files[name])

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 8077), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:8077/"
    finally:
        server.shutdown()
        server.server_close()


def contact_sheet(images):
    from PIL import Image, ImageDraw

    cells = []
    bounds = []
    for label, data in images[:6]:
        image = Image.open(io.BytesIO(data)).convert("RGB")
        image.thumbnail((680, 850))
        cell = Image.new("RGB", (700, image.height + 40), "#d8d8d8")
        ImageDraw.Draw(cell).text((10, 5), label, fill="black")
        cell.paste(image, (10, 30))
        cells.append((cell, image.size, label))
    if not cells:
        raise ValueError("Renderer produced no image")
    heights = [max(cell[0].height for cell in cells[n:n + 2]) for n in range(0, len(cells), 2)]
    sheet = Image.new("RGB", (1400, sum(heights)), "#d8d8d8")
    row_y = 0
    for start in range(0, len(cells), 2):
        for column, (cell, size, label) in enumerate(cells[start:start + 2]):
            x = column * 700
            sheet.paste(cell, (x, row_y))
            bounds.append({"panel": label, "x": x + 10, "y": row_y + 30, "width": size[0], "height": size[1]})
        row_y += heights[start // 2]
    output = io.BytesIO()
    sheet.save(output, format="JPEG", quality=82)
    data = output.getvalue()
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("Preview image exceeds limit")
    return {
        "mime_type": "image/jpeg",
        "data": base64.b64encode(data).decode(),
        "panels": [label for label, _ in images[:6]],
        "panel_bounds": bounds,
    }


def preview_web(files, entry):
    if entry not in files or not entry.endswith((".html", ".htm")):
        raise ValueError("Missing HTML entry point")
    from playwright.sync_api import sync_playwright

    images, metrics = [], []
    with web_server(files) as origin, sync_playwright() as engine:
        browser = engine.chromium.launch(
            headless=True, chromium_sandbox=True, args=["--disable-dev-shm-usage"]
        )
        try:
            context = browser.new_context(
                service_workers="block", accept_downloads=False, reduced_motion="reduce"
            )
            context.route(
                "**/*",
                lambda route: (
                    route.continue_()
                    if route.request.url.startswith(origin)
                    or route.request.url.startswith(("data:", "blob:"))
                    else route.abort()
                ),
            )
            context.route_web_socket("**/*", lambda socket: socket.close())
            for width, height in [(1440, 960), (390, 844)]:
                page = context.new_page()
                page.set_viewport_size({"width": width, "height": height})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)[:300]))
                page.goto(origin + entry, wait_until="domcontentloaded", timeout=12000)
                page.wait_for_timeout(600)
                session = context.new_cdp_session(page)
                layout = session.send("Page.getLayoutMetrics")
                dimensions = {
                    "width": width,
                    "content_width": round(layout["cssContentSize"]["width"]),
                    "height": min(round(layout["cssContentSize"]["height"]), 12000),
                }
                travel = max(0, dimensions["height"] - layout["cssLayoutViewport"]["clientHeight"])
                scroll_samples = []
                for position in sorted({0, travel // 2, travel}):
                    page.evaluate("(y) => scrollTo({top: y, behavior: 'instant'})", position)
                    page.wait_for_timeout(150)
                    observed = round(session.send("Page.getLayoutMetrics")["cssLayoutViewport"]["pageY"])
                    scroll_samples.append({"requested": position, "observed": observed})
                    label = f"{width}px, y={observed}"
                    if observed != position:
                        label += f" (target {position})"
                    images.append((
                        label,
                        page.screenshot(type="jpeg", quality=82),
                    ))
                metrics.append({**dimensions, "javascript_errors": errors[:8], "scroll_samples": scroll_samples})
                session.detach()
                page.close()
        finally:
            browser.close()
    return {"status": "rendered", "image": contact_sheet(images), "metrics": metrics}


def build_web(files, entry):
    if entry not in files or not entry.endswith((".js", ".jsx", ".ts", ".tsx")):
        raise ValueError("Missing application entry point")
    (ROOT / "node_modules").symlink_to("/runner/node_modules", target_is_directory=True)
    code, output = command(["node", "/runner/build.mjs", entry])
    if code:
        return {
            "status": "failed",
            "tests": 0,
            "output": output,
            "environment": "react_build",
        }
    generated = {
        p.relative_to(ROOT).as_posix(): p.read_bytes()
        for p in (ROOT / ".preview").glob("*")
        if p.is_file()
    }
    html = next(
        (data.decode("utf-8") for path, data in files.items() if path == "index.html"),
        '<html><head></head><body><div id="root"></div></body></html>',
    )
    html = re.sub(
        r'<script\b[^>]*type=["\']module["\'][^>]*>.*?</script>',
        "",
        html,
        flags=re.S | re.I,
    )
    assets = '<script type="module" src="/.preview/app.js"></script>'
    if ".preview/app.css" in generated:
        assets += '<link rel="stylesheet" href="/.preview/app.css">'
    html = (
        html.replace("</body>", assets + "</body>")
        if "</body>" in html
        else html + assets
    )
    return preview_web(
        {**files, **generated, "index.html": html.encode()}, "index.html"
    )


def preview_office(kind, encoded, page_start=1):
    if kind not in {"docx", "pptx"}:
        raise ValueError("Unsupported document format")
    data = base64.b64decode(encoded, validate=True)
    if len(data) > 6 * 1024 * 1024:
        raise ValueError("Document exceeds preview limit")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > 2048 or sum(e.file_size for e in entries) > 32 * 1024 * 1024:
            raise ValueError("Document expands beyond limit")
        if any("vbaproject" in e.filename.lower() for e in entries):
            raise ValueError("Macros are not accepted")
    path = ROOT / ("document." + kind)
    path.write_bytes(data)
    code, _ = command(
        [
            "libreoffice",
            "-env:UserInstallation=file:///tmp/office-profile",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(ROOT),
            str(path),
        ],
        timeout=40,
    )
    pdf = ROOT / "document.pdf"
    if code or not pdf.is_file():
        raise ValueError("Document renderer did not produce a PDF")
    code, info = command(["pdfinfo", str(pdf)], timeout=10)
    pages = re.search(r"^Pages:\s+(\d+)", info, re.M)
    if code or not pages:
        raise ValueError("Document page count is unavailable")
    total = int(pages.group(1))
    if type(page_start) is not int or not 1 <= page_start <= total <= 100:
        raise ValueError("Invalid document page window")
    page_end = min(page_start + 5, total)
    code, _ = command(
        [
            "pdftoppm",
            "-f",
            str(page_start),
            "-l",
            str(page_end),
            "-scale-to",
            "1000",
            "-png",
            str(pdf),
            str(ROOT / "page"),
        ],
        timeout=20,
    )
    if code:
        raise ValueError("Document pages did not render")
    images = [(p.stem, p.read_bytes()) for p in sorted(ROOT.glob("page-*.png"))]
    return {
        "status": "rendered",
        "image": contact_sheet(images),
        "metrics": [],
        "pages_checked": len(images),
        "total_pages": total,
        "next_page": page_end + 1 if page_end < total else None,
    }


def main():
    resource.setrlimit(resource.RLIMIT_FSIZE, (24 * 1024 * 1024, 24 * 1024 * 1024))
    body = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
    if len(body) > 8 * 1024 * 1024:
        raise ValueError("Job exceeds input limit")
    request = json.loads(body)
    kind = request.get("kind")
    ROOT.mkdir(parents=True, exist_ok=True)
    if kind == "office":
        result = preview_office(
            request.get("format"),
            request.get("document", ""),
            request.get("page_start", 1),
        )
    else:
        files = sources(request.get("files"))
        for name, data in files.items():
            path = ROOT / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        if kind == "web":
            result = preview_web(files, request.get("entry", "index.html"))
        elif kind == "react_web":
            result = build_web(files, request.get("entry"))
        else:
            result = run_tests(kind, files)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(
            json.dumps({"status": "unavailable", "error": "isolated_check_failed"}),
            flush=True,
        )
        raise SystemExit(1)
