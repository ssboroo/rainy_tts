import io
import json
import subprocess
import unittest
import wave

class DubbingFormatTests(unittest.TestCase):
    def test_octet_stream_flac_becomes_real_mp3(self):
        from app.media_formats import dubbing_output
        out=io.BytesIO()
        with wave.open(out,'wb') as w:
            w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0\0'*1600)
        flac=subprocess.run(['ffmpeg','-v','error','-f','wav','-i','pipe:0','-f','flac','pipe:1'],input=out.getvalue(),capture_output=True,check=True).stdout
        data,mime,ext=dubbing_output(flac,'application/octet-stream','lossless_audio')
        self.assertEqual((mime,ext),('audio/mpeg','.mp3'))
        result=subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_name','-of','json','-i','pipe:0'],input=data,capture_output=True,check=True)
        self.assertEqual(json.loads(result.stdout)['streams'][0]['codec_name'],'mp3')

    def test_non_audio_output_is_preserved(self):
        from app.media_formats import dubbing_output
        data=b'video-content'
        self.assertEqual(dubbing_output(data,'video/mp4','video'),(data,'video/mp4','.mp4'))

    def test_invalid_audio_is_rejected(self):
        from app.media_formats import dubbing_output
        with self.assertRaises(ValueError):dubbing_output(b'not audio','audio/flac','lossless_audio')
