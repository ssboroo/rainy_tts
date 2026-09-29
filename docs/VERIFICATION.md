# Verification — 2026-09-29

## Passed

- `python -m unittest discover -s tests -v`: 9 tests passed.
- `node --check app/static/app.js`: passed.
- Python source compilation: passed.
- Integration tests exercise registration, login/logout, origin/CSRF rejection, voice upload conversion with FFmpeg, private voice/job isolation, disabled-engine errors, durable queue submission, SRT overlap/overrun handling, and WAV/MP3 export.
- The automated worker-export test uses an **explicit test double**; it does not establish TTS quality.

## Real model CPU smoke test — passed, slow

Independent of the test double, downloaded the pinned Oron weights, its supplied female reference and pinned Vocos. Installed Oron 0.2.0 and F5-TTS 1.1.22. Ran the application's actual `OronEngine.synthesize` with `device='cpu'`, `use_ema=False`, 32 inference steps, `OMP_NUM_THREADS=2`, and `HF_HUB_OFFLINE=1`.

Input: `Сайн байна уу. Өнөөдөр сайхан өдөр байна.`

- WAV length: **2.731 seconds**.
- Cold generation time (including model load): **175.398 seconds**.
- Real-time factor: **64.233** (lower is better).
- Python: 3.12.14; CPU PyTorch/torchaudio: 2.8.0.
- Runtime RSS observed during generation: about 2.4 GB (not a rigorous peak measurement).
- Exact machine performance is not representative of every CPU server. No speed guarantee is made.

This is evidence that the candidate engine can generate audio on CPU, **not evidence of accurate Mongolian pronunciation, good acting, stable cloning or suitability for paid throughput**. No native-listener quality review was performed. The measured latency is too high to advertise instant generation. See `cpu-benchmark.json`.

The first attempt with unpinned latest torch/torchaudio failed because an audio codec tried loading a CUDA runtime. The matched 2.8.0 CPU pair fixed the attempted inference path. The model Dockerfile now uses that pair. Changes after the real run suppress reference-text stdout and clean upstream reference caches; those privacy wrappers have not undergone a second full model benchmark.

## Incomplete checks

- `agent-browser` was unavailable; Playwright's Chromium download failed with a truncated/invalid archive. Browser visual and interaction QA is **not claimed**.
- Docker is unavailable here; Compose and model-image builds need validation on the deployment host.
- No deployment/domain provisioning, payment verification, voice cloning evaluation, new voice design or emotion evaluation was completed.
- Commercial license review has not been completed. The production release flag remains false. Enabling it for a local technical smoke test is not a rights clearance.
