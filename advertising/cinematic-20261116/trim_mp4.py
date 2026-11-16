"""Trim the MP4 presentation by 224 movie ticks, preserving the 724 CFR samples."""
from pathlib import Path
from struct import pack_into, unpack_from
import sys

TIMESCALE = 60_000
MASTER_DURATION = 724 * 1001
PRESENTATION_DURATION = 724_500

def boxes(data, start, end):
    while start + 8 <= end:
        length, kind = unpack_from(">I4s", data, start)
        header = 8
        if length == 1:
            length = unpack_from(">Q", data, start+8)[0]
            header = 16
        elif length == 0:
            length = end-start
        if length < header or start+length > end:
            raise ValueError(f"Invalid MP4 box {kind!r} at {start}")
        yield kind, start+header, start+length
        start += length

def child(data, parent, name):
    lo, hi = parent
    return next((start,end) for kind,start,end in boxes(data,lo,hi) if kind==name)

def set_duration(data, pos, offset_32, offset_64):
    if data[pos] == 0:
        fmt, at = ">I", pos+offset_32
    elif data[pos] == 1:
        fmt, at = ">Q", pos+offset_64
    else:
        raise ValueError(f"Unsupported MP4 box version at {pos}")
    previous = unpack_from(fmt,data,at)[0]
    if previous != MASTER_DURATION:
        raise ValueError(f"Expected {MASTER_DURATION} ticks at {at}, found {previous}")
    pack_into(fmt,data,at,PRESENTATION_DURATION)

def trim(source, destination):
    data = bytearray(source.read_bytes())
    moov = child(data,(0,len(data)),b"moov")
    mvhd, _ = child(data,moov,b"mvhd")
    if unpack_from(">I",data,mvhd+(12 if data[mvhd]==0 else 20))[0] != TIMESCALE:
        raise ValueError("Movie timescale must be 60000")
    set_duration(data,mvhd,16,24)

    tracks = [(start,end) for kind,start,end in boxes(data,*moov) if kind==b"trak"]
    video_tracks = 0
    for track in tracks:
        hdlr, _ = child(data,child(data,track,b"mdia"),b"hdlr")
        if data[hdlr+8:hdlr+12] != b"vide":
            continue
        video_tracks += 1
        tkhd, _ = child(data,track,b"tkhd")
        set_duration(data,tkhd,20,28)
        elst, _ = child(data,child(data,track,b"edts"),b"elst")
        if unpack_from(">I",data,elst+4)[0]!=1:
            raise ValueError("Expected a single video presentation edit")
        set_duration(data,elst,8,8)
    if video_tracks != 1:
        raise ValueError("Expected exactly one video track")
    destination.write_bytes(data)

if __name__ == "__main__":
    trim(Path(sys.argv[1]),Path(sys.argv[2]))
