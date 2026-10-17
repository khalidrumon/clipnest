import asyncio
import json
import ipaddress
import os
import re
import secrets
import shutil
import socket
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import yt_dlp

ROOT = Path(__file__).resolve().parent
TEMP = ROOT / 'downloads'
TEMP.mkdir(exist_ok=True)
app = FastAPI(title='ClipNest Downloader', docs_url=None, redoc_url=None)
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
MAX_ACTIVE = asyncio.Semaphore(2)
JOBS = {}
RATE = {}
X_CACHE = {}
X_RE = re.compile(r"^/(?:[^/]+/status|i/web/status)/(\d+)(?:/.*)?$")
HOSTS = (
    'youtube.com', 'youtu.be', 'youtube-nocookie.com', 'facebook.com', 'fb.watch',
    'instagram.com', 'tiktok.com', 'twitter.com', 'x.com', 'reddit.com', 'redd.it',
    'vimeo.com', 'dailymotion.com', 'linkedin.com', 'snapchat.com', 'pinterest.com',
    'pin.it', 'twitch.tv', 'clips.twitch.tv', 'streamable.com', 'threads.net',
    'dai.ly', 'archive.org', 'vkvideo.ru', 'vk.ru', 'ok.ru', 'rutube.ru',
    'odysee.com', 'kick.com', 'bitchute.com', 'ted.com', '9gag.com',
    'imgur.com', 'giphy.com', 'nicovideo.jp', 'niconico.jp', 'peertube.tv',
    'soundcloud.com', 'bilibili.com', 'tumblr.com', 'rumble.com', 'vk.com',
)

class UrlBody(BaseModel):
    url: str = Field(max_length=2048)

class DownloadBody(UrlBody):
    format_id: str = Field(default='best', max_length=120)
    audio: bool = False


def allowed(url):
    try:
        p = urlparse(url)
        if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None, 443):
            return False
        host = p.hostname.lower().rstrip('.')
        if not any(host == h or host.endswith('.' + h) for h in HOSTS):
            return False
        # DNS rebinding safeguard: only publicly routable IPs may be used.
        for result in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
            if not ipaddress.ip_address(result[4][0]).is_global:
                return False
        return True
    except (ValueError, OSError):
        return False


def base_opts():
    return {
        'quiet': True, 'no_warnings': True, 'noplaylist': True,
        'skip_download': True, 'socket_timeout': 15, 'retries': 2,
        'extractor_retries': 2, 'ignoreerrors': False,
        'cachedir': False, 'playlist_items': '1',
    }


def info_for(url):
    with yt_dlp.YoutubeDL(base_opts()) as ydl:
        info = ydl.extract_info(url, download=False)
        if not info:
            raise ValueError('No downloadable media found at this link.')
        if info.get('_type') in ('playlist', 'multi_video'):
            entries = info.get('entries') or []
            info = next((i for i in entries if i), None)
        if not info:
            raise ValueError('No downloadable media found.')
        return info


def formats_for(info):
    formats = info.get('formats') or []
    heights = {}
    for f in formats:
        if f.get('vcodec') == 'none' or not f.get('height'):
            continue
        height = int(f['height'])
        if height < 144:
            continue
        # Prefer source qualities with separate streams or combined audio; yt-dlp can merge.
        heights[height] = {'id': f'height:{height}', 'label': f'{height}p', 'height': height}
    return [heights[h] for h in sorted(heights, reverse=True)][:12]


def is_x(url):
    host = (urlparse(url).hostname or '').lower()
    return host in ('x.com', 'www.x.com', 'twitter.com', 'www.twitter.com', 'mobile.twitter.com')


