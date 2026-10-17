# ClipNest — shareable video-downloader website

A responsive website + Python FastAPI backend, using `yt-dlp`. Paste a social-media URL, inspect its title/thumbnail and available resolutions, download video or audio, preview completed MP4 in the browser, and save the file via your browser.

## Run locally (Windows)

Install Python 3.11+ and FFmpeg, then open a terminal here:

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Open http://localhost:8000

## Deploy to a domain

The included Dockerfile is suitable for a Linux server or a container hosting provider that supports long-running services. Build/run:

```bash
docker build -t clipnest .
docker run -p 8000:8000 clipnest
```

Connect a domain through your hosting provider's HTTPS reverse proxy (e.g. Caddy or Nginx) to port 8000. HTTPS is recommended.

**Not suitable for static-only hosting** like GitHub Pages: video analysis/downloading runs on the server. Your server needs outbound internet, storage and FFmpeg. Downloads consume hosting bandwidth twice (source -> server -> visitor).

## Selecting a local folder

For a website, the visitor's **browser controls the destination**. Chrome/Brave/Edge: Settings → Downloads → turn on **Ask where to save each file before downloading**. A website cannot directly choose `G:\DOWN` on the visitor's computer.

## Supported sites

Supported URL hosts include YouTube, Facebook, Instagram, TikTok, X/Twitter, LinkedIn, Reddit, Snapchat, Pinterest, Dailymotion (`dailymotion.com`, `dai.ly`), Internet Archive (`archive.org`), VK (`vk.com`, `vk.ru`, `vkvideo.ru`), Odnoklassniki (`ok.ru`), Vimeo, Twitch, Rumble, Rutube, Odysee, Bilibili, Tumblr, Streamable, Kick, BitChute, TED, 9GAG, Imgur, Giphy, Niconico, PeerTube.tv, and others in the backend allowlist.

Includes allowlisted mainstream platforms; actual support is controlled by the installed `yt-dlp` version and platform access restrictions. DRM media, some private groups, login-only posts and changing website APIs may not work. No guarantee of success for any particular URL.

## Before launching publicly

This is a functional **starter**, not a production-hardened hosted download service. Add user accounts or stronger abuse protections, egress/network restrictions, job expiration and file cleanup, durable jobs and storage, bandwidth limits, capacity controls, access logs, HTTPS, abuse reporting and legal review. In particular, yt-dlp can be induced to fetch URLs exposed by extractors and redirects; use network-level outbound filtering and isolate the downloader on a restricted host. Rate limiting here is a simple per-process demo and is not sufficient for public high-traffic exposure. Files persist on disk until removed manually/at restart if older than a day. Public APIs may be rate-limited or blocked by social platforms.

Only download content you have the rights or permission to download; follow each platform's rules.

## What changed in this expanded version

Added mainstream and video-library sites to the domain allowlist and visible platform chips. These changes permit ClipNest to attempt extraction using yt-dlp; they do **not** implement new extraction engines or guarantee successful downloads. The archive.org allowlist covers hosted item pages where yt-dlp can extract a playable media file. Subscription, paywalled, private and DRM-protected content is not supported.

## X video improvement (v1.1)
For X/Twitter links, ClipNest now tries the public FxTwitter metadata API first, then falls back to yt-dlp if unavailable. If MP4 streams are returned, it displays exact resolutions, a lighter-weight ~540p browser preview, an Open MP4 link, and a server-assisted MP4 Save link (350 MB limit). The alternative API is a third-party service and can become unavailable without warning. Downloads are temporarily proxied through the server and therefore consume hosting bandwidth. The preview's playback time depends on X CDN buffering; no instant-start guarantee. The rest of the platforms keep their previous yt-dlp behavior.

If the X preview is blocked by the browser, use Open MP4. Each direct link is only active for 30 minutes; analyze again if it expires. Only download media you are authorized to save.


## v1.2: Large X MP4 fix

For X videos, **Open to Save** and **Play MP4** now redirect directly to a validated `video.twimg.com` HTTPS MP4 URL. They do not use the 350 MB server-side proxy, so files larger than 350 MB can be opened in the browser if the X CDN serves them. To save, use the browser video player's Download action or right-click **Save video as**. Browser restrictions mean this is not an automatic forced download and the media CDN may refuse access or take time to buffer. The previous `/api/x/video/` streaming endpoint remains for compatibility and still enforces its 350 MB limit. Re-analyze posts after 30 minutes.
