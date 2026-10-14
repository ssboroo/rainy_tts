# RAINY AI Receptionist — Монгол веб MVP

## Одоогийн боломж
Админ Reception.ai цэсэнд үйлчилгээ (30/60/90/120 минут, MNT үнэ) нэмнэ, Улаанбаатарын цагаар Даваа–Бямба 09:00–18:00 бодит сул цаг шалгана, захиалга үүсгэнэ, цуцална.
Календарь Railway persistent /data SQLite volume-д хадгалагдана. Захиалга нь tenant/user_id-аар тусгаарлагдсан бөгөөд нэг бизнесийн нийт нэг хуваарийн давхардлыг BEGIN IMMEDIATE transaction-аар шалгана.
Ижил request_id + ижил payload дахин ирэхэд өмнөх үр дүнг буцаана. Нэг request_id өөр payload-д ашиглавал 409.

## Монгол дуут AI agent-ийн тохиргоо
ElevenLabs Conversational AI dashboard-д агент, Монгол хэлээр яриа таних/хариу өгөх STT/TTS, зөвлөмж, хэрэгслийг тохируулна. Railway-д ELEVENLABS_AGENT_ID болон LIVE_AGENT_ADMIN_PREVIEW_ENABLED=true байхад, мөн ELEVENLABS_API_KEY хүчинтэй бол админ Reception.ai доторх дуут веб туршилт идэвхжинэ.
Ярианы минутын provider зардал нь RAINY TTS кредитийн системээс тусдаа. Агент нь одоогоор зөвхөн админы микрофоны веб туршилт. SIP утасны дуудлага холбогдоогүй.

## Agent System Prompt (Монгол)
Та RAINY AI Receptionist. Үйлчлүүлэгчид Монгол хэлээр эелдэг, товч хариул. Үйлчилгээ ба үнийг хэзээ ч таамаглахгүй; эхлээд list_services ашигла. Үйлчилгээ, өдөр, цагийг үйлчлүүлэгчээс тодруулж, check_availability-аар зөвхөн бодит сул цагийг шалга. YYYY-MM-DD огноо, HH:MM Монголын цаг ашигла. Нэр, утас, үйлчилгээ, огноо, цагийг нэг удаа давтан хэлж зөвшөөрөл авсны дараа л book_appointment дууд. Нэг захиалгын retry бүрд ижил request_id ашигла; хэрэглэгч өөр захиалга эхлүүлэхэд шинэ request_id өг. Зөвхөн status=booked ба id буцаж ирсний дараа цаг баталгаажсан гэж хэл. 409 гарвал өөр цаг санал болго. Цуцлалт хүсвэл ажилтанд шилжүүл; AI-д цуцлах эрх байхгүй. Нэр/дугаар/цаг тодорхойгүй бол дахин асуу.

## API контракт
Admin /api/reception/services GET: {items:[{id,name,duration_minutes,price_mnt}]}
Admin /api/reception/services POST: {name,duration_minutes,price_mnt}
Admin /api/reception/availability GET: ?service_id=...&date=YYYY-MM-DD -> {date,service_id,timezone,slots:[HH:MM]}
Admin /api/reception/appointments POST: {service_id,date,time,caller_name,phone,request_id} -> {id,status,date,time,timezone}
Admin /api/reception/appointments GET: {items:[...]}
Admin /api/reception/appointments/{id}/cancel POST: {id,status:cancelled}
Agent /api/reception/hooks/{token}/list_services POST: {}
Agent /api/reception/hooks/{token}/check_availability POST: {service_id,date}
Agent /api/reception/hooks/{token}/book_appointment POST: {service_id,date,time,caller_name,phone,request_id}

Agent tool URL нь нууц bearer token агуулдаг; зөвхөн тохирсон агент дотор хадгал. Rotate-token хийхэд өмнөх холбоосууд хүчингүй болно.

## Үлдэж буй ажлууд
Монгол нэр, тоо, цагийн бодит дуут ярианы туршилт; ElevenLabs agent тохиргоо; операторын SIP/утасны дугаар; бизнес бүрийн цагийн хуваарь, олон ажилтан, амралтын өдөр, сануулга, Calendar sync, эрх ба минутын лимит, data retention. Нийтэд 24/7 дуудлага авдаг үйлчилгээ гэж тайлбарлахгүй.