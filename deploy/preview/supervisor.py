"""Private bounded Docker launcher. No caller supplies commands or Docker flags."""

import argparse
import hmac
import http.server
import json
import re
import subprocess
import threading
import time
from pathlib import Path
import uuid


CAPACITY = threading.BoundedSemaphore(1)
MAX_BODY = 8 * 1024 * 1024


def run_job(data, *, image, seccomp):
    request = json.loads(data)
    if not isinstance(request, dict) or request.get("kind") not in {
        "web",
        "react_web",
        "office",
        "python_tests",
        "node_tests",
        "react_tests",
    }:
        raise ValueError("Unsupported check")
    name = "troika-preview-job-" + uuid.uuid4().hex
    args = [
        "docker",
        "run",
        "--rm",
        "--init",
        "--name",
        name,
        "--network",
        "none",
        "--read-only",
        "--user",
        "pwuser",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--security-opt",
        "seccomp=" + seccomp,
        "--memory",
        "512m",
        "--memory-swap",
        "768m",
        "--cpus",
        "0.75",
        "--pids-limit",
        "128",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=96m,uid=1001,gid=1001",
        "--tmpfs",
        "/work:rw,nosuid,nodev,size=64m,uid=1001,gid=1001",
        "--log-driver",
        "none",
        "-i",
        image,
        "python",
        "/runner/worker.py",
    ]
    process = subprocess.Popen(
        args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    captured = bytearray()
    overflow = threading.Event()

    def read(stream, keep):
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            if keep and len(captured) + len(chunk) <= 3 * 1024 * 1024:
                captured.extend(chunk)
            elif keep:
                overflow.set()

    readers = [
        threading.Thread(target=read, args=(process.stdout, True), daemon=True),
        threading.Thread(target=read, args=(process.stderr, False), daemon=True),
    ]
    for reader in readers:
        reader.start()
    try:
        process.stdin.write(data)
        process.stdin.close()
        deadline = time.monotonic() + 100
        while process.poll() is None:
            if overflow.is_set() or time.monotonic() >= deadline:
                raise TimeoutError("Isolated check exceeded its bounds")
            time.sleep(0.1)
        for reader in readers:
            reader.join(timeout=2)
        if overflow.is_set() or process.returncode != 0:
            raise ValueError("Isolated check did not finish")
        value = json.loads(captured)
        if not isinstance(value, dict) or value.get("status") not in {
            "rendered",
            "passed",
            "failed",
        }:
            raise ValueError("Invalid isolated check response")
        return value
    finally:
        # The name is generated here; cleanup never uses a client-supplied target.
        subprocess.run(["docker", "kill", name], capture_output=True, timeout=10)
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)


def serve(host, port, token_file, image, seccomp):
    token = Path(token_file).read_text().strip()
    if not re.fullmatch(r"[a-f0-9]{64}", token):
        raise ValueError("Invalid private preview credential")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
        raise ValueError("An immutable preview image is required")

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, value):
            data = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.path != "/check" or not hmac.compare_digest(
                self.headers.get("Authorization", ""), "Bearer " + token
            ):
                self.reply(401, {"error": "private_check_required"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= MAX_BODY:
                    raise ValueError()
            except ValueError:
                self.reply(413, {"error": "check_too_large"})
                return
            if not CAPACITY.acquire(timeout=1):
                self.reply(429, {"error": "check_capacity"})
                return
            try:
                self.connection.settimeout(20)
                data = self.rfile.read(size)
                if len(data) != size:
                    raise ValueError()
                self.reply(200, run_job(data, image=image, seccomp=seccomp))
            except Exception:
                self.reply(503, {"error": "isolated_check_unavailable"})
            finally:
                CAPACITY.release()

    http.server.ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ["host", "token-file", "image", "seccomp"]:
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--port", type=int, default=18768)
    args = parser.parse_args()
    serve(args.host, args.port, args.token_file, args.image, args.seccomp)
