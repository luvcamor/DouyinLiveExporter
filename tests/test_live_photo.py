import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

import imageio_ffmpeg
import piexif
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def boxes(data):
    """Independent reader for the small ISO boxes in test output."""
    result = []
    pos = 0
    while pos < len(data):
        size, kind = struct.unpack_from('>I4s', data, pos)
        header = 8
        if size == 1:
            size = struct.unpack_from('>Q', data, pos + 8)[0]
            header = 16
        if size == 0:
            size = len(data) - pos
        if size < header or pos + size > len(data):
            raise ValueError('Invalid box')
        result.append((kind, data[pos + header:pos + size]))
        pos += size
    return result


def child(data, kind):
    return next(payload for tag, payload in boxes(data) if tag == kind)


class LivePhotoTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('live_photo'),
                             'Missing real Live Photo conversion module')
        import live_photo
        self.converter = live_photo
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    def video(self, audio=True):
        path = self.root / '原始缓存.bin'
        args = [self.ffmpeg, '-v', 'error', '-f', 'lavfi', '-i',
                'testsrc2=size=96x128:rate=30:duration=1.2']
        if audio:
            args += ['-f', 'lavfi', '-i', 'sine=frequency=440:duration=1.2']
        args += ['-c:v', 'libx264', '-pix_fmt', 'yuv420p']
        if audio:
            args += ['-c:a', 'aac']
        subprocess.run(args + ['-f', 'mp4', str(path)], check=True, capture_output=True)
        return path

    def test_creates_matching_identifier_and_real_timed_metadata(self):
        source = self.video()
        original = source.read_bytes()
        result = self.converter.convert_live_photo(source, self.root / '输出', photo_format='jpeg')
        jpg, mov = Path(result['photo']), Path(result['video'])
        self.assertEqual(source.read_bytes(), original)
        with Image.open(jpg) as image:
            self.assertEqual(image.size, (96, 128))
        note = piexif.load(str(jpg))['Exif'][piexif.ExifIFD.MakerNote]
        self.assertEqual(note[:14], b'Apple iOS\0\0\x01MM')
        count = struct.unpack_from('>H', note, 14)[0]
        entries = [struct.unpack_from('>HHII', note, 16 + i * 12) for i in range(count)]
        tag, kind, length, offset = next(e for e in entries if e[0] == 17)
        self.assertEqual(kind, 2)
        identifier = note[offset:offset + length].rstrip(b'\0').decode()
        self.assertEqual(identifier, result['identifier'])
        data = mov.read_bytes()
        moov = child(data, b'moov')
        # AVFoundation ignores FFmpeg's moov/udta/meta for Live Photo pairing.
        # Require the native movie-level plain meta container explicitly.
        movie_meta = child(moov, b'meta')
        self.assertEqual(movie_meta[4:8], b'hdlr')
        item = child(child(movie_meta, b'ilst'), b'\0\0\0\1')
        self.assertEqual(child(item, b'data')[8:].decode(), identifier)
        tracks = [p for k, p in boxes(moov) if k == b'trak']
        meta = next(t for t in tracks
                    if child(child(t, b'mdia'), b'hdlr')[8:12] == b'meta')
        stbl = child(child(child(meta, b'mdia'), b'minf'), b'stbl')
        stsd = child(stbl, b'stsd')
        mebx = child(stsd[8:], b'mebx')
        key_entry = child(child(mebx[8:], b'keys'), b'\0\0\0\1')
        self.assertEqual(child(key_entry, b'keyd'),
                         b'mdtacom.apple.quicktime.still-image-time')
        self.assertEqual(child(key_entry, b'dtyp'), struct.pack('>II', 0, 65))
        offset = struct.unpack_from('>I', child(stbl, b'stco'), 8)[0]
        self.assertEqual(data[offset:offset + 9], b'\0\0\0\x09\0\0\0\x01\0')
        self.assertEqual(struct.unpack_from('>II', child(stbl, b'stsz'), 4), (9, 1))
        # A broken offset can leave tags intact while destroying playback.
        decoded = subprocess.run([self.ffmpeg, '-v', 'error', '-xerror', '-i', str(mov),
                                  '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-'],
                                 capture_output=True)
        self.assertEqual(decoded.returncode, 0, decoded.stderr.decode(errors='replace'))
        self.assertTrue(self.converter.verify_live_photo(jpg, mov)['valid'])

    def test_silent_video_is_supported_and_repeated_exports_do_not_overwrite(self):
        source = self.video(audio=False)
        first = self.converter.convert_live_photo(source, self.root / 'out')
        second = self.converter.convert_live_photo(source, self.root / 'out')
        self.assertNotEqual(first['photo'], second['photo'])
        self.assertNotEqual(first['identifier'], second['identifier'])
        self.assertTrue(Path(first['photo']).exists())

    def test_invalid_media_does_not_publish_a_pair(self):
        source = self.root / 'broken.bin'
        source.write_bytes(b'not a video' * 200)
        with self.assertRaises(self.converter.ConversionError):
            self.converter.convert_live_photo(source, self.root / 'out')
        self.assertFalse(list((self.root / 'out').glob('*/IMG_*.JPG')))
        self.assertTrue(source.exists())

    def test_mismatched_photo_and_video_fail_validation(self):
        source = self.video(audio=False)
        first = self.converter.convert_live_photo(source, self.root / 'out')
        second = self.converter.convert_live_photo(source, self.root / 'out')
        with self.assertRaises(self.converter.ConversionError):
            self.converter.verify_live_photo(Path(first['photo']), Path(second['video']))

    def test_corrupted_metadata_offset_fails_validation(self):
        result = self.converter.convert_live_photo(self.video(False), self.root / 'out')
        mov = Path(result['video'])
        data = bytearray(mov.read_bytes())
        # Our appended metadata track has the last chunk-offset table.
        at = data.rfind(b'stco')
        struct.pack_into('>I', data, at + 12, 0)
        mov.write_bytes(data)
        with self.assertRaises(self.converter.ConversionError):
            self.converter.verify_live_photo(Path(result['photo']), mov)


if __name__ == '__main__':
    unittest.main()
