"""發一則 IG carousel（多圖）到 Instagram Business 帳號。

官方 Instagram Content Publishing API（graph.instagram.com，IGAA token）。
IG 沒有原生排程 —— 這支腳本就是「到點代按發佈」的那隻手，由 GitHub Actions cron 呼叫。

流程（carousel）：
  1. 每張圖：POST /{ig_user}/media  image_url=<公開URL> is_carousel_item=true → 子容器 id
  2. 輪詢每個子容器 status_code 直到 FINISHED
  3. POST /{ig_user}/media  media_type=CAROUSEL children=<ids> caption=<caption> → carousel 容器 id
  4. 輪詢 carousel 容器 FINISHED
  5. POST /{ig_user}/media_publish  creation_id=<carousel 容器 id> → 已發佈 id
  6. GET /{id}?fields=permalink

Token 來源優先序：環境變數（GitHub Actions Secrets）→ 本機 ~/.env.claude-tools（本機測試用）。
  IG_ACCESS_TOKEN、IG_BUSINESS_ACCOUNT_ID

用法：
  python3 publish_ig.py --check                       # 只驗證 token、印帳號
  python3 publish_ig.py --images url1 url2 ... --caption-file cap.txt          # 真發
  python3 publish_ig.py --images url1 url2 ... --caption-file cap.txt --dry    # 乾跑：建容器＋驗圖抓得到＋輪詢 FINISHED，但不 media_publish
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

BASE = os.environ.get("IG_GRAPH_BASE", "https://graph.instagram.com/v21.0")
ENV_PATH = Path("~/.env.claude-tools").expanduser()

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()


def read_secret(name: str) -> str:
    """環境變數優先（雲端），退回本機 env 檔（本機測試）。"""
    v = os.environ.get(name)
    if v:
        return v.strip()
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _read(resp) -> dict:
    return json.loads(resp.read().decode())


def api_get(path: str, params: dict) -> dict:
    url = f"{BASE}/{path}?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=60, context=_SSL_CTX) as resp:
            return _read(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"GET {path} → HTTP {e.code}: {body}") from None


def api_post(path: str, params: dict) -> dict:
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"{BASE}/{path}", data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60, context=_SSL_CTX) as resp:
            return _read(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"POST {path} → HTTP {e.code}: {body}") from None


def poll_finished(container_id: str, token: str, label: str, timeout_s: int = 180) -> None:
    """輪詢容器直到 FINISHED；ERROR 或逾時就丟例外。"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        st = api_get(container_id, {"fields": "status_code,status", "access_token": token})
        code = st.get("status_code")
        if code == "FINISHED":
            return
        if code == "ERROR":
            raise RuntimeError(f"{label} 容器處理失敗：{st}")
        time.sleep(5)
    raise TimeoutError(f"{label} 容器 {timeout_s}s 內未 FINISHED")


def check_image_public(url: str) -> None:
    """先確認圖是公開、可抓、是影像 mime —— Meta 抓不到圖是最常見的失敗。"""
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as resp:
            ct = resp.headers.get("Content-Type", "")
            if not ct.startswith("image/"):
                raise RuntimeError(f"圖 URL 回的不是影像（Content-Type={ct}）：{url}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"圖 URL 抓不到（HTTP {e.code}）：{url}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--images", nargs="*", default=[])
    ap.add_argument("--caption")
    ap.add_argument("--caption-file")
    ap.add_argument("--dry", action="store_true", help="建容器＋驗圖＋輪詢 FINISHED，但不 media_publish")
    args = ap.parse_args()

    token = read_secret("IG_ACCESS_TOKEN")
    if not token:
        print("[ERR] 缺 IG_ACCESS_TOKEN", file=sys.stderr)
        return 1

    # graph.instagram.com（Instagram Login / IGAA token）內容發佈的節點是 GET /me 的 **user_id** 欄位
    # （這裡＝17841…，等同 IG_BUSINESS_ACCOUNT_ID），而**不是** `id` 欄位（26563…），也不能用字面 "me"。
    # 實測：node=user_id → /media（含 is_carousel_item）與 media_publish 都成功；node=id → 400 subcode 33。
    me = api_get("me", {"fields": "id,user_id,username", "access_token": token})
    ig_user = me.get("user_id")
    if not ig_user:
        print(f"[ERR] 無法解析 IG user_id：{me}", file=sys.stderr)
        return 1

    if args.check:
        print(json.dumps(me, ensure_ascii=False, indent=2))
        return 0

    images = args.images
    if len(images) < 2:
        print(f"[ERR] carousel 至少 2 張圖，收到 {len(images)}", file=sys.stderr)
        return 2
    if len(images) > 10:
        print(f"[ERR] IG carousel 最多 10 張，收到 {len(images)}", file=sys.stderr)
        return 2

    caption = args.caption or ""
    if args.caption_file:
        caption = Path(args.caption_file).expanduser().read_text().strip()

    # 0) 先驗每張圖公開可抓
    for u in images:
        check_image_public(u)
    print(f"[ok] {len(images)} 張圖皆公開可抓")

    # 1) 逐張建子容器
    child_ids = []
    for i, u in enumerate(images, 1):
        c = api_post(f"{ig_user}/media", {
            "image_url": u,
            "is_carousel_item": "true",
            "access_token": token,
        })
        cid = c.get("id")
        if not cid:
            print(f"[ERR] 第 {i} 張子容器建立失敗：{c}", file=sys.stderr)
            return 1
        child_ids.append(cid)
        print(f"[ok] 子容器 {i}/{len(images)} = {cid}")

    # 2) 輪詢子容器 FINISHED
    for i, cid in enumerate(child_ids, 1):
        poll_finished(cid, token, f"子容器{i}")
    print("[ok] 所有子容器 FINISHED")

    # 3) 建 carousel 容器
    carousel = api_post(f"{ig_user}/media", {
        "media_type": "CAROUSEL",
        "children": ",".join(child_ids),
        "caption": caption,
        "access_token": token,
    })
    carousel_id = carousel.get("id")
    if not carousel_id:
        print(f"[ERR] carousel 容器建立失敗：{carousel}", file=sys.stderr)
        return 1
    poll_finished(carousel_id, token, "carousel")
    print(f"[ok] carousel 容器 = {carousel_id} FINISHED")

    if args.dry:
        print(f"[DRY] 停在發佈前。carousel_id={carousel_id}，若真發會 media_publish 這個。")
        print(json.dumps({"dry": True, "carousel_id": carousel_id, "children": child_ids}, ensure_ascii=False))
        return 0

    # 5) 發佈
    pub = api_post(f"{ig_user}/media_publish", {"creation_id": carousel_id, "access_token": token})
    post_id = pub.get("id")
    if not post_id:
        print(f"[ERR] media_publish 失敗：{pub}", file=sys.stderr)
        return 1

    info = api_get(post_id, {"fields": "permalink", "access_token": token})
    permalink = info.get("permalink", "(取不到 permalink)")
    print(f"已發佈 IG：{permalink}")
    print(json.dumps({"post_id": post_id, "permalink": permalink}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
