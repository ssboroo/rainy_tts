"""Thin server-side client for ElevenLabs Creative API tools."""
import json
import os
import httpx

API_BASE = "https://api.elevenlabs.io"

class ElevenAPIError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status

class ElevenTools:
    def __init__(self, api_key=None):
        self.api_key=(api_key or os.getenv("ELEVENLABS_API_KEY","")).strip()

    def _headers(self):
        if not self.api_key:
            raise ElevenAPIError(503,"ELEVENLABS_API_KEY тохируулаагүй байна.")
        return {"xi-api-key":self.api_key}

    @staticmethod
    def _meta(response):
        headers=response.headers or {}
        return {
            "character_cost":headers.get("character-cost"),
            "request_id":headers.get("request-id"),
            "trace_id":headers.get("x-trace-id"),
        }

    async def _request(self, method, path, **kwargs):
        headers=dict(self._headers())
        headers.update(kwargs.pop("headers",{}))
        timeout=kwargs.pop("timeout",180)
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout,connect=20),follow_redirects=True) as client:
            response=await client.request(method,API_BASE+path,headers=headers,**kwargs)
        if response.status_code >= 400:
            message=f"ElevenLabs API алдаа ({response.status_code})."
            try:
                detail=response.json().get("detail")
                if isinstance(detail,dict):
                    message=detail.get("message") or message
                elif isinstance(detail,str):
                    message=detail
            except Exception:
                pass
            raise ElevenAPIError(response.status_code,message)
        return response

    async def clone_voice(self, name, uploads, description="", remove_background_noise=False):
        files=[]
        for upload in uploads:
            await upload.seek(0)
            files.append(("files[]",(upload.filename,upload.file,upload.content_type or "audio/mpeg")))
        data={
            "name":name[:100],
            "description":description[:500],
            "remove_background_noise":"true" if remove_background_noise else "false",
        }
        response=await self._request("POST","/v1/voices/add",files=files,data=data,timeout=240)
        result=response.json()
        if isinstance(result,dict):
            result["_provider_usage"]=self._meta(response)
        return result

    async def delete_voice(self, voice_id):
        response=await self._request("DELETE",f"/v1/voices/{voice_id}")
        return response.json()

    async def get_voice(self, voice_id):
        response=await self._request("GET",f"/v1/voices/{voice_id}")
        return response.json()

    async def find_shared_voice(self, voice_id):
        response=await self._request(
            "GET","/v1/shared-voices",
            params={"search":voice_id,"page_size":100,"include_custom_rates":"true"}
        )
        voices=response.json().get("voices",[])
        return next((voice for voice in voices if voice.get("voice_id")==voice_id),None)

    async def add_shared_voice(self, public_owner_id, voice_id, new_name):
        response=await self._request(
            "POST",f"/v1/voices/add/{public_owner_id}/{voice_id}",
            json={"new_name":new_name[:100],"bookmarked":True}
        )
        return response.json()

    async def find_saved_shared_voice(self, source_voice_id):
        token=None
        for _ in range(10):
            params={"page_size":100,"voice_type":"community","include_total_count":"false"}
            if token:
                params["next_page_token"]=token
            response=await self._request("GET","/v2/voices",params=params)
            data=response.json()
            for voice in data.get("voices",[]):
                sharing=voice.get("sharing") or {}
                if voice.get("voice_id")==source_voice_id or sharing.get("original_voice_id")==source_voice_id:
                    return voice
            if not data.get("has_more"):
                break
            token=data.get("next_page_token")
            if not token:
                break
        return None

    async def dialogue(self, inputs, language_code="mn"):
        payload={"inputs":inputs,"model_id":"eleven_v4","language_code":language_code or None}
        response=await self._request(
            "POST","/v1/text-to-dialogue",
            params={"output_format":"mp3_44100_128"},
            json=payload,timeout=240
        )
        return response.content, self._meta(response)

    async def music(self, prompt, length_ms, model_id="music_v2_5", force_instrumental=False):
        payload={
            "prompt":prompt,
            "music_length_ms":int(length_ms),
            "model_id":model_id,
            "force_instrumental":bool(force_instrumental),
        }
        response=await self._request(
            "POST","/v1/music",
            params={"output_format":"mp3_48000_192" if model_id in {"music_v2","music_v2_5"} else "mp3_44100_128"},
            json=payload,timeout=360
        )
        return response.content, self._meta(response)

    async def sound_effect(self, text, duration_seconds=None, loop=False, prompt_influence=0.3):
        payload={
            "text":text,
            "model_id":"eleven_text_to_sound_v2",
            "loop":bool(loop),
            "prompt_influence":float(prompt_influence),
        }
        if duration_seconds is not None:
            payload["duration_seconds"]=float(duration_seconds)
        response=await self._request(
            "POST","/v1/sound-generation",
            params={"output_format":"mp3_44100_128"},
            json=payload,timeout=180
        )
        return response.content, self._meta(response)

    async def speech_to_text(
        self, upload, language_code="mn", keyterms=None, polish=True,
        diarize=False, num_speakers=1, no_verbatim=True
    ):
        await upload.seek(0)
        multipart=[
            ("file",(upload.filename,upload.file,upload.content_type or "application/octet-stream")),
            ("model_id",(None,"scribe_v2")),
            ("timestamps_granularity",(None,"word")),
            ("temperature",(None,"0")),
            ("tag_audio_events",(None,"false")),
            ("diarize",(None,"true" if diarize else "false")),
            ("no_verbatim",(None,"true" if no_verbatim else "false")),
        ]
        if language_code:
            multipart.append(("language_code",(None,language_code)))
        if diarize and num_speakers:
            multipart.append(("num_speakers",(None,str(int(num_speakers)))))
        for term in keyterms or []:
            multipart.append(("keyterms",(None,term)))
        if polish:
            if (language_code or "").lower()=="mn":
                edit_instruction=(
                    "Keep the transcript in Mongolian. Do not translate. Correct only obvious "
                    "Mongolian spelling, punctuation, capitalization, spacing, and formatting. "
                    "Preserve the spoken meaning exactly. Do not add, remove, summarize, or invent "
                    "content. Preserve names, brands, technical terms, numbers, dates, URLs, and "
                    "foreign words as spoken."
                )
            else:
                edit_instruction=(
                    "Keep the transcript in the original spoken language. Do not translate. "
                    "Correct only obvious spelling, punctuation, capitalization, spacing, and "
                    "formatting. Preserve the spoken meaning exactly. Do not add, remove, summarize, "
                    "or invent content. Preserve names, brands, technical terms, numbers, dates, URLs, "
                    "and foreign words as spoken."
                )
            multipart.append(("transcript_edit",(None,edit_instruction)))
        response=await self._request("POST","/v1/speech-to-text",files=multipart,timeout=360)
        data=response.json()
        if isinstance(data,dict):
            data["_provider_usage"]=self._meta(response)
        return data

    async def voice_changer(self, upload, voice_id, remove_background_noise=False):
        await upload.seek(0)
        files={"audio":(upload.filename,upload.file,upload.content_type or "audio/mpeg")}
        data={
            "model_id":"eleven_multilingual_sts_v2",
            "remove_background_noise":"true" if remove_background_noise else "false",
        }
        response=await self._request(
            "POST",f"/v1/speech-to-speech/{voice_id}",
            params={"output_format":"mp3_44100_128"},
            files=files,data=data,timeout=300
        )
        return response.content, self._meta(response)

    async def voice_isolator(self, upload):
        await upload.seek(0)
        files={"audio":(upload.filename,upload.file,upload.content_type or "application/octet-stream")}
        response=await self._request(
            "POST","/v1/audio-isolation/stream",
            files=files,
            data={"file_format":"other"},
            timeout=360
        )
        return response.content, {
            "request_id":response.headers.get("request-id"),
            "trace_id":response.headers.get("x-trace-id"),
            "mime":response.headers.get("content-type","audio/mpeg").split(";")[0],
        }

    async def pvc_create(self, name, language="mn", description=""):
        response=await self._request(
            "POST","/v1/voices/pvc",
            json={"name":name[:100],"language":language,"description":description[:500] or None},
            timeout=120
        )
        return response.json()

    async def pvc_add_samples(self, voice_id, uploads, remove_background_noise=False):
        files=[]
        for upload in uploads:
            await upload.seek(0)
            files.append(("files[]",(upload.filename,upload.file,upload.content_type or "audio/mpeg")))
        response=await self._request(
            "POST",f"/v1/voices/pvc/{voice_id}/samples",
            files=files,
            data={"remove_background_noise":"true" if remove_background_noise else "false"},
            timeout=600
        )
        return response.json()

    async def pvc_get_captcha(self, voice_id):
        response=await self._request("GET",f"/v1/voices/pvc/{voice_id}/captcha",timeout=120)
        try:
            data=response.json()
        except Exception:
            data=response.text
        if isinstance(data,str):
            return {"captcha":data}
        return data

    async def pvc_verify_captcha(self, voice_id, recording):
        await recording.seek(0)
        files={"recording":(recording.filename,recording.file,recording.content_type or "audio/mpeg")}
        response=await self._request(
            "POST",f"/v1/voices/pvc/{voice_id}/captcha",
            files=files,timeout=300
        )
        return response.json()

    async def pvc_train(self, voice_id, model_id=None):
        payload={}
        if model_id:
            payload["model_id"]=model_id
        response=await self._request(
            "POST",f"/v1/voices/pvc/{voice_id}/train",
            json=payload,timeout=180
        )
        return response.json()

    async def pvc_status(self, voice_id):
        response=await self._request("GET",f"/v1/voices/{voice_id}",timeout=120)
        return response.json()

    async def realtime_token(self):
        response=await self._request("POST","/v1/single-use-token/realtime_scribe")
        return response.json()

    async def create_dubbing(self, upload=None, source_url=None, reference="", source_language=None, target_language=None, keyterms=None):
        data={"reference":reference[:500],"model_id":"dubbing_v2"}
        if source_language:
            data["source_language"]=source_language
        if target_language:
            data["target_language"]=target_language
        if keyterms:
            data['keyterms']=json.dumps(keyterms,ensure_ascii=False)
        files=None
        if upload is not None:
            await upload.seek(0)
            files={"file":(upload.filename,upload.file,upload.content_type or "application/octet-stream")}
        elif source_url:
            data["source_url"]=source_url
        else:
            raise ValueError("Видео/аудио файл эсвэл URL шаардлагатай.")
        response=await self._request("POST","/v1/dubbing/project",files=files,data=data,timeout=360)
        result=response.json()
        if isinstance(result,dict):
            result["_provider_usage"]=self._meta(response)
        return result

    async def get_dubbing_project(self, project_id):
        response=await self._request("GET",f"/v1/dubbing/project/{project_id}")
        return response.json()

    async def list_dubbing_languages(self, project_id):
        response=await self._request("GET",f"/v1/dubbing/project/{project_id}/language",params={"page_size":20})
        return response.json()

    async def create_dubbing_language(self, project_id, target_language):
        response=await self._request(
            "POST",f"/v1/dubbing/project/{project_id}/language",
            json={"target_language":target_language}
        )
        return response.json()

    async def download_url(self, url):
        async with httpx.AsyncClient(timeout=httpx.Timeout(300,connect=20),follow_redirects=True) as client:
            response=await client.get(url)
        response.raise_for_status()
        return response.content, response.headers.get("content-type","application/octet-stream")

    async def subscription(self):
        response=await self._request("GET","/v1/user/subscription")
        return response.json()

    async def usage(self, start_ms, end_ms, interval_seconds=86400):
        payload={
            "start_time":int(start_ms),
            "end_time":int(end_ms),
            "interval_seconds":int(interval_seconds),
            "time_zone":"Asia/Ulaanbaatar",
            "group_by":["product_type"],
        }
        response=await self._request(
            "POST","/v1/workspace/analytics/query/usage-by-product-over-time",
            json=payload
        )
        return response.json()
