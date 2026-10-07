import base64
import io
import json
import subprocess
import unittest
from unittest.mock import patch

from backend import topic_encoder
from scripts import topic_encode


class TopicEncoderTests(unittest.TestCase):
    def valid_result(self):
        return {'model': topic_encoder.MODEL_NAME, 'dimension': 512, 'text_vectors': [[1.] + [0.] * 511], 'image_vectors': []}

    def test_protocol_keeps_sensitive_text_on_stdin_and_uses_fixed_program(self):
        result = self.valid_result()
        with patch.object(topic_encoder, 'availability', return_value={'ready': True}), patch.object(topic_encoder.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(result), '')) as run:
            self.assertEqual(topic_encoder.encode(['私密产品资料']), result)
            args, kw = run.call_args
            self.assertEqual(args[0], [str(topic_encoder.PYTHON), str(topic_encoder.SCRIPT)])
            self.assertNotIn('私密产品资料', str(args))
            self.assertIn('私密产品资料', kw['input'])
            self.assertEqual(kw['timeout'], 180)
            self.assertNotIn('shell', kw)

    def test_timeout_releases_slot_and_does_not_leak(self):
        with patch.object(topic_encoder, 'availability', return_value={'ready': True}), patch.object(topic_encoder.subprocess, 'run', side_effect=subprocess.TimeoutExpired('secret', 180)):
            with self.assertRaisesRegex(topic_encoder.TopicEncoderError, '耗时较长'):
                topic_encoder.encode(['测试'])
        self.assertTrue(topic_encoder._LOCK.acquire(blocking=False))
        topic_encoder._LOCK.release()

    def test_busy_no_subprocess(self):
        topic_encoder._LOCK.acquire()
        try:
            with patch.object(topic_encoder, 'availability', return_value={'ready': True}), patch.object(topic_encoder.subprocess, 'run') as run:
                with self.assertRaisesRegex(topic_encoder.TopicEncoderError, '另一批'):
                    topic_encoder.encode(['测试'])
                run.assert_not_called()
        finally:
            topic_encoder._LOCK.release()

    def test_missing_installation(self):
        with patch.object(topic_encoder, 'availability', return_value={'ready': False}):
            with self.assertRaisesRegex(topic_encoder.TopicEncoderError, '先安装'):
                topic_encoder.encode(['测试'])

    def test_rejects_nonfinite_and_wrong_count_dimension_norm(self):
        for mutate in (lambda x: x.update(dimension=256), lambda x: x.update(text_vectors=[]), lambda x: x['text_vectors'][0].__setitem__(1, float('nan')), lambda x: x['text_vectors'][0].__setitem__(0, 2.)):
            result = self.valid_result()
            mutate(result)
            with patch.object(topic_encoder, 'availability', return_value={'ready': True}), patch.object(topic_encoder.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(result), '')):
                with self.assertRaises(topic_encoder.TopicEncoderError):
                    topic_encoder.encode(['测试'])

    def test_library_error_not_exposed(self):
        with patch.object(topic_encoder, 'availability', return_value={'ready': True}), patch.object(topic_encoder.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, json.dumps({'error': '/home/private-secret'}), 'raw secret')):
            with self.assertRaises(topic_encoder.TopicEncoderError) as caught:
                topic_encoder.encode(['测试'])
            self.assertNotIn('secret', str(caught.exception))

    def test_payload_bounds(self):
        for payload in ({}, {'texts': ['']}, {'texts': ['x' * 10001]}, {'texts': ['x'] * 129}, {'texts': 'x'}, {'texts': [2]}, {'images': ['x'] * 65}):
            with self.assertRaises(ValueError):
                topic_encode.validate_payload(payload)

    def test_chunking_preserves_all_tokens(self):
        class Tokenizer:
            def encode(self, text, **kwargs):
                self.kwargs = kwargs
                return list(range(17))
        tok = Tokenizer()
        chunks = topic_encode.chunk_token_ids(tok, '任意长文', 6)
        self.assertEqual([len(c) for c in chunks], [6, 6, 5])
        self.assertEqual(sum(chunks, []), list(range(17)))
        self.assertFalse(tok.kwargs['truncation'])

    def test_images_are_rgb_without_metadata(self):
        from PIL import Image, PngImagePlugin
        image = Image.new('RGBA', (3, 4))
        meta = PngImagePlugin.PngInfo()
        meta.add_text('secret', 'private-location')
        buffer = io.BytesIO()
        image.save(buffer, format='PNG', pnginfo=meta)
        decoded = topic_encode.decode_image(base64.b64encode(buffer.getvalue()).decode())
        self.assertEqual(decoded.mode, 'RGB')
        self.assertEqual(decoded.info, {})

    def test_invalid_and_disallowed_images(self):
        from PIL import Image
        buffer = io.BytesIO()
        Image.new('RGB', (2, 2)).save(buffer, format='BMP')
        for value in ('bad', base64.b64encode(b'no image').decode(), base64.b64encode(buffer.getvalue()).decode()):
            with self.assertRaisesRegex(ValueError, '图片无效'):
                topic_encode.decode_image(value)

    def test_pixels_bound_and_exif_orientation(self):
        from PIL import Image
        buffer = io.BytesIO()
        exif = Image.Exif()
        exif[274] = 6
        Image.new('RGB', (3, 4)).save(buffer, format='JPEG', exif=exif)
        data = base64.b64encode(buffer.getvalue()).decode()
        self.assertEqual(topic_encode.decode_image(data).size, (4, 3))
        with patch.object(topic_encode, 'MAX_PIXELS', 5):
            with self.assertRaisesRegex(ValueError, '图片无效'):
                topic_encode.decode_image(data)


if __name__ == '__main__':
    unittest.main()
