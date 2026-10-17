# ClipNest — KRDigi Team

Modern light/dark themed website with FxTwitter MP4 fallback, yt-dlp and FFmpeg.

## Test locally

```bat
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
```

Open http://127.0.0.1:8000.

## Deploy to Render

Upload the **contents** of this folder to the root of a GitHub repository. Create a Render Blueprint from render.yaml or a Docker Web Service on the free plan. Test the assigned onrender.com URL before adding a custom domain. Follow Render's DNS instructions for download.krdigi.com; do not change your existing main-site DNS records.

## Large X videos

X MP4s are opened directly from X's CDN, so the former 350MB local proxy limit does not apply. On the browser player menu, use Download / Save video as. Some browsers or CDN servers may limit saving, and direct URLs can expire.

## Notes

Other platforms continue to use yt-dlp and may consume server disk, CPU, and bandwidth. This is a testing build, **not hardened for a public high-traffic downloader**. Add download size/time limits, queued-job expiration and stronger rate limiting, and respect media rights and platform terms before public launch. Free Render services have limited resources and may go to sleep. Never advertise guaranteed coverage of private or DRM-protected video.
