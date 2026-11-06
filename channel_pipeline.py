"""
Big Dad The Chairman — Channel Pipeline (v2 companion)
Pulls from your YouTube channel, newest uploads first, then works through
the back catalog in small batches. Own it outright: no subscriptions.

WHAT IT DOES
  1. Lists your channel's videos with yt-dlp (newest first).
  2. Checks channel_state.json so a video is never processed twice.
  3. Takes the next BATCH_LIMIT unprocessed videos (default 3 per run).
  4. Downloads each one, finds its highest-energy moments, and cuts
     vertical 1080x1920 clips (same engine as auto_pipeline.py).
  5. Clips land in channel_clips/, named from the video's title and ID.
  Run it again tomorrow and it picks up where it left off — new uploads
  first, then deeper into the backlog.

SETUP (one time)
  - ffmpeg on PATH (same as auto_pipeline.py).
  - yt-dlp installed:   pip install yt-dlp
  - This file sits in the SAME folder as auto_pipeline.py — it reuses
    that script's energy-finder and clip cutter instead of duplicating them.

RUN IT
  Preview the next batch (downloads nothing):  python channel_pipeline.py
  Process the next batch:                      python channel_pipeline.py make

POSTING
  Same as the inbox pipeline: output is ready-to-post vertical MP4s.
  TikTok gates fully automatic posting behind its developer approval,
  so posting stays a two-tap job in the TikTok app.
"""

import csv
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import auto_pipeline as ap  # reuse the energy finder + vertical clip cutter

# ----------------------------- YOUR SETTINGS -----------------------------
CHANNEL_URL = "https://www.youtube.com/@bigdadthechairmanofficial"
BATCH_LIMIT = 3            # videos processed per run
LIST_LIMIT = 100           # how far back the channel listing scans per run
CLIP_SECONDS = 30          # length of each clip
CLIPS_PER_VIDEO = 3        # moments cut per video
MIN_GAP_SECONDS = 45       # winning moments must be at least this far apart
KEEP_DOWNLOADS = False     # True = keep full videos after clipping (uses disk)
# --------------------------------------------------------------------------

HERE = Path(__file__).parent
STATE_FILE = HERE / "channel_state.json"
DOWNLOAD_DIR = HERE / "channel_downloads"
OUT_DIR = HERE / "channel_clips"

# auto_pipeline reads its settings from module globals at call time,
# so point them at this script's settings and output folder.
ap.CLIP_SECONDS = CLIP_SECONDS
ap.CLIPS_PER_VIDEO = CLIPS_PER_VIDEO
ap.MIN_GAP_SECONDS = MIN_GAP_SECONDS
ap.OUT_DIR = OUT_DIR


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)


def yt_dlp_cmd() -> list:
    """Call yt-dlp through this Python, so it works even when the yt-dlp
    command itself is not on PATH (common with Microsoft Store Python)."""
    return [sys.executable, "-m", "yt_dlp"]


