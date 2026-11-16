"""Stream PNGs in frame order from one or two render directories."""
from pathlib import Path
from shutil import copyfileobj
from subprocess import PIPE, Popen
import sys

def encode(primary, fallback, options):
    folders = [Path(primary), Path(fallback)] if fallback else [Path(primary)]
    inputs = []
    for frame in range(724):
        name = f"frame-{frame:04d}.png"
        image = next((folder / name for folder in folders if (folder / name).is_file()), None)
        if image is None:
            raise FileNotFoundError(name)
        inputs.append(image)
    with Popen(["ffmpeg", *options], stdin=PIPE) as pipe:
        assert pipe.stdin is not None
        try:
            for image in inputs:
                with image.open("rb") as source:
                    copyfileobj(source, pipe.stdin)
            pipe.stdin.close()
        except BrokenPipeError:
            return pipe.wait() or 1
        return pipe.wait()

if __name__ == "__main__":
    sys.exit(encode(sys.argv[1], sys.argv[2], sys.argv[3:]))
