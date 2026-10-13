from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import DouyinLivePhotoExporter as exporter
from live_photo import ConversionError


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        self.calls = []
        for name, value in [('OUTPUT_DIR', self.output), ('CONFIG', {'delete_after_export': True})]:
            patcher = patch.object(exporter, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def fake_adb(self, *args):
        self.calls.append(args)
        if args[0] == 'pull':
            Path(args[-1]).write_bytes(b'video payload' * 200)
        return subprocess.CompletedProcess(args, 0, '', '')

    def test_failed_pull_never_counts_partial_file_as_success(self):
        def failed_pull(*args):
            result = self.fake_adb(*args)
            result.returncode = 1
            return result
        with patch.object(exporter, 'adb', failed_pull):
            self.assertFalse(exporter.export_file('image_123'))
        self.assertFalse(any('rm' in args for args in self.calls))

    def test_conversion_failure_retains_original_and_remote(self):
        # The converter is the external media boundary for this ADB test.
        self.assertTrue(hasattr(exporter, 'convert_live_photo'), 'Exporter must convert to Live Photo')
        with patch.object(exporter, 'adb', self.fake_adb), patch.object(
                exporter, 'convert_live_photo', side_effect=ConversionError('bad video')):
            self.assertFalse(exporter.export_file('image_123'))
        self.assertFalse(any('rm' in args for args in self.calls))
        self.assertEqual(len(list((self.output / 'originals').glob('*.bin'))), 1)

    def test_delete_remote_only_after_pair_has_been_created(self):
        self.assertTrue(hasattr(exporter, 'convert_live_photo'), 'Exporter must convert to Live Photo')
        def convert(source, destination, **kwargs):
            self.assertTrue(Path(source).exists())
            self.assertFalse(any('rm' in args for args in self.calls))
            return {'photo': str(self.output / 'pair.JPG'), 'video': str(self.output / 'pair.MOV')}
        with patch.object(exporter, 'adb', self.fake_adb), patch.object(exporter, 'convert_live_photo', convert):
            self.assertTrue(exporter.export_file('image_123'))
        self.assertTrue(any('rm' in args for args in self.calls))


if __name__ == '__main__':
    unittest.main()
