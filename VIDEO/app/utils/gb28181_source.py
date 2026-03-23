import os
from typing import Iterable, Optional, Tuple
from urllib.parse import urlparse

import requests


GB28181_SOURCE_PREFIX = 'gb28181://'


def is_gb28181_source(source: Optional[str]) -> bool:
    return bool(source and source.strip().lower().startswith(GB28181_SOURCE_PREFIX))


def parse_gb28181_source(source: Optional[str]) -> Optional[Tuple[str, str]]:
    if not is_gb28181_source(source):
        return None

    parsed = urlparse(source.strip())
    device_id = (parsed.netloc or '').strip()
    channel_id = (parsed.path or '').strip('/ ')
    if not device_id or not channel_id:
        return None
    return device_id, channel_id


def _candidate_bases() -> Iterable[str]:
    configured_base = (os.getenv('GB28181_SERVICE_URL') or '').strip().rstrip('/')
    if configured_base:
        yield configured_base

    gateway_url = (os.getenv('GATEWAY_URL') or '').strip().rstrip('/')
    if gateway_url:
        if gateway_url.endswith('/admin-api'):
            yield f'{gateway_url}/gb28181'
        else:
            yield f'{gateway_url}/admin-api/gb28181'

    yield 'http://localhost:48088/api'


def _build_play_url(base_url: str, device_id: str, channel_id: str) -> str:
    base = base_url.rstrip('/')
    if base.endswith('/api'):
        return f'{base}/play/start/{device_id}/{channel_id}'
    return f'{base}/play/start/{device_id}/{channel_id}'


def _extract_stream_url(payload: dict) -> Optional[str]:
    body = payload.get('data') if isinstance(payload.get('data'), dict) else payload
    candidates = [
        body.get('rtsp'),
        body.get('rtsps'),
        body.get('rtmp'),
        body.get('rtmps'),
        body.get('flv'),
        body.get('https_flv'),
        body.get('ws_flv'),
        body.get('fmp4'),
        body.get('hls'),
        body.get('rtc'),
        body.get('rtcs'),
    ]
    return next((url for url in candidates if isinstance(url, str) and url.strip()), None)


def resolve_gb28181_source(
    source: Optional[str],
    *,
    timeout: int = 15,
    logger=None,
) -> Optional[str]:
    parsed = parse_gb28181_source(source)
    if not parsed:
        return source

    device_id, channel_id = parsed
    headers = {}
    jwt_token = (os.getenv('JWT_TOKEN') or '').strip()
    if jwt_token:
        headers['X-Authorization'] = f'Bearer {jwt_token}'

    errors = []
    for base_url in _candidate_bases():
        play_url = _build_play_url(base_url, device_id, channel_id)
        try:
            response = requests.get(play_url, headers=headers, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            stream_url = _extract_stream_url(payload if isinstance(payload, dict) else {})
            if stream_url:
                if logger:
                    logger.info(
                        f'GB28181源解析成功: {device_id}/{channel_id} -> {stream_url} (via {base_url})'
                    )
                return stream_url
            errors.append(f'{base_url}: 未返回可播放流地址')
        except Exception as exc:
            errors.append(f'{base_url}: {exc}')

    if logger:
        logger.error(
            f'GB28181源解析失败: {device_id}/{channel_id}, errors={"; ".join(errors)}'
        )
    return None