def fx_data(url):
    path = urlparse(url).path
    match = X_RE.match(path)
    if not match:
        raise ValueError('Not a supported X post link.')
    status_id = match.group(1)
    # The user handle is not required for FxTwitter's status lookup.
    api_url = 'https://api.fxtwitter.com' + (path.split('/video/')[0] if not path.startswith('/i/web/status/') else f'/i/status/{status_id}')
    with httpx.Client(timeout=12, follow_redirects=False, headers={'User-Agent': 'ClipNest/1.1'}) as client:
        r = client.get(api_url)
        r.raise_for_status()
        data = r.json()
    if data.get('code') != 200:
        raise ValueError('Alternative X metadata service could not retrieve the post.')
    tweet = data.get('tweet') or {}
    vids = ((tweet.get('media') or {}).get('videos') or [])
    if not vids:
        raise ValueError('Alternative X metadata found no videos.')
    video = vids[0]
    variants = []
    seen = set()
    for f in (video.get('formats') or video.get('variants') or []):
        mp4 = f.get('url', '')
        if f.get('container') != 'mp4' and f.get('content_type') != 'video/mp4':
            continue
        parsed = urlparse(mp4)
        if parsed.scheme != 'https' or parsed.hostname != 'video.twimg.com' or not parsed.path.endswith('.mp4'):
            continue
        size = re.search(r'/(\d{2,4})x(\d{2,4})/', parsed.path)
        if not size:
            continue
        width, height = map(int, size.groups())
        if (width, height) in seen:
            continue
        seen.add((width, height))
        variants.append({'id': f'x:{width}x{height}', 'label': f'{width} × {height}', 'height': height, 'url': mp4})
    variants.sort(key=lambda x: x['height'], reverse=True)
    if not variants:
        raise ValueError('No direct MP4 video formats were returned.')
    token = secrets.token_urlsafe(24)
    now = time.time()
    for key, entry in list(X_CACHE.items()):
        if now - entry['created'] > 1800:
            X_CACHE.pop(key, None)
    X_CACHE[token] = {'created': now, 'variants': variants, 'source': url}
    preview = next((v for v in variants if v['height'] >= 540 and v['height'] <= 540), None) or min(variants, key=lambda v: abs(v['height'] - 540))
    return {
        'title': (tweet.get('text') or 'X video')[:180],
        'uploader': ((tweet.get('author') or {}).get('name') or '')[:100],
        'thumbnail': video.get('thumbnail_url') or '',
        'duration': video.get('duration'), 'extractor': 'X / FxTwitter',
        'formats': [{k:v[k] for k in ('id','label','height')} for v in variants],
        'original_url': url, 'direct_token': token,
        'preview_url': preview['url'], 'preview_label': preview['label'],
    }


@app.get('/api/x/open/{token}/{format_id}')
async def x_open_direct(token: str, format_id: str, request: Request):
    """Redirect browser straight to X CDN, avoiding server-side proxy limits."""
    client_limit(request)
    entry = X_CACHE.get(token)
    if not entry or time.time() - entry['created'] > 1800:
        raise HTTPException(404, 'Video session expired. Analyze the link again.')
    chosen = next((v for v in entry['variants'] if v['id'] == format_id), None)
    if not chosen:
        raise HTTPException(404, 'Quality unavailable.')
    media_url = chosen['url']
    parsed = urlparse(media_url)
    if parsed.scheme != 'https' or parsed.hostname != 'video.twimg.com' or not parsed.path.endswith('.mp4'):
        raise HTTPException(400, 'Unsupported media location.')
    return RedirectResponse(url=media_url, status_code=307, headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})


@app.get('/api/x/video/{token}/{format_id}')
async def x_video(token: str, format_id: str, request: Request, download: int = 0):
    # Legacy endpoint: always use the validated direct CDN redirect rather than proxying.
    return await x_open_direct(token, format_id, request)


def err(e):
    msg = str(e).replace('\n', ' ').strip()
    return re.sub(r'(?i)(cookie|authorization|token|password)\s*[:=]\s*\S+', r'\1=[redacted]', msg)[:280]


def client_limit(req):
    key = req.client.host if req.client else 'unknown'
    now = time.time()
    entries = [t for t in RATE.get(key, []) if now - t < 60]
    if len(entries) >= 15:
        raise HTTPException(429, 'Too many requests. Try again in a minute.')
    entries.append(now)
    RATE[key] = entries


@app.get('/')
def home():
    return FileResponse(ROOT / 'static' / 'index.html')


@app.post('/api/analyze')
async def analyze(body: UrlBody, request: Request):
    client_limit(request)
    if not await asyncio.to_thread(allowed, body.url):
        raise HTTPException(400, 'Enter a valid HTTPS link from a supported video website.')
    try:
        if is_x(body.url):
            try:
                return await asyncio.wait_for(asyncio.to_thread(fx_data, body.url), timeout=16)
            except Exception:
                pass  # Fall back to yt-dlp if the public metadata service fails.
        async with MAX_ACTIVE:
            info = await asyncio.wait_for(asyncio.to_thread(info_for, body.url), timeout=65)
        return {
            'title': (info.get('title') or 'Untitled video')[:180],
            'uploader': (info.get('uploader') or info.get('channel') or '')[:100],
            'thumbnail': info.get('thumbnail') or '',
            'duration': info.get('duration'), 'extractor': info.get('extractor_key') or 'Video',
            'formats': formats_for(info), 'original_url': body.url,
        }
    except asyncio.TimeoutError:
        raise HTTPException(504, 'The source took too long to respond.')
    except Exception as e:
        raise HTTPException(422, 'Could not analyze this link: ' + err(e))


