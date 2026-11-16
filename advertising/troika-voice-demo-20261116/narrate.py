import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "release-20261115"))
import voice


if __name__ == "__main__":
    voice.OUT = ROOT / "materials"
    voice.SPEC = json.loads((ROOT / "narration.json").read_text(encoding="utf-8"))
    voice.SPEC["instructions"] = (voice.OUT / "narration-direction.txt").read_text(encoding="utf-8").strip()
    voice.generate()
