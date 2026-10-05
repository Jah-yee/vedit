#!/usr/bin/env python3
"""vedit: simple video edits with ffmpeg and ImageMagick. Needs Python 3 and ffmpeg."""
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def fail(message):
    sys.exit(f"vedit: error: {message}")


def default_out(src, tag, ext=None):
    """Return the output path: <name>_<tag>.<ext> next to the input file."""
    return src.with_name(f"{src.stem}_{tag}{ext or src.suffix}")


def check_input(path):
    path = Path(path)
    if not path.is_file():
        fail(f"input file not found: {path}")
    return path


def run_ffmpeg(args, out, force, quiet=False):
    """Run ffmpeg with an argument list. Never use a shell."""
    if shutil.which("ffmpeg") is None:
        fail("ffmpeg is not installed or not in PATH")
    if out.exists() and not force:
        fail(f"output exists: {out} (use --force to overwrite)")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-stats", "-y", *args, str(out)]
    if subprocess.run(cmd).returncode != 0:
        fail("ffmpeg failed")
    if not quiet:
        # ffmpeg can exit with code 0 and write nothing, for example for a time after the end.
        if not out.exists():
            fail(f"ffmpeg wrote no output: {out}")
        print(f"wrote {out}")


def run_magick(tool, args, out, force):
    """Run ImageMagick 7 (`magick`) or 6 (`convert`, `montage`). tool is convert or montage."""
    if out.exists() and not force:
        fail(f"output exists: {out} (use --force to overwrite)")
    if shutil.which("magick"):
        cmd = ["magick"] + ([] if tool == "convert" else [tool])
    elif shutil.which(tool):
        cmd = [tool]
    else:
        fail("ImageMagick is not installed or not in PATH")
    if subprocess.run([*cmd, *args, str(out)]).returncode != 0:
        fail("ImageMagick failed")


def video_duration(src):
    """Return the length of a video in seconds."""
    if shutil.which("ffprobe") is None:
        fail("ffprobe is not installed or not in PATH")
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(src)],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout)
    except ValueError:
        fail(f"cannot read the length of {src}")


def cmd_trim(a):
    src = check_input(a.input)
    out = Path(a.output) if a.output else default_out(src, "trim")
    # ponytail: re-encodes for exact cuts, add a --fast stream copy mode if speed matters
    args = ["-i", str(src), "-ss", a.start]
    if a.end:
        args += ["-to", a.end]
    run_ffmpeg(args, out, a.force)


def cmd_join(a):
    srcs = [check_input(p) for p in a.inputs]
    out = Path(a.output) if a.output else default_out(srcs[0], "joined")
    # The concat list file needs a single quote written as '\''.
    lines = [f"file '{str(p.resolve()).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'" for p in srcs]
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("\n".join(lines) + "\n")
    try:
        # ponytail: ffmpeg scales later clips to the size of the first clip, no crossfade
        run_ffmpeg(["-f", "concat", "-safe", "0", "-i", f.name], out, a.force)
    finally:
        Path(f.name).unlink(missing_ok=True)


def cmd_speed(a):
    if not 0.5 <= a.factor <= 100:
        fail("factor must be from 0.5 to 100")
    src = check_input(a.input)
    out = Path(a.output) if a.output else default_out(src, f"x{a.factor:g}")
    run_ffmpeg(
        ["-i", str(src), "-vf", f"setpts=PTS/{a.factor}", "-af", f"atempo={a.factor}"],
        out, a.force,
    )


def cmd_gif(a):
    src = check_input(a.input)
    out = Path(a.output) if a.output else default_out(src, "gif", ".gif")
    graph = (
        f"fps={a.fps},scale={a.width}:-1:flags=lanczos,"
        "split[a][b];[a]palettegen[p];[b][p]paletteuse"
    )
    run_ffmpeg(["-i", str(src), "-vf", graph, "-loop", "0"], out, a.force)


def cmd_compress(a):
    src = check_input(a.input)
    out = Path(a.output) if a.output else default_out(src, "small", ".mp4")
    run_ffmpeg(
        ["-i", str(src), "-c:v", "libx264", "-crf", str(a.crf), "-preset", "medium",
         "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart"],
        out, a.force,
    )


def cmd_audio(a):
    src = check_input(a.input)
    out = Path(a.output) if a.output else default_out(src, "audio", ".mp3")
    # ffmpeg picks the audio format from the output extension: .mp3, .wav, .m4a, .flac
    run_ffmpeg(["-i", str(src), "-vn"], out, a.force)


def cmd_mute(a):
    src = check_input(a.input)
    out = Path(a.output) if a.output else default_out(src, "mute")
    run_ffmpeg(["-i", str(src), "-an", "-c:v", "copy"], out, a.force)


def cmd_frame(a):
    src = check_input(a.input)
    out = Path(a.output) if a.output else default_out(src, "frame", ".png")
    run_ffmpeg(["-ss", a.time, "-i", str(src), "-frames:v", "1"], out, a.force)


def cmd_resize(a):
    if a.width is None and a.height is None:
        fail("give --width or --height")
    for value in (a.width, a.height):
        # H.264 needs even sizes. The value -2 makes ffmpeg pick an even size for the other side.
        if value is not None and (value <= 0 or value % 2):
            fail("width and height must be even numbers above 0")
    src = check_input(a.input)
    out = Path(a.output) if a.output else default_out(src, "resized")
    scale = f"scale={a.width or -2}:{a.height or -2}"
    run_ffmpeg(["-i", str(src), "-vf", scale, "-c:a", "copy"], out, a.force)


ROTATE_FILTERS = {90: "transpose=1", 180: "hflip,vflip", 270: "transpose=2"}


