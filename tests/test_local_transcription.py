import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from backend import local_transcription as asr
from backend.contracts import DomainError


class LocalTranscriptionTests(unittest.TestCase):
    def call(self,data=b'test',**extra):
        options=dict(filename='clip.wav',account_id='account',title='用户录音',permission_confirmed=True)
        options.update(extra)
        return asr.transcribe_upload(data,**options)

    def test_input_rejections_do_not_decode(self):
        with patch.object(asr,'_decode') as decode:
            for data,extra in [(b'',{}),(b'a'*(asr.MAX_BYTES+1),{}),('path/to/audio',{}),
                    (b'test',{'permission_confirmed':False}),(b'test',{'filename':'playlist.m3u8'}),
                    (b'test',{'title':''}),(b'test',{'account_id':''})]:
                with self.subTest(extra=extra),self.assertRaises(DomainError):self.call(data,**extra)
            decode.assert_not_called()

    def test_timestamps_provenance_private_temp_and_cleanup(self):
        seen=[]
        def decode(source,target,ext):
            self.assertEqual(source.stat().st_mode&0o777,0o600)
            self.assertEqual(target.stat().st_mode&0o777,0o600)
            self.assertEqual(source.name,'upload.wav');seen.append(source.parent)
            return 35
        segments=[{'start':0,'end':30,'text':'第一段'},{'start':30,'end':35,'text':'第二段'}]
        with patch.object(asr,'_decode',side_effect=decode),patch.object(asr,'_infer',return_value=segments):
            result=self.call(filename='../../secret.wav')
        self.assertFalse(seen[0].exists())
        self.assertIn('[30.00s–35.00s] 第二段',result['payload']['text'])
        self.assertEqual(result['payload']['content_kind'],'transcript')
        self.assertNotIn('用户录音',result['payload']['text'])
        self.assertEqual(len(result['provenance']['source_sha256']),64)

    def test_invalid_or_empty_segments(self):
        for segments in [[],[{'start':0,'end':5,'text':'x'}],[{'start':0,'end':1,'text':''}],
                         [{'start':0,'end':1,'text':'x'},{'start':0,'end':1,'text':'y'}]]:
            with patch.object(asr,'_decode',return_value=2),patch.object(asr,'_infer',return_value=segments):
                with self.assertRaises(DomainError):self.call()

    def test_timeout_is_safe_error(self):
        with patch('subprocess.run',side_effect=subprocess.TimeoutExpired('private-path',30)):
            with self.assertRaises(DomainError) as caught:asr._run(['test'],30)
        self.assertEqual(caught.exception.code,'TRANSCRIPTION_TIMEOUT')
        self.assertNotIn('private-path',str(caught.exception))

    def test_decode_missing_audio_unknown_duration_and_long(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            for info in ['Duration: N/A, Audio: aac','Duration: 00:02:01.00, Audio: aac','Duration: 00:00:03.00, Video: h264']:
                with patch.object(asr,'_run',return_value=subprocess.CompletedProcess([],1,b'',info.encode())):
                    with self.assertRaises(DomainError):asr._decode(Path(temp)/'in',Path(temp)/'out','.mp4')

    def test_actual_audio_size_bound_and_protocol_allowlist(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'out'
            def execute(args,timeout):
                self.assertIn('file,pipe',args)
                if '-y' in args:
                    with target.open('wb') as handle:handle.truncate((asr.MAX_SECONDS*asr.SAMPLE_RATE+1)*4)
                return subprocess.CompletedProcess(args,0,b'',b'Duration: 00:00:03.00, Audio: pcm')
            with patch.object(asr,'_run',side_effect=execute):
                with self.assertRaises(DomainError) as caught:asr._decode(Path(temp)/'in',target,'.wav')
            self.assertEqual(caught.exception.code,'MEDIA_TOO_LONG')

    def test_decode_failure_cleans_temp(self):
        paths=[]
        def fail(source,*args):
            paths.append(source.parent);raise DomainError('MEDIA_INVALID','invalid')
        with patch.object(asr,'_decode',side_effect=fail),self.assertRaises(DomainError):self.call()
        self.assertFalse(paths[0].exists())

    def test_whisper_uses_structured_output_to_preserve_eos(self):
        import numpy as np
        from types import SimpleNamespace
        from unittest.mock import Mock
        model=Mock()
        model.generation_config.eos_token_id=50257
        model.generate.return_value=SimpleNamespace(sequences=np.array([[50258,33,50257]]))
        features=SimpleNamespace(input_features='features',attention_mask='mask')
        ids=asr._generate(model,features)
        self.assertEqual(ids[0,-1],50257)
        self.assertTrue(model.generate.call_args.kwargs['return_dict_in_generate'])
        self.assertFalse(model.generate.call_args.kwargs['return_timestamps'])
        self.assertEqual(model.generate.call_args.kwargs['attention_mask'],'mask')
        model.generate.return_value=SimpleNamespace(sequences=np.array([[50258,33,44]]))
        with self.assertRaises(DomainError):asr._generate(model,features)