# ------------------------------- state -----------------------------------

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log("WARNING: state file was unreadable; starting fresh.")
    return {"processed": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ------------------------------ listing ----------------------------------

def list_channel(limit: int = LIST_LIMIT) -> list:
    """Return [{'id','title','url'}] newest first, via yt-dlp flat playlist."""
    if importlib.util.find_spec("yt_dlp") is None:
        print("yt-dlp not found. Install it first:  python -m pip install yt-dlp")
        sys.exit(1)
    videos_url = CHANNEL_URL.rstrip("/") + "/videos"
    result = subprocess.run(
        yt_dlp_cmd() + ["--flat-playlist", "--dump-single-json",
                        "--playlist-end", str(limit), videos_url],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("yt-dlp could not list the channel. Its error was:")
        print(result.stderr.strip()[-800:])
        sys.exit(1)
    data = json.loads(result.stdout)
    entries = []
    for e in data.get("entries") or []:
        vid = e.get("id")
        if not vid:
            continue
        entries.append({
            "id": vid,
            "title": e.get("title") or vid,
            "url": e.get("url") or f"https://www.youtube.com/watch?v={vid}",
        })
    return entries


def select_batch(entries: list, state: dict, limit: int = BATCH_LIMIT) -> list:
    """Next unprocessed entries, in listing order (newest first)."""
    done = state.get("processed", {})
    return [e for e in entries if e["id"] not in done][:limit]


# ----------------------------- processing --------------------------------

def safe_name(entry: dict) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", entry["title"]).strip("_")[:40]
    return f"{slug}_{entry['id']}" if slug else entry["id"]


def download_video(entry: dict) -> Path:
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    target_stem = DOWNLOAD_DIR / entry["id"]
    for existing in DOWNLOAD_DIR.glob(entry["id"] + ".*"):
        return existing  # already downloaded
    subprocess.run(
        yt_dlp_cmd() + ["-f", "bv[height<=1080][vcodec^=avc]+ba[acodec^=mp4a]"
                              "/bv[height<=1080]+ba/b[height<=1080]/b",
                        "--merge-output-format", "mp4",
                        "-o", str(target_stem) + ".%(ext)s", entry["url"]],
        check=True, capture_output=True,
    )
    matches = list(DOWNLOAD_DIR.glob(entry["id"] + ".*"))
    if not matches:
        raise FileNotFoundError(f"Download produced no file for {entry['id']}")
    return matches[0]


# ----------------------------- captions -----------------------------------

GENRE_TAGS = [
    ("g-funk", "#GFunk #WestCoastHipHop"),
    ("west coast", "#WestCoastHipHop #GFunk"),
    ("afrobeat", "#Afrobeat #Afrobeats"),
    ("cloud rap", "#CloudRap #UndergroundRap"),
    ("dark r&b", "#DarkRnB #RnBTypeBeat"),
    ("r&b", "#RnBTypeBeat #RnB"),
    ("boom bap", "#BoomBap #HipHopBeats"),
    ("trap", "#TrapBeats #TypeBeat"),
    ("drill", "#DrillBeats #TypeBeat"),
    ("soul", "#SoulSample #TypeBeat"),
]


def parse_title(title: str) -> tuple:
    """'Cafe Noir Slowjam - Dark R&B Type Beat | Big Dad...' -> (name, genre)."""
    clean = title.split("|")[0].strip().strip("‘’'\"")
    for sep in (" — ", " – ", " - "):
        if sep in clean:
            name, genre = clean.split(sep, 1)
            genre = re.sub(r"(?i)\s*type beat\s*$", "", genre).strip()
            return name.strip(), genre
    return clean, ""


def caption_for(name: str, genre: str, idx: int) -> str:
    tags = "#TypeBeat #Producer #BigDadTheChairman"
    g = genre.lower()
    for key, extra in GENRE_TAGS:
        if key in g:
            tags = f"{extra} #TypeBeat #Producer #BigDadTheChairman"
            break
    label = genre if genre else "new"
    if idx == 1:
        text = f"{name} — {label} type beat. Full beat on my YouTube."
    elif idx == 2:
        text = f"{name}, part 2 — the standout section. Full beat on YouTube."
    else:
        text = f"{name}, part {idx} — one more standout moment. Full beat on YouTube."
    return f"{text} {tags}"


def write_captions(entry: dict, made: list) -> None:
    """One .txt caption file per clip + rows in posting_queue.csv."""
    name, genre = parse_title(entry["title"])
    queue_file = HERE / "posting_queue.csv"
    new_file = not queue_file.exists()
    with queue_file.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["clip_file", "caption", "status"])
        for i, clip_name in enumerate(made, 1):
            cap = caption_for(name, genre, i)
            (OUT_DIR / (Path(clip_name).stem + ".txt")).write_text(
                cap, encoding="utf-8")
            w.writerow([clip_name, cap, "READY"])


def process_entry(entry: dict) -> list:
    """Download (if needed), find peaks, cut clips. Returns clip file names."""
    source = download_video(entry)
    energy = ap.audio_energy_per_second(source)
    starts = ap.pick_moments(energy)
    if not starts:
        return []
    OUT_DIR.mkdir(exist_ok=True)
    stem = safe_name(entry)
    made = []
    for i, start in enumerate(starts, 1):
        out = ap.make_clip(source, start, f"{stem}_clip{i}")
        made.append(out.name)
        log(f"MADE: {out.name} (at {start // 60}:{start % 60:02d})")
    if made:
        write_captions(entry, made)
    if not KEEP_DOWNLOADS:
        source.unlink(missing_ok=True)
    return made


# -------------------------------- main ------------------------------------

def cycle(do_make: bool, entries: list = None, batch_limit: int = BATCH_LIMIT) -> list:
    """One run. Returns the batch it previewed or processed.
    `entries` can be injected (used by offline tests); normally it lists YouTube."""
    state = load_state()
    if entries is None:
        entries = list_channel()
    batch = select_batch(entries, state, batch_limit)
    if not batch:
        log("Nothing new: everything in the scanned listing is already processed.")
        return []
    if not do_make:
        log(f"Next batch would be {len(batch)} video(s):")
        for e in batch:
            log(f"  WOULD PROCESS: {e['title']}  ({e['url']})")
        print()
        print("Preview only — nothing downloaded or cut. "
              "Run  python channel_pipeline.py make  to process this batch.")
        return batch
    for e in batch:
        log(f"PROCESSING: {e['title']}")
        try:
            clips = process_entry(e)
        except Exception as exc:
            log(f"ERROR on {e['id']}: {exc} — left unprocessed, will retry next run.")
            continue
        state["processed"][e["id"]] = {
            "title": e["title"],
            "processed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "clips": clips,
        }
        save_state(state)  # save after EACH video so a crash loses nothing
        log(f"DONE: {e['title']} -> {len(clips)} clip(s)")
    return batch


def main() -> None:
    if shutil.which("ffmpeg") is None:
        print("ffmpeg not found. Install it first:  winget install Gyan.FFmpeg")
        print("Then close and reopen your terminal and run this again.")
        return
    do_make = len(sys.argv) > 1 and sys.argv[1].lower() == "make"
    cycle(do_make)


if __name__ == "__main__":
    main()