def cmd_rotate(a):
    src = check_input(a.input)
    out = Path(a.output) if a.output else default_out(src, f"rot{a.degrees}")
    run_ffmpeg(["-i", str(src), "-vf", ROTATE_FILTERS[a.degrees], "-c:a", "copy"], out, a.force)


def cmd_title(a):
    m = re.fullmatch(r"(\d+)x(\d+)", a.size)
    if not m or int(m[1]) % 2 or int(m[2]) % 2 or 0 in (int(m[1]), int(m[2])):
        fail("size must be WIDTHxHEIGHT with even numbers, for example 1280x720")
    w, h = int(m[1]), int(m[2])
    out = Path(a.output) if a.output else Path("title.mp4")
    # ImageMagick reads a file for text that starts with @ and expands %w style codes.
    text = a.text.replace("%", "%%")
    if text.startswith("@"):
        text = "\\" + text
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "title.png"
        run_magick(
            "convert",
            ["-background", a.bg, "-fill", a.fg, "-gravity", "center",
             "-size", f"{w * 8 // 10}x{h * 8 // 10}", f"caption:{text}",
             "-extent", f"{w}x{h}"],
            png, True,
        )
        # The silent audio track lets the title card join with clips that have sound.
        run_ffmpeg(
            ["-loop", "1", "-framerate", str(a.fps), "-i", str(png),
             "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
             "-t", str(a.seconds), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"],
            out, a.force,
        )


def cmd_sheet(a):
    if a.cols < 1 or a.rows < 1:
        fail("cols and rows must be 1 or more")
    src = check_input(a.input)
    out = Path(a.output) if a.output else default_out(src, "sheet", ".jpg")
    if out.exists() and not a.force:
        fail(f"output exists: {out} (use --force to overwrite)")
    count = a.cols * a.rows
    length = video_duration(src)
    with tempfile.TemporaryDirectory() as tmp:
        # Take one frame from the middle of each equal part of the clip.
        run_ffmpeg(
            ["-ss", str(length / (2 * count)), "-i", str(src),
             "-vf", f"fps={count}/{length},scale={a.width}:-1", "-frames:v", str(count)],
            Path(tmp) / "%03d.png", True, quiet=True,
        )
        frames = sorted(Path(tmp).glob("*.png"))
        run_magick(
            "montage",
            [*map(str, frames), "-tile", f"{a.cols}x{a.rows}", "-geometry", "+4+4",
             "-background", "black"],
            out, a.force,
        )
    print(f"wrote {out}")


def build_parser():
    p = argparse.ArgumentParser(prog="vedit", description="Simple video edits with ffmpeg.")
    p.add_argument("-f", "--force", action="store_true", help="overwrite the output file")
    sub = p.add_subparsers(dest="command", required=True)

    def add(name, func, help_text):
        sp = sub.add_parser(name, help=help_text, description=help_text)
        sp.add_argument("-o", "--output", help="output file (default: next to the input)")
        sp.set_defaults(func=func)
        return sp

    sp = add("trim", cmd_trim, "cut a clip between two times")
    sp.add_argument("input")
    sp.add_argument("start", help="start time, for example 10 or 0:01:30.5")
    sp.add_argument("end", nargs="?", help="end time (default: end of the clip)")

    sp = add("join", cmd_join, "join clips one after the other")
    sp.add_argument("inputs", nargs="+", metavar="input")

    sp = add("speed", cmd_speed, "make a clip faster or slower")
    sp.add_argument("input")
    sp.add_argument("factor", type=float, help="2 is twice as fast, 0.5 is half speed")

    sp = add("gif", cmd_gif, "make a GIF from a clip")
    sp.add_argument("input")
    sp.add_argument("--fps", type=int, default=12)
    sp.add_argument("--width", type=int, default=480, help="width in pixels")

    sp = add("compress", cmd_compress, "make the file smaller (H.264)")
    sp.add_argument("input")
    sp.add_argument("--crf", type=int, default=28, help="quality, 18 is high, 35 is low")

    sp = add("title", cmd_title, "make a title card video (needs ImageMagick)")
    sp.add_argument("text")
    sp.add_argument("--seconds", type=float, default=3)
    sp.add_argument("--size", default="1280x720", help="WIDTHxHEIGHT, even numbers")
    sp.add_argument("--fps", type=int, default=25)
    sp.add_argument("--bg", default="black", help="background color")
    sp.add_argument("--fg", default="white", help="text color")

    sp = add("sheet", cmd_sheet, "make a contact sheet of frames (needs ImageMagick)")
    sp.add_argument("input")
    sp.add_argument("--cols", type=int, default=4)
    sp.add_argument("--rows", type=int, default=3)
    sp.add_argument("--width", type=int, default=320, help="width of each frame in pixels")

    sp = add("audio", cmd_audio, "save the sound of a clip as an audio file")
    sp.add_argument("input")

    sp = add("mute", cmd_mute, "remove the sound from a clip")
    sp.add_argument("input")

    sp = add("frame", cmd_frame, "save one frame of a clip as an image")
    sp.add_argument("input")
    sp.add_argument("time", help="time of the frame, for example 5 or 0:01:30")

    sp = add("resize", cmd_resize, "change the size of a clip")
    sp.add_argument("input")
    sp.add_argument("--width", type=int, help="width in pixels, an even number")
    sp.add_argument("--height", type=int, help="height in pixels, an even number")

    sp = add("rotate", cmd_rotate, "turn a clip clockwise")
    sp.add_argument("input")
    sp.add_argument("degrees", type=int, choices=sorted(ROTATE_FILTERS))
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    main()
