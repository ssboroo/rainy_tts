"""Normalize dubbing audio downloads to interoperable MP3 files."""
import mimetypes
from pathlib import Path
import subprocess
import tempfile


def dubbing_output(data, mime, kind):
    mime=mime.split(';')[0].strip().lower()
    audio=(mime.startswith('audio/') or 'audio' in kind.lower() or
           data.startswith((b'fLaC',b'ID3',b'OggS')) or
           (data.startswith(b'RIFF') and data[8:12]==b'WAVE') or
           (len(data)>1 and data[0]==255 and data[1]&224==224))
    if not audio:
        return data,mime,mimetypes.guess_extension(mime) or '.bin'
    with tempfile.TemporaryDirectory(prefix='rainy-dubbing-') as directory:
        source=Path(directory)/'source';output=Path(directory)/'audio.mp3'
        source.write_bytes(data)
        try:
            subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-i',str(source),
                            '-map','0:a:0','-vn','-codec:a','libmp3lame','-q:a','2',
                            str(output)],check=True,timeout=300,capture_output=True)
            result=output.read_bytes()
            if not result:raise ValueError('empty output')
        except (subprocess.SubprocessError,OSError,ValueError) as exc:
            raise ValueError('Орчуулсан аудиог MP3 болгож чадсангүй. Дахин шалгана уу.') from exc
    return result,'audio/mpeg','.mp3'
