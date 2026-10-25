#!/usr/bin/env python3
"""Cut raw.mp4 between two timestamps and wrap it with the open and close slides."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
PAD = "0xf2faff"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Slides come from index.html. Preview them at index.html#open and "
            "index.html#close.\n"
            "examples:\n"
            "  python cut.py --start 1:30 --end 8:45\n"
            "  python cut.py --start 90.5 --end 12:10 --hold 5 -o take.mp4"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--start", required=True, help="clip start: seconds, M:SS, or H:MM:SS")
    parser.add_argument("--end", required=True, help="clip end: seconds, M:SS, or H:MM:SS")
    parser.add_argument("--input", type=Path, default=ROOT / "raw.mp4")
    parser.add_argument("--output", type=Path, default=ROOT / "demo.mp4")
    parser.add_argument("--hold", type=float, default=4, help="seconds to hold the opening slide. The close is three times this")
    args = parser.parse_args(argv)

    source = args.input if args.input.is_absolute() else ROOT / args.input
    output = args.output if args.output.is_absolute() else ROOT / args.output
    if not source.is_file():
        print(f"missing input: {source}", file=sys.stderr)
        return 1
    if not CHROME.is_file():
        print(f"Chrome not found at {CHROME}", file=sys.stderr)
        return 1
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        print("ffmpeg and ffprobe need to be on PATH", file=sys.stderr)
        return 1

    try:
        start = parse_timestamp(args.start)
        end = parse_timestamp(args.end)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    if args.hold <= 0:
        print("--hold must be greater than zero", file=sys.stderr)
        return 1

    info = probe(source)
    duration = info["duration"]
    if end <= start:
        print(
            f"end ({format_timestamp(end)}) is not after start ({format_timestamp(start)})",
            file=sys.stderr,
        )
        return 1
    if start < 0 or end > duration + 0.05:
        print(
            f"clip {format_timestamp(start)}–{format_timestamp(end)} falls outside "
            f"{source.name} ({format_timestamp(duration)})",
            file=sys.stderr,
        )
        return 1

    width, height = info["width"], info["height"]
    fps = info["fps"]
    output.parent.mkdir(parents=True, exist_ok=True)
    crop = content_crop(source, start, end - start, width, height)
    print(f"Picture {crop.width}x{crop.height} inside {width}x{height}")

    with tempfile.TemporaryDirectory(prefix="demo-cut-") as tmp:
        work = Path(tmp)
        open_png = work / "open.png"
        close_png = work / "close.png"
        screenshot("open", open_png, crop.width, crop.height)
        screenshot("close", close_png, crop.width, crop.height)

        open_mp4 = work / "open.mp4"
        clip_mp4 = work / "clip.mp4"
        close_mp4 = work / "close.mp4"
        close_hold = args.hold * 3
        print(f"Opening slide ({args.hold:.1f}s)")
        render_slide(open_png, args.hold, open_mp4, crop.width, crop.height, fps, fade_in=False)
        print(f"Clip {format_timestamp(start)}–{format_timestamp(end)}")
        render_clip(source, start, end - start, clip_mp4, crop, fps, info["audio"])
        print(f"Closing slide ({close_hold:.1f}s)")
        render_slide(close_png, close_hold, close_mp4, crop.width, crop.height, fps)
        print(f"Writing {output}")
        concat([open_mp4, clip_mp4, close_mp4], work / "concat.txt", output)
        attach_poster(output, open_png)

    return 0


def parse_timestamp(value: str) -> float:
    text = value.strip()
    parts = text.split(":")
    try:
        if len(parts) == 1:
            seconds = float(parts[0])
        elif len(parts) == 2:
            seconds = int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        else:
            raise ValueError
    except ValueError:
        raise ValueError(f"not a timestamp: {value}") from None
    if seconds < 0:
        raise ValueError(f"not a timestamp: {value}")
    return seconds


def format_timestamp(seconds: float) -> str:
    whole = int(seconds)
    hours, rem = divmod(whole, 3600)
    minutes, secs = divmod(rem, 60)
    clock = f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
    fraction = seconds - whole
    if fraction >= 0.05:
        return f"{clock}.{int(round(fraction * 10))}"
    return clock


def probe(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-show_entries",
            "stream=codec_type,width,height,r_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or f"could not inspect {path}")
    payload = json.loads(result.stdout or "{}")
    video = next(stream for stream in payload["streams"] if stream["codec_type"] == "video")
    num, den = video["r_frame_rate"].split("/")
    return {
        "duration": float(payload["format"]["duration"]),
        "width": int(video["width"]),
        "height": int(video["height"]),
        "fps": float(num) / float(den),
        "audio": any(stream["codec_type"] == "audio" for stream in payload["streams"]),
    }


@dataclass(frozen=True)
class Crop:
    width: int
    height: int
    x: str
    y: int


def content_crop(source: Path, start: float, duration: float, width: int, height: int) -> Crop:
    """Crop away the black bars. Follow the picture if it slides sideways."""
    step = 30
    times = [start + 0.4]
    cursor = start + step
    while cursor < start + duration - 0.4:
        times.append(cursor)
        cursor += step
    if duration > 1:
        times.append(start + duration - 0.4)

    boxes = [_bounds(source, time, width, height) for time in times]
    content = [box for box in boxes if box is not None]
    if not content:
        return Crop(width - width % 2, height - height % 2, "0", 0)

    picture_w = max(x1 - x0 + 1 for x0, _, x1, _ in content)
    picture_h = max(y1 - y0 + 1 for _, y0, _, y1 in content)
    picture_w += picture_w % 2
    picture_h += picture_h % 2
    y = min(y0 for _, y0, _, _ in content)
    y -= y % 2

    pieces: list[tuple[float, int]] = []
    for index, box in enumerate(boxes):
        if box is None:
            continue
        x = box[0] - box[0] % 2
        if not pieces or abs(x - pieces[-1][1]) > 4:
            if pieces:
                changed = _switch_time(source, times[index - 1], times[index], pieces[-1][1], width, height)
                pieces.append((changed - start, x))
            else:
                pieces.append((0.0, x))

    # A sideways slide stays inside the frame. A real size change uses one box
    # big enough for every sample, so the edges are not cut off.
    widths = {x1 - x0 + 1 for x0, _, x1, _ in content}
    if max(widths) - min(widths) > 8:
        x0 = min(box[0] for box in content)
        x0 -= x0 % 2
        picture_w = max(box[2] for box in content) - x0 + 1
        picture_w += picture_w % 2
        return Crop(picture_w, picture_h, str(x0), y)

    return Crop(picture_w, picture_h, _x_expr(pieces), y)


def _switch_time(
    source: Path,
    before: float,
    after: float,
    previous_x: int,
    width: int,
    height: int,
) -> float:
    lo, hi = before, after
    while hi - lo > 0.05:
        mid = (lo + hi) / 2
        box = _bounds(source, mid, width, height)
        if box is not None and abs((box[0] - box[0] % 2) - previous_x) <= 4:
            lo = mid
        else:
            hi = mid
    return hi


def _x_expr(pieces: list[tuple[float, int]]) -> str:
    expr = str(pieces[-1][1])
    for index in range(len(pieces) - 2, -1, -1):
        boundary = pieces[index + 1][0]
        expr = f"if(lt(t,{boundary:.3f}),{pieces[index][1]},{expr})"
    return expr.replace(",", r"\,")


def _bounds(source: Path, time: float, width: int, height: int) -> tuple[int, int, int, int] | None:
    preroll = min(8.0, time)
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{time - preroll:.3f}",
            "-i",
            str(source),
            "-ss",
            f"{preroll:.3f}",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:",
        ],
        capture_output=True,
    )
    expected = width * height * 3
    if result.returncode != 0 or len(result.stdout) < expected:
        return None
    rgb = result.stdout
    stride = width * 3
    step = 4

    def column_has_ink(x: int) -> bool:
        offset = x * 3
        for y in range(0, height, step):
            pixel = y * stride + offset
            if rgb[pixel] > 12 or rgb[pixel + 1] > 12 or rgb[pixel + 2] > 12:
                return True
        return False

    xs = [x for x in range(width) if column_has_ink(x)]
    if not xs:
        return None
    x0, x1 = xs[0], xs[-1]

    def row_has_ink(y: int) -> bool:
        row = y * stride
        for x in range(x0, x1 + 1, 8):
            pixel = row + x * 3
            if rgb[pixel] > 12 or rgb[pixel + 1] > 12 or rgb[pixel + 2] > 12:
                return True
        return False

    ys = [y for y in range(height) if row_has_ink(y)]
    if not ys:
        return None
    return x0, ys[0], x1, ys[-1]


def screenshot(slide: str, dest: Path, width: int, height: int) -> None:
    url = (ROOT / "index.html").resolve().as_uri() + f"#{slide}"
    result = subprocess.run(
        [
            str(CHROME),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            "--default-background-color=FFF2FAFF",
            f"--window-size={width},{height}",
            "--virtual-time-budget=5000",
            f"--screenshot={dest}",
            url,
        ],
        capture_output=True,
        text=True,
    )
    if dest.is_file() and dest.stat().st_size > 0:
        return
    detail = (result.stderr or result.stdout or "").strip()
    raise SystemExit(detail[-2000:] or f"Chrome did not write {dest.name}")


def render_slide(
    png: Path,
    duration: float,
    dest: Path,
    width: int,
    height: int,
    fps: float,
    *,
    fade_in: bool = True,
) -> None:
    fade = min(0.4, duration / 4)
    # The opening card stays fully visible on the first frame. macOS builds the
    # file preview from that frame, and a fade-in from black becomes a black thumbnail.
    fades = [f"fade=t=out:st={max(duration - fade, 0):.3f}:d={fade:.3f}"]
    if fade_in:
        fades.insert(0, f"fade=t=in:st=0:d={fade:.3f}")
    video = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={PAD},"
        "setsar=1,fps="
        + str(fps)
        + ",format=yuv420p,"
        + ",".join(fades)
    )
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-loop",
            "1",
            "-i",
            str(png),
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-t",
            f"{duration:.3f}",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-vf",
            video,
            *encode(fps),
            str(dest),
        ]
    )


def render_clip(
    source: Path,
    start: float,
    duration: float,
    dest: Path,
    crop: Crop,
    fps: float,
    has_audio: bool,
) -> None:
    fade = min(0.05, duration / 4)
    video = (
        f"crop={crop.width}:{crop.height}:{crop.x}:{crop.y},"
        f"setsar=1,fps={fps},format=yuv420p"
    )
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(source),
    ]
    if not has_audio:
        command.extend(["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"])
    command.extend(["-t", f"{duration:.3f}", "-map", "0:v:0"])
    if has_audio:
        audio = (
            f"afade=t=in:st=0:d={fade:.3f},"
            f"afade=t=out:st={max(duration - fade, 0):.3f}:d={fade:.3f},"
            "aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo"
        )
        command.extend(["-map", "0:a:0", "-af", audio])
    else:
        command.extend(["-map", "1:a:0"])
    command.extend(["-vf", video, *encode(fps), str(dest)])
    run(command)


def concat(paths: list[Path], list_file: Path, output: Path) -> None:
    lines = ["file '" + path.resolve().as_posix().replace("'", r"'\''") + "'" for path in paths]
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            "-use_editlist",
            "0",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )


def attach_poster(video: Path, poster: Path) -> None:
    """Store the opening slide as the preview image. macOS uses it for the thumbnail."""
    temp = video.with_suffix(".tmp.mp4")
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-i",
            str(poster),
            "-map",
            "0",
            "-map",
            "1",
            "-c",
            "copy",
            "-disposition:v:1",
            "attached_pic",
            "-use_editlist",
            "0",
            "-movflags",
            "+faststart",
            str(temp),
        ]
    )
    temp.replace(video)


def encode(fps: float) -> list[str]:
    return [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-bf",
        "0",
        "-crf",
        "28",
        "-pix_fmt",
        "yuv420p",
        "-r",
        f"{fps}",
        "-fps_mode",
        "cfr",
        "-video_track_timescale",
        str(int(round(fps * 1000))),
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-ac",
        "2",
    ]


def run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise SystemExit(detail[-2000:] or "command failed")


if __name__ == "__main__":
    raise SystemExit(main())
