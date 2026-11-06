"""
Big Dad The Chairman — TikTok Poster (own-app route)

Publishes clips from posting_queue.csv to TikTok through the official
Content Posting API (Direct Post), using YOUR OWN TikTok developer app.

ONE-TIME SETUP (after your app is registered at developers.tiktok.com)
  1. Create tiktok_config.json next to this script:
       {
         "client_key": "PASTE_FROM_DEV_PORTAL",
         "client_secret": "PASTE_FROM_DEV_PORTAL",
         "redirect_uri": "http://localhost:8765/callback"
       }
     The secret lives ONLY in that file on your PC. Never paste it in chat.
  2. Run:  python poster.py login
     A browser opens; you approve the app on your own TikTok account.
     The token is saved to tiktok_token.json (also only on your PC).

DAILY USE
  Preview the queue:   python poster.py
  Post the queue:      python poster.py post
  For each post the tool shows your account, the clip and its caption, and
  asks YOU to pick the privacy level from the options TikTok returns —
  no default, per TikTok's posting rules. It then uploads, waits for
  TikTok to confirm, and marks the row POSTED in posting_queue.csv.

UNTIL YOUR APP PASSES TIKTOK'S AUDIT
  TikTok restricts posts from unaudited apps to private (SELF_ONLY), and
  your TikTok account must itself be set to private for test posts.
  That is expected behavior, not a bug. Public posting unlocks with the
  audit. Rate limits: roughly 15 posts per account per day.

No third-party libraries: Python standard library only.
"""

import base64
import csv
import hashlib
import json
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).parent
CONFIG_FILE = HERE / "tiktok_config.json"
TOKEN_FILE = HERE / "tiktok_token.json"
QUEUE_FILE = HERE / "posting_queue.csv"
CLIPS_DIR = HERE / "channel_clips"
API = "https://open.tiktokapis.com/v2"
SCOPES = "user.info.basic,video.publish"


# ------------------------------ http helpers -------------------------------

def http_json(method: str, url: str, token: str = None, body: dict = None,
              form: dict = None) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"error": {"code": f"http_{e.code}", "message": str(e)}}


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        print("Missing tiktok_config.json — see the setup steps at the top "
              "of poster.py. The client key/secret come from your app page "
              "at developers.tiktok.com and stay on this PC only.")
        sys.exit(1)
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def load_token() -> dict:
    if not TOKEN_FILE.exists():
        print("Not logged in yet. Run:  python poster.py login")
        sys.exit(1)
    return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))


def save_token(tok: dict) -> None:
    tok["saved_at"] = int(time.time())
    TOKEN_FILE.write_text(json.dumps(tok, indent=2), encoding="utf-8")


def access_token(cfg: dict, tok: dict) -> str:
    """Return a fresh access token, refreshing if the saved one is old."""
    age = int(time.time()) - int(tok.get("saved_at", 0))
    if age < int(tok.get("expires_in", 86400)) - 600 and tok.get("access_token"):
        return tok["access_token"]
    resp = http_json("POST", f"{API}/oauth/token/", form={
        "client_key": cfg["client_key"],
        "client_secret": cfg["client_secret"],
        "grant_type": "refresh_token",
        "refresh_token": tok["refresh_token"],
    })
    if "access_token" not in resp:
        print(f"Token refresh failed: {resp}. Run:  python poster.py login")
        sys.exit(1)
    tok.update(resp)
    save_token(tok)
    return tok["access_token"]


# --------------------------------- login -----------------------------------

def do_login(cfg: dict) -> None:
    redirect = cfg.get("redirect_uri", "http://localhost:8765/callback")
    parsed = urllib.parse.urlparse(redirect)
    port = parsed.port or 8765
    state = str(int(time.time()))
    # TikTok requires PKCE: send a SHA-256 challenge now, prove the
    # matching verifier when exchanging the code.
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    auth_url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
        "client_key": cfg["client_key"],
        "scope": SCOPES,
        "response_type": "code",
        "redirect_uri": redirect,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in qs:
                result["code"] = qs["code"][0]
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Approved! You can close this tab and "
                                 b"return to PowerShell.")
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"No code returned. Try login again.")

        def log_message(self, *args):
            pass

    server = HTTPServer(("localhost", port), Handler)
    print("Opening TikTok in your browser — approve the app there.")
    print(f"If it does not open, paste this URL:\n{auth_url}\n")
    webbrowser.open(auth_url)
    while "code" not in result:
        server.handle_request()
    server.server_close()
    resp = http_json("POST", f"{API}/oauth/token/", form={
        "client_key": cfg["client_key"],
        "client_secret": cfg["client_secret"],
        "code": result["code"],
        "grant_type": "authorization_code",
        "redirect_uri": redirect,
        "code_verifier": verifier,
    })
    if "access_token" not in resp:
        print(f"Login failed: {resp}")
        sys.exit(1)
    save_token(resp)
    print("Logged in and token saved to tiktok_token.json (this PC only).")


