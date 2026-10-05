"""Check each vedit command on a short generated clip. Run: python3 -m unittest"""
import subprocess
import tempfile
import unittest
from pathlib import Path

import vedit


def duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout)


class VeditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        # A 4 second clip with video and audio. The name has a space and a quote.
        self.clip = self.dir / "my 'clip'.mp4"
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=4",
             "-f", "lavfi", "-i", "sine=duration=4", "-shortest", str(self.clip)],
            check=True,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_trim(self):
        out = self.dir / "t.mp4"
        vedit.main(["trim", str(self.clip), "1", "3", "-o", str(out)])
        self.assertAlmostEqual(duration(out), 2, delta=0.2)

    def test_join(self):
        out = self.dir / "j.mp4"
        vedit.main(["join", str(self.clip), str(self.clip), "-o", str(out)])
        self.assertAlmostEqual(duration(out), 8, delta=0.3)

    def test_speed(self):
        out = self.dir / "s.mp4"
        vedit.main(["speed", str(self.clip), "2", "-o", str(out)])
        self.assertAlmostEqual(duration(out), 2, delta=0.3)

    def test_gif(self):
        out = self.dir / "g.gif"
        vedit.main(["gif", str(self.clip), "-o", str(out)])
        self.assertTrue(out.stat().st_size > 0)

    def test_compress(self):
        out = self.dir / "c.mp4"
        vedit.main(["compress", str(self.clip), "-o", str(out)])
        self.assertTrue(out.stat().st_size > 0)

    def test_title_joins_with_clip(self):
        card = self.dir / "card.mp4"
        vedit.main(["title", "Hello 100%", "--seconds", "2", "--size", "320x240", "-o", str(card)])
        self.assertAlmostEqual(duration(card), 2, delta=0.2)
        out = self.dir / "tj.mp4"
        vedit.main(["join", str(card), str(self.clip), "-o", str(out)])
        self.assertAlmostEqual(duration(out), 6, delta=0.3)

    def test_title_text_is_not_read_as_a_file(self):
        # ImageMagick would try to open this path if the text were not escaped.
        card = self.dir / "at.mp4"
        vedit.main(["title", "@/no/such/file", "--size", "320x240", "-o", str(card)])
        self.assertTrue(card.stat().st_size > 0)

    def test_title_odd_size(self):
        with self.assertRaises(SystemExit):
            vedit.main(["title", "x", "--size", "321x240"])

    def test_sheet(self):
        out = self.dir / "sheet.png"
        vedit.main(["sheet", str(self.clip), "--cols", "3", "--rows", "2", "--width", "100", "-o", str(out)])
        size = subprocess.run(
            ["magick", "identify", "-format", "%wx%h", str(out)],
            capture_output=True, text=True, check=True,
        ).stdout
        # Each tile is 100x75 plus 4 pixels of border on every side.
        self.assertEqual(size, f"{3 * 108}x{2 * 83}")

    def test_no_overwrite_without_force(self):
        out = self.dir / "o.mp4"
        out.write_text("x")
        with self.assertRaises(SystemExit):
            vedit.main(["compress", str(self.clip), "-o", str(out)])
        self.assertEqual(out.read_text(), "x")

    def test_missing_input(self):
        with self.assertRaises(SystemExit):
            vedit.main(["trim", str(self.dir / "none.mp4"), "1"])


if __name__ == "__main__":
    unittest.main()
