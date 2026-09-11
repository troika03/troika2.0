"""Start a private product STT worker using an existing product runtime."""

import argparse
import os
from pathlib import Path
import runpy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-home", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--model", default="base")
    parser.add_argument("--backend", choices=("local", "groq", "auto"), default="local")
    args = parser.parse_args()
    runtime = args.hermes_home.resolve()
    database = runtime / "troika_access.db"
    if not database.is_file():
        parser.error("Existing product runtime with troika_access.db is required")
    os.environ.update({
        "HERMES_HOME": str(runtime),
        "TROIKA_PRODUCT_AUTH_ENABLED": "true",
        "TROIKA_PRODUCT_AUTH_DB": str(database),
        "STT_PROXY_HOST": "127.0.0.1",
        "STT_PROXY_PORT": str(args.port),
        "STT_BACKEND": args.backend,
        "WHISPER_MODEL_SIZE": args.model,
    })
    runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "hermes-android" / "stt_proxy_server.py"),
        run_name="__main__",
    )


if __name__ == "__main__":
    main()
