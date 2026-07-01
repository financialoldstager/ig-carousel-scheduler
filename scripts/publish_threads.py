"""發一則純文字貼文到 Threads（官方 API，兩步：建容器 → 發佈）。

移植自 ig-carousel-daily skill 的 post_threads.py，改成 token 走環境變數優先
（GitHub Actions Secrets）、退回本機 ~/.env.claude-tools。Threads 無原生排程，
由 GitHub Actions cron 到點呼叫此腳本代發。

Token：THREADS_USER_ID、THREADS_ACCESS_TOKEN。文字上限 500 字（超過先在 skill 端切接龍）。

用法：
  python3 publish_threads.py --check
  python3 publish_threads.py --file threads.txt
  python3 publish_threads.py --file threads.txt --dry    # 只建容器、不發佈
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://graph.threads.net/v1.0"
ENV_PATH = Path("~/.env.claude-tools").expanduser()
TEXT_LIMIT = 500

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()


def read_secret(name: str) -> str:
    v = os.environ.get(name)
    if v:
        return v.strip()
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def api_get(path: str, params: dict) -> dict:
    url = f"{BASE}/{path}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30, context=_SSL_CTX) as resp:
        return json.loads(resp.read().decode())


def api_post(path: str, params: dict) -> dict:
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"{BASE}/{path}", data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--text")
    ap.add_argument("--file")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    user_id = read_secret("THREADS_USER_ID")
    token = read_secret("THREADS_ACCESS_TOKEN")
    if not user_id or not token:
        print("[ERR] 缺 THREADS_USER_ID / THREADS_ACCESS_TOKEN", file=sys.stderr)
        return 1

    if args.check:
        me = api_get("me", {"fields": "id,username", "access_token": token})
        print(json.dumps(me, ensure_ascii=False, indent=2))
        return 0 if me.get("id") else 1

    text = args.text
    if args.file:
        text = Path(args.file).expanduser().read_text()
    if not text or not text.strip():
        print("[ERR] 沒有文字內容", file=sys.stderr)
        return 2
    text = text.strip()
    if len(text) > TEXT_LIMIT:
        print(f"[ERR] {len(text)} 字超過 Threads {TEXT_LIMIT} 字上限", file=sys.stderr)
        return 2

    container = api_post(f"{user_id}/threads", {
        "media_type": "TEXT",
        "text": text,
        "access_token": token,
    })
    creation_id = container.get("id")
    if not creation_id:
        print(f"[ERR] 建容器失敗：{container}", file=sys.stderr)
        return 1

    if args.dry:
        print(f"[DRY] 停在發佈前。creation_id={creation_id}")
        print(json.dumps({"dry": True, "creation_id": creation_id}, ensure_ascii=False))
        return 0

    time.sleep(5)
    published = api_post(f"{user_id}/threads_publish", {
        "creation_id": creation_id,
        "access_token": token,
    })
    post_id = published.get("id")
    if not post_id:
        print(f"[ERR] 發佈失敗：{published}", file=sys.stderr)
        return 1

    info = api_get(post_id, {"fields": "id,permalink", "access_token": token})
    permalink = info.get("permalink", "(取不到 permalink)")
    print(f"已發佈 Threads：{permalink}")
    print(json.dumps({"post_id": post_id, "permalink": permalink}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
