"""Bounded, memory-only PNG input for the Windows test capture paths."""

import base64
import io
import struct


MAX_FRAME_BYTES = 1024 * 1024


def clean_png(raw):
    from PIL import Image

    if len(raw) < 33 or len(raw) > MAX_FRAME_BYTES or raw[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR":
        raise ValueError("invalid PNG")
    width, height = struct.unpack(">II", raw[16:24])
    if not (0 < width <= 1280 and 0 < height <= 800):
        raise ValueError("frame dimensions out of bounds")
    with Image.open(io.BytesIO(raw), formats=["PNG"]) as image:
        if image.n_frames != 1 or image.size != (width, height):
            raise ValueError("expected one frame")
        image.verify()
    with Image.open(io.BytesIO(raw), formats=["PNG"]) as image, io.BytesIO() as output:
        with Image.frombytes("RGB", image.size, image.convert("RGB").tobytes()) as clean:
            clean.save(output, format="PNG")
        if output.tell() > MAX_FRAME_BYTES:
            raise ValueError("normalized frame is too large")
        return output.getvalue()


def vision_input(text, frame):
    return [{"type": "text", "text": text},
            {"type": "image_url", "image_url": {
                "url": "data:image/png;base64," + base64.b64encode(frame).decode("ascii"),
            }}]
