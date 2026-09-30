# RAINY Voice · Монгол дууны онлайн студи

A CPU-first, self-hosted Mongolian voice studio for a **new independent domain**. Built for ssboroo. End users only need a browser.

> **Status: engineering pilot.** Web/API implementation is present; a real CPU inference smoke test passed, but commercial-license clearance and human voice-quality evaluation remain incomplete. This is not yet a deployed or payment-ready service. There is no fake speech generator.

## Хэрэгжсэн боломжууд

- Монгол интерфэйс, гар утсанд зохицох дууны студи.
- Имэйл/нууц үгийн бүртгэл, HttpOnly session, CSRF болон origin шалгалт.
- Хэрэглэгч тус бүрийн хувийн хоолойн сан: аудио upload, FFmpeg хөрвүүлэлт, transcript, зөвшөөрлийн баталгаа, сонсох/устгах.
- Монгол кирилл текст, дуудлагын толь, урт текст хуваах. Тоо, латин нэрийг буруу тааж уншихын оронд засуулах тодорхой алдаа.
- SRT parse, нэг хоолойгоор репликүүд үүсгэх, эхлэх хугацааг хадгалах, хугацаа хэтрэлтийг мэдээлэх.
- SQLite-д хадгалагдах ажлын дараалал, явц, түүх; worker дахин асахад тасарсан ажлыг сэргээх.
- WAV/MP3 татах; хэрэглэгч зөвхөн өөрийн аудиод хандана.
- Oron/F5-TTS CPU adapter: загвар бэлэн бус үед үүсгэхийг хаана.
- ElevenLabs **Eleven v4** cloud adapter: Монгол текстийг server-side API-аар үүсгэнэ; API key браузерт ил гарахгүй, Oron-той зэрэгцэн provider байдлаар ажиллана.
- Нэг серверт Docker Compose + шинэ домэйнд HTTPS proxy тохиргоо.

## Одоогоор баталгаажаагүй / дараагийн ажил

- Хүний сонсголоор монгол аудионы чанарыг үнэлэх, зорилтот серверийн хурдыг хэмжих. Эндхийн CPU smoke test: 2.731 секунд аудио / 175.398 секунд үүсгэлт.
- Арилжааны лицензийн бүрэн шалгалт, pinned model/dependency manifest.
- Хувийн reference-ээр хоолой дуурайлт: default OFF, зөвхөн туршилтын flag-тай.
- Emotion удирдлага, шинэ хоолой бүтээх, дүр бүрийн timeline editor, lip-sync.
- QPay, кредитийн бүртгэл, нууц үг сэргээх, үйлдвэрлэлийн мониторинг.

## Run

The web app has **zero pip dependencies**. Python 3.12+ and FFmpeg are required. Model inference has separate heavy dependencies and must be installed explicitly after review.

```bash
ALLOW_REGISTRATION=true PUBLIC_ORIGIN=http://localhost:8080 python -m app.server
# second terminal
python -m app.worker
# tests
python -m unittest discover -s tests -v
```

Open http://localhost:8080. With no configured engine the studio is honest about unavailability: registration, uploads and history work, synthesis returns 503.

For ElevenLabs Eleven v4, set the server-side values below in `.env` and restart both `web` and `worker`:

```env
ELEVENLABS_API_KEY=your_server_side_key
ELEVENLABS_VOICE_ID=your_mongolian_voice_id
ELEVENLABS_VOICE_LABEL=Монгол · Eleven v4
ELEVENLABS_LANGUAGE_CODE=mn
```

The worker calls `eleven_v4` and requests 24 kHz PCM, then writes normal WAV/MP3 outputs through the existing queue. ElevenLabs usage is billed and governed by your ElevenLabs account/plan. For the best Mongolian pronunciation, use a voice recorded or cloned from native Mongolian speech.

See [Deployment](docs/DEPLOY.md) for Windows, Docker and HTTPS, and [Model integration](docs/MODELS.md) for the engine details.

## Architecture

Browser → same-origin Python API → SQLite durable queue → single worker → Oron CPU **or** Eleven v4 cloud provider → private WAV/MP3 files.

Reference uploads and outputs are outside the public static directory. Authentication is required for every voice/job operation. CSRF tokens, strict same-site cookies, request size caps and per-user job limits are included. The service needs a hardened reverse proxy and the documented launch gates before public paid use.

## Ownership

Application code authored for **ssboroo / RAINY Voice**. Copyright © 2026 ssboroo. All rights reserved unless separately licensed. Upstream code, model weights, datasets and reference voices remain subject to their own licenses and rights. This notice does not claim ownership of upstream models.
