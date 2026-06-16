"""SAM 模型断点下载单元测试"""
import os
import tempfile
import unittest
from unittest import mock

from app.utils import sam_model_download as smd


class TestSamModelDownloadHelpers(unittest.TestCase):
    def test_parse_content_range_total(self):
        total = smd._parse_content_range_total('bytes 100-999/5000', 900, 100)
        self.assertEqual(total, 5000)

    def test_parse_content_range_fallback(self):
        total = smd._parse_content_range_total('', 900, 100)
        self.assertEqual(total, 1000)

    def test_download_source_defaults_to_modelscope(self):
        with mock.patch.object(smd, 'SAM_MODEL_DOWNLOAD_URL', ''):
            self.assertEqual(smd._download_source(), 'modelscope')
            self.assertTrue(smd._can_auto_download())

    def test_download_source_prefers_http_url(self):
        with mock.patch.object(smd, 'SAM_MODEL_DOWNLOAD_URL', 'http://example.com/model.pt'):
            self.assertEqual(smd._download_source(), 'http')

    def test_build_status_shows_resumable_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = os.path.join(tmp, 'sam3', 'sam3.1_multiplex.pt')
            partial_path = f'{model_path}.downloading'
            os.makedirs(os.path.dirname(model_path), exist_ok=True)
            with open(partial_path, 'wb') as f:
                f.write(b'x' * (50 * 1024 * 1024))

            with mock.patch.object(smd, 'SAM_MODEL_PATH', model_path), mock.patch.object(
                smd, 'SAM_MODEL_DOWNLOAD_URL', ''
            ), mock.patch.object(smd, '_state', {
                'status': 'error',
                'stage': 'error',
                'progress': 0,
                'downloaded_bytes': 0,
                'total_bytes': smd.ESTIMATED_MODEL_SIZE_BYTES,
                'error': 'network error',
            }):
                status = smd.get_sam_model_status()

            self.assertFalse(status['exists'])
            self.assertTrue(status['resumable'])
            self.assertEqual(status['source'], 'modelscope')
            self.assertEqual(status['modelscope_id'], 'facebook/sam3.1')
            self.assertEqual(status['downloaded_bytes'], 50 * 1024 * 1024)
            self.assertGreater(status['progress'], 0)

    def test_download_resumes_with_range_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = os.path.join(tmp, 'sam3', 'sam3.1_multiplex.pt')
            partial_path = f'{model_path}.downloading'
            os.makedirs(os.path.dirname(model_path), exist_ok=True)
            existing = b'a' * (120 * 1024 * 1024)
            with open(partial_path, 'wb') as f:
                f.write(existing)

            captured = {}

            class FakeResponse:
                status = 206
                headers = {
                    'Content-Length': str(len(existing)),
                    'Content-Range': f'bytes {len(existing)}-{len(existing) * 2 - 1}/{len(existing) * 2}',
                }

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def getcode(self):
                    return 206

                def read(self, size=-1):
                    if not hasattr(self, '_sent'):
                        self._sent = True
                        return existing
                    return b''

            def fake_urlopen(req, timeout=0):
                captured['range'] = req.headers.get('Range')
                return FakeResponse()

            with mock.patch.object(smd, 'SAM_MODEL_PATH', model_path), mock.patch(
                'urllib.request.urlopen', side_effect=fake_urlopen
            ):
                smd._download_http_with_progress('http://example.com/model.pt', partial_path)

            self.assertEqual(captured.get('range'), f'bytes={len(existing)}-')
            self.assertEqual(os.path.getsize(partial_path), len(existing) * 2)

    def test_modelscope_download_installs_weight(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = os.path.join(tmp, 'sam3', 'sam3.1_multiplex.pt')
            staging_dir = os.path.join(tmp, 'sam3', '.modelscope_staging')
            staging_file = os.path.join(staging_dir, 'sam3.1_multiplex.pt')
            os.makedirs(staging_dir, exist_ok=True)
            payload = b'w' * (120 * 1024 * 1024)
            with open(staging_file, 'wb') as f:
                f.write(payload)

            def fake_snapshot_download(**kwargs):
                self.assertEqual(kwargs['model_id'], 'facebook/sam3.1')
                self.assertEqual(kwargs['allow_file_pattern'], 'sam3.1_multiplex.pt')
                return staging_dir

            with mock.patch.object(smd, 'SAM_MODEL_PATH', model_path), mock.patch.object(
                smd, 'SAM_MODEL_DOWNLOAD_URL', ''
            ), mock.patch('modelscope.hub.snapshot_download.snapshot_download', fake_snapshot_download):
                smd._download_modelscope_with_progress()

            self.assertTrue(os.path.isfile(model_path))
            self.assertEqual(os.path.getsize(model_path), len(payload))


if __name__ == '__main__':
    unittest.main()
