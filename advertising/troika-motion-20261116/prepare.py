import argparse
from pathlib import Path
from shutil import copyfile


PROJECT = Path(__file__).resolve().parent
REPO = PROJECT.parents[1]


def main():
    parser = argparse.ArgumentParser(description="Copy Troika assets into the motion project.")
    parser.add_argument("--voice-dir", type=Path, required=True)
    parser.add_argument("--screen", type=Path, default=(
        REPO / "design" / "troika-ui-2026-11-13" / "android-dark-390.png"
    ))
    args = parser.parse_args()
    font_dir = REPO / "brand" / "troika" / "fonts"
    assets = {
        "public/android-home.png": args.screen,
        "public/logo-ru-reverse.svg": REPO / "hermes-android" / "assets" / "brand" / "logo-ru-reverse.svg",
        "public/GolosText-Variable.ttf": font_dir / "GolosText-Variable.ttf",
        "public/OFL.txt": font_dir / "OFL.txt",
        "materials/wake.mp3": args.voice_dir / "wake.mp3",
        "materials/remind.mp3": args.voice_dir / "remind.mp3",
    }
    for source in assets.values():
        if not source.is_file():
            parser.error(f"Missing asset {source}")
    for filename, source in assets.items():
        target = PROJECT / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        copyfile(source, target)


if __name__ == "__main__":
    main()