# -------------------------------- posting ----------------------------------

def creator_info(token: str) -> dict:
    resp = http_json("POST", f"{API}/post/publish/creator_info/query/",
                     token=token, body={})
    if "data" not in resp:
        print(f"Could not read creator info: {resp}")
        sys.exit(1)
    return resp["data"]


def upload_and_post(token: str, video: Path, caption: str,
                    privacy: str) -> str:
    """Direct Post via FILE_UPLOAD. Returns the publish id."""
    size = video.stat().st_size
    chunk = size  # our clips are a few MB: single-chunk upload
    init = http_json("POST", f"{API}/post/publish/video/init/", token=token, body={
        "post_info": {
            "title": caption,
            "privacy_level": privacy,
            "disable_duet": False,
            "disable_stitch": False,
            "disable_comment": False,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": size,
            "chunk_size": chunk,
            "total_chunk_count": 1,
        },
    })
    data = init.get("data") or {}
    if "publish_id" not in data:
        raise RuntimeError(f"init failed: {init}")
    req = urllib.request.Request(
        data["upload_url"], data=video.read_bytes(), method="PUT",
        headers={"Content-Type": "video/mp4",
                 "Content-Range": f"bytes 0-{size - 1}/{size}"})
    with urllib.request.urlopen(req) as resp:
        if resp.status not in (200, 201, 206):
            raise RuntimeError(f"upload HTTP {resp.status}")
    return data["publish_id"]


def wait_status(token: str, publish_id: str, timeout: int = 300) -> str:
    start = time.time()
    while time.time() - start < timeout:
        resp = http_json("POST", f"{API}/post/publish/status/fetch/",
                         token=token, body={"publish_id": publish_id})
        status = (resp.get("data") or {}).get("status", "UNKNOWN")
        if status in ("PUBLISH_COMPLETE", "FAILED"):
            return status
        time.sleep(10)
    return "TIMEOUT"


def read_queue() -> list:
    if not QUEUE_FILE.exists():
        return []
    with QUEUE_FILE.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_queue(rows: list) -> None:
    with QUEUE_FILE.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["clip_file", "caption", "status"])
        w.writeheader()
        w.writerows(rows)


def do_post(cfg: dict, dry_run: bool) -> None:
    rows = read_queue()
    ready = [r for r in rows if r.get("status") == "READY"]
    if not ready:
        print("Queue is empty — no READY clips in posting_queue.csv.")
        return
    tok = load_token()
    token = access_token(cfg, tok)
    info = creator_info(token)
    print(f"Account: @{info.get('creator_username')} "
          f"({info.get('creator_nickname')})")
    options = info.get("privacy_level_options") or ["SELF_ONLY"]
    for row in ready:
        clip = CLIPS_DIR / row["clip_file"]
        print(f"\nClip: {row['clip_file']}")
        print(f"Caption: {row['caption']}")
        if not clip.exists():
            print("  File missing — skipping.")
            continue
        if dry_run:
            print("  (preview only)")
            continue
        print("Choose who can watch this (TikTok requires your pick):")
        for i, opt in enumerate(options, 1):
            print(f"  {i}. {opt}")
        while True:
            pick = input("Number: ").strip()
            if pick.isdigit() and 1 <= int(pick) <= len(options):
                privacy = options[int(pick) - 1]
                break
            print("  Pick one of the listed numbers.")
        publish_id = upload_and_post(token, clip, row["caption"], privacy)
        status = wait_status(token, publish_id)
        print(f"  Result: {status}")
        if status == "PUBLISH_COMPLETE":
            row["status"] = "POSTED"
            write_queue(rows)


def main() -> None:
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "preview"
    if mode == "login":
        do_login(load_config())
    elif mode == "post":
        do_post(load_config(), dry_run=False)
    else:
        rows = read_queue()
        ready = [r for r in rows if r.get("status") == "READY"]
        print(f"{len(ready)} clip(s) READY in posting_queue.csv:")
        for r in ready:
            print(f"  {r['clip_file']} — {r['caption'][:70]}...")
        print("\nRun  python poster.py post  to publish them.")


if __name__ == "__main__":
    main()
