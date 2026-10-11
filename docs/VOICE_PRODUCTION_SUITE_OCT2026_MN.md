# RAINY Voice Studio — Production Suite (2026-10-11)

RAINY Voice болон RAINY Video нь тусдаа OAuth, credit wallet, provider credentials-тай хэвээр.

## 1. Voice Director
- `POST /api/production/director` нь хэрэглэгчийн текстийг Eleven v4 tag-тай найруулж буцаана, credit **0**.
- Original болон directedText хоёул хариунд бий. Audio үүсээгүй; хэрэглэгч текстээ шалгаж `/api/jobs/quote`, `/api/jobs`-ээр үргэлжлүүлнэ.
- Tag нь чанарыг 100% батлахгүй; 12,000 тэмдэгтийн дээд хязгаар хэвээр.

## 2. Audiobook Producer
- `POST /api/production/audiobook/plan`: хамгийн ихдээ 80,000 тэмдэгт, 20 бүлэг, нэг бүлэг 10,000 тэмдэгт; free quote.
- Дуу үүсгэхэд `/api/jobs/quote`-ийг **бүлэг тус бүр** дахин дуудаж, нийт үнийг хэрэглэгч зөвшөөрсний дараа `/api/jobs` хэрэглэнэ.
- `/api/jobs` нь optional `maxCredits` параметртэй болж, баталсан дээд үнээс хэтэрвэл төлбөр суутгалгүй хаана.
- Нэг хэрэглэгч зэрэг **3 хүртэл** TTS ажил үүсгэнэ. UI нэг удаад 3 бүлэг илгээнэ, дараагийн багцыг хэрэглэгч үргэлжлүүлнэ. Өөрөө ар талд бүх бүлгийг scheduler-ээр үйлдвэрлэх, нэг MP3/M4B болгон нэгтгэх **одоогоор хийгдээгүй**.
- Бүлэг бүр `/api/jobs` болон бүтээлийн түүхэд тусдаа үлдэнэ.

## 3. Sentence Repair
- Засварлах текстээ шинэ богино TTS job-оор үүсгэнэ — **зөвхөн шинэ өгүүлбэр TTS кредит зарцуулна**.
- Хоёр ажил хоёулаа ижил хэрэглэгчийн `done` WAV байх ёстой.
- `POST /api/production/audio-patch`: original_job_id, correction_job_id, start_seconds, end_seconds.
- 24kHz mono PCM WAV, эх бичлэг <=600 сек, нэг засвар <=90 сек, ffmpeg timeout 120 сек, output <=20MB.
- FFmpeg өөрийн хадгалсан WAV-ийг л боловсруулна; дурын URL/файлын зам авахаас татгалзана.
- Сольсон MP3 нь `tool_jobs` болон artifact-д хадгалагдана. Гар ажиллагааны timecode шаардлагатай, автомат үг-таймлайн alignment болон арын хөгжимтэй холилдсон audio track засвар хийхгүй. Дууны урт өөрчлөгдөж болно.
- Тус засвар нь API төлбөргүй, серверийн нөөц ашигладаг тул цагийн хязгаартай.

## 4. Smart Transcript Editor
- Өмнөх Scribe v2 `polish` сонголт API-д `transcript_edit` ашигладаг байсан.
- Нэмэлт `edit_instruction` (хамгийн ихдээ 900 тэмдэгт) оруулж болно. Үндсэн текстийн утга, хэл, тоо, нэрийг хадгалах хамгаалалтын заавар тавина.
- Provider-ийн **30% нэмэлт** STT үнэ өмнөх `polish` кредит тооцоонд аль хэдийн багтсан, давхар тооцохгүй. `polish=false` үед энэ засвар хүлээж авахгүй.
- Эх transcript ба edited transcript тусдаа artifacts; үгийн timestamp нь **эх** бичвэрт хамаарна. Зассан текстэд SRT таймкод шинээр үнэн зөв болсон гэж үзэж болохгүй.
- Provider edit алдаа гарсан бол `edited_transcript.kind=error` ирж болзошгүй, original-ийг заавал хадгална.

## 5. Live Agent — зөвхөн админы preview
- `LIVE_AGENT_ADMIN_PREVIEW_ENABLED` анхдагч утга false.
- `ELEVENLABS_AGENT_ID`, `ELEVENLABS_API_KEY` баталгаажсан үед л админ preview API зөвшөөрнө.
- `GET /api/production/agent-status`; `POST /api/production/agent-session` нь admin-only, CSRF, rate-limited.
- Browser нь signed ElevenAgents WSS URL авч зөвхөн ElevenLabs-ийн баталгаат домэйнд холбогдоно. Secret key-г frontend-д илгээхгүй.
- **Voice credit wallet-аас төлбөр суутгахгүй ч provider жинхэнэ минутын өртөгтэй.** Одоохондоо энгийн хэрэглэгчдэд нээж болохгүй. Ажиллуулахын өмнө бодит agent ID, API service эрх, Монгол хэлний STT/TTS, minutes usage reconciliation, advance credit authorization, timeout, privacy, abuse controls болон cancellation QA хийнэ.
- Текстээс дуу realtime TTS нь **ElevenAgents full conversational product**-оос ялгаатай.

## Турших
```bash
python -m unittest discover -s tests -v
python -m compileall -q app
node --check app/static/app.js
```

CI PASS нь live ElevenLabs billing/provider session амжилтыг батлахгүй; үүнд тусдаа эзэмшигчийн live smoke-test шаардлагатай.
