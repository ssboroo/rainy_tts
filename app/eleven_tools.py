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
        return response.json()

    async def delete_voice(self, voice_id):
        response=await self._request("DELETE",f"/v1/voices/{voice_id}")
        return response.json()

    async def get_voice(self, voice_id):
        response=await self._request("GET",f"/v1/voices/{voice_id}")
        return response.json()

    async def dialogue(self, inputs, language_code="mn"):
        payload={"inputs":inputs,"model_id":"eleven_v3","language_code":language_code or None}
        response=await self._request(
            "POST","/v1/text-to-dialogue",
            params={"output_format":"mp3_44100_128"},
            json=payload,timeout=240
        )
        return response.content

    async def music(self, prompt, length_ms):
        payload={"prompt":prompt,"music_length_ms":int(length_ms)}
        response=await self._request(
            "POST","/v1/music",
            params={"output_format":"mp3_44100_128"},
            json=payload,timeout=360
        )
        return response.content

    async def sound_effect(self, text):
        response=await self._request(
            "POST","/v1/sound-generation",
            params={"output_format":"mp3_44100_128"},
            json={"text":text},timeout=180
        )
        return response.content

    async def speech_to_text(self, upload, language_code=None):
        await upload.seek(0)
        files={"file":(upload.filename,upload.file,upload.content_type or "application/octet-stream")}
        data={"model_id":"scribe_v2","diarize":"true","tag_audio_events":"true"}
        if language_code:
            data["language_code"]=language_code
        response=await self._request("POST","/v1/speech-to-text",files=files,data=data,timeout=360)
        return response.json()

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
        return response.content

    async def realtime_token(self):
        response=await self._request("POST","/v1/single-use-token/realtime_scribe")
        return response.json()

    async def create_dubbing(self, upload=None, source_url=None, reference="", source_language=None, target_language=None):
        data={"reference":reference[:500],"model_id":"dubbing_v2"}
        if source_language:
            data["source_language"]=source_language
        if target_language:
            data["target_language"]=target_language
        files=None
        if upload is not None:
            await upload.seek(0)
            files={"file":(upload.filename,upload.file,upload.content_type or "application/octet-stream")}
        elif source_url:
            data["source_url"]=source_url
        else:
            raise ValueError("Видео/аудио файл эсвэл URL шаардлагатай.")
        response=await self._request("POST","/v1/dubbing/project",files=files,data=data,timeout=360)
        return response.json()

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
