# YouTube → TikTok Clip Pipeline

An automated pipeline that turns a YouTube channel's videos into ready-to-post vertical clips for TikTok, YouTube Shorts, and Reels — no subscription services, no manual editing.

Built and operated by **Big Dad The Chairman** (Minneapolis, MN) for his own type-beat channel. It runs hands-free on a home Windows PC: a scheduled task wakes it every 6 hours, it processes the next batch of videos, and finished clips land in a folder with captions, ready to post.

## What it does

1. **Lists the channel's videos** with `yt-dlp` — newest uploads first, then works through the back catalog.
2. **Skips anything already processed** using a state file (`channel_state.json`), so a video is never clipped twice.
3. **Downloads at 1080p** — quality over speed, on purpose.
4. **Cuts the listed moments** from each video and uses `ffmpeg` to render vertical **1080×1920** clips with a blurred-background fill, so horizontal footage fills a phone screen instead of sitting in black bars.
5. **Writes a caption file per clip** and appends every clip to `posting_queue.csv`, producing batches of 9 ready-to-post clips at a time.

## Results so far

- Multiple production batches of **9 clips each**, cut, captioned, and queued automatically.
- The first batches were posted/scheduled to TikTok from the queue.
- Runs unattended on a 6-hour schedule via Windows Task Scheduler (`run_clips.bat`).

## Project structure

| File | Purpose |
| --- | --- |
| `channel_pipeline.py` | The main pipeline: list → dedupe → download → cut → caption → queue. |
| `poster.py` | Optional TikTok Direct Post client (OAuth with PKCE) that logs in and posts queued clips through TikTok's official API. |
| `run_clips.bat` | Windows launcher used by the scheduled task. |
| `tiktok_config_template.json` | Template for the poster's local config — copy to `tiktok_config.json` and fill in your own TikTok developer app keys. |
| `requirements.txt` | Python dependencies. |

## Setup

**Requirements:** Python 3.10+, `ffmpeg` on your PATH, and the packages in `requirements.txt`.

```bash
pip install -r requirements.txt
```

1. Point `CHANNEL_URL` in `channel_pipeline.py` at your channel.
2. List the moments you want clipped for each video (start/end times in the script's clip map).
3. Preview a batch (downloads nothing):

```bash
python channel_pipeline.py
```

4. Run it for real, or schedule `run_clips.bat` with Windows Task Scheduler for hands-free batches.

**Posting (optional):** `poster.py` uses TikTok's Content Posting API. It requires your own registered TikTok developer app (free, but the app goes through TikTok's review) — copy `tiktok_config_template.json` to `tiktok_config.json` and add your app's client key and secret. **Never commit that file**; it's already in `.gitignore`.

## Design choices

- **1080p sources over faster 720p downloads** — clip quality is the product.
- **Batches of 3 videos per run** — steady output instead of one giant dump.
- **State-file dedupe** — safe to run on a schedule without re-processing.
- **Own tooling over SaaS** — built instead of renting a clipping subscription.

## Roadmap

- [ ] Activate `poster.py` end-to-end once the TikTok developer app clears review.
- [ ] Hook-text overlay in the first 2 seconds of each clip.
- [ ] Posting support for YouTube Shorts and Instagram Reels.

## Tech

Python · ffmpeg · yt-dlp · Windows Task Scheduler · TikTok Content Posting API (OAuth 2.0 + PKCE)
