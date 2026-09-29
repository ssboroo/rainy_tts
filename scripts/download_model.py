"""Download explicit revisions and record hashes. Never enables commercial release."""
import hashlib
import json
import os
from pathlib import Path
from huggingface_hub import snapshot_download

root = Path(os.getenv('MODEL_DIR', './models/oron'))
revision = '86946b23a59753dc6a074f59a81dc717b4d18535'
files = ['model.safetensors', 'vocab.txt', 'voices/male.wav', 'voices/male.txt', 'voices/female.wav', 'voices/female.txt', 'README.md']
snapshot_download('btsee/oron-tts', revision=revision, local_dir=root, allow_patterns=files)
snapshot_download('charactr/vocos-mel-24khz', revision='0feb3fdd929bcd6649e0e7c5a688cf7dd012ef21', local_dir=root / 'vocos', allow_patterns=['config.yaml', 'pytorch_model.bin', 'README.md'])
files += ['vocos/config.yaml', 'vocos/pytorch_model.bin']
manifest = {'vocoder_revision':'0feb3fdd929bcd6649e0e7c5a688cf7dd012ef21','model':'btsee/oron-tts','revision':revision,'commercial_review':'pending','sha256':{}}
for name in files:
    path = root / name
    if not path.is_file():
        raise RuntimeError(f'Missing required model file: {name}')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    manifest['sha256'][name] = digest.hexdigest()
(root / 'manifest.json').write_text(json.dumps(manifest, indent=2))
print('Model downloaded; license review and audio quality validation remain required.')