def do_download(job, url, fmt, audio):
    work = Path(tempfile.mkdtemp(prefix='clip_', dir=TEMP))
    try:
        def hook(data):
            if data['status'] == 'downloading':
                job['status'] = 'downloading'
                total = data.get('total_bytes') or data.get('total_bytes_estimate') or 0
                if total:
                    job['progress'] = min(99, round(data.get('downloaded_bytes', 0) * 100 / total))
            elif data['status'] == 'finished':
                job['status'] = 'processing'
                job['progress'] = 99
        options = base_opts()
        options.update({
            'skip_download': False,
            'outtmpl': str(work / '%(title).110B [%(id)s].%(ext)s'),
            'progress_hooks': [hook], 'merge_output_format': 'mp4',
            'postprocessors': ([{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}] if audio else []),
            'format': 'bestaudio/best' if audio else ('bestvideo*+bestaudio/best' if fmt == 'best' else f'bestvideo[height<={int(fmt.split(":")[1])}]+bestaudio/best[height<={int(fmt.split(":")[1])}]'),
        })
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])
        files = sorted((p for p in work.iterdir() if p.is_file() and p.suffix.lower() in ('.mp4', '.mkv', '.webm', '.mp3', '.m4a')), key=lambda p: p.stat().st_size, reverse=True)
        if not files:
            raise ValueError('No completed video file was created.')
        job['file'] = str(files[0]); job['name'] = files[0].name
        job['status'] = 'ready'; job['progress'] = 100
    except Exception as e:
        job['status'] = 'error'; job['error'] = err(e)
        shutil.rmtree(work, ignore_errors=True)


@app.post('/api/download')
async def download(body: DownloadBody, request: Request):
    client_limit(request)
    if not await asyncio.to_thread(allowed, body.url):
        raise HTTPException(400, 'Invalid source URL.')
    if body.format_id != 'best' and not re.fullmatch(r'height:(\d{3,4})', body.format_id):
        raise HTTPException(400, 'Invalid quality.')
    if sum(1 for j in JOBS.values() if j['status'] in ('queued', 'downloading', 'processing')) >= 2:
        raise HTTPException(429, 'Server is busy. Retry shortly.')
    key = secrets.token_urlsafe(24)
    JOBS[key] = {'status': 'queued', 'progress': 0, 'file': None, 'name': None, 'created': time.time()}
    asyncio.create_task(asyncio.to_thread(do_download, JOBS[key], body.url, body.format_id, body.audio))
    return {'job_id': key}


@app.get('/api/status/{job_id}')
def status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, 'Download not found.')
    return {k: job.get(k) for k in ('status', 'progress', 'error', 'name')}


@app.get('/api/file/{job_id}')
def file(job_id: str):
    job = JOBS.get(job_id)
    if not job or job.get('status') != 'ready' or not job.get('file'):
        raise HTTPException(404, 'Download is not ready.')
    path = Path(job['file'])
    if not path.is_file():
        raise HTTPException(410, 'File has expired.')
    return FileResponse(path, filename=job['name'], media_type='application/octet-stream')


@app.get('/api/preview/{job_id}')
def preview(job_id: str):
    job = JOBS.get(job_id)
    if not job or job['status'] != 'ready' or not job.get('file'):
        raise HTTPException(404, 'Preview not ready.')
    path = Path(job['file'])
    if not path.exists() or path.suffix.lower() != '.mp4':
        raise HTTPException(404, 'Preview is available only for MP4 videos.')
    return FileResponse(path, media_type='video/mp4', headers={'Content-Disposition': 'inline'})


@app.on_event('startup')
async def cleanup_on_start():
    # For production, run a periodic cleanup worker / shared object storage.
    for p in TEMP.glob('clip_*'):
        if p.is_dir() and time.time() - p.stat().st_mtime > 86400:
            shutil.rmtree(p, ignore_errors=True)
