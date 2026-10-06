"""Validated v4 directions; charge exactly the text sent for each segment."""
from . import core

DIRECTIONS = {
    'neutral': '', 'happy': '[happy]', 'sad': '[sad]',
    'excited': '[excited]', 'angry': '[angry]',
    'whisper': '[whisper]', 'thoughtful': '[thoughtful]',
    'surprised': '[surprised]',
}

def segments(payload):
    direction = payload.get('emotion', 'neutral')
    if direction not in DIRECTIONS:
        raise ValueError('Сэтгэл хөдлөлийн сонголт буруу байна.')
    if direction != 'neutral' and payload.get('model_id') != 'eleven_v4':
        raise ValueError('Сэтгэл хөдлөлд Чанартай · Eleven v4 загварыг сонгоно уу.')
    texts = [c['text'] for c in payload['cues']] if payload.get('cues') else core.chunks(payload['text'])
    tag = DIRECTIONS[direction]
    return [(tag + ' ' + text) if tag else text for text in texts]

def uncertain_failure(exc):
    """Never refund an upstream call with an unknown billing outcome."""
    import httpx
    seen = set()
    while exc and id(exc) not in seen:
        seen.add(id(exc))
        status = getattr(exc, 'status_code', getattr(exc, 'status', 0)) or 0
        if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)) or status >= 500:
            return True
        exc = exc.__cause__
    return False
