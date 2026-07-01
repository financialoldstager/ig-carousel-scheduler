"""雲端 cron 的入口：讀當天 manifest → 發 IG carousel ＋ Threads → 更新狀態 → 推 Telegram。

由 .github/workflows/publish.yml 在 20:30 MYT（12:30 UTC）觸發。
FB 不在這裡——FB 在「落地」時就用平台原生排程送出，Meta 伺服器端到點自發。

manifest：queue/<YYYY-MM-DD>.json（schema 見 docs/SETUP.md）。
冪等：ig/threads 狀態已是 published 就跳過，避免重跑重發。

用法：
  python3 run_publish.py                 # 跑今天（MYT）的 manifest
  python3 run_publish.py --date 2026-07-01
  python3 run_publish.py --dry           # 乾跑（子腳本只建容器不發佈）
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent.parent
QUEUE = REPO / "queue"
SCRIPTS = REPO / "scripts"
MYT = ZoneInfo("Asia/Kuala_Lumpur")

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()


def telegram(msg: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "").strip()
    if not token or not chat:
        print("[warn] 無 Telegram 設定，跳過通知")
        return
    try:
        data = urllib.parse.urlencode({"chat_id": chat, "text": msg, "disable_web_page_preview": "true"}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data, method="POST")
        urllib.request.urlopen(req, timeout=30, context=_SSL_CTX).read()
    except Exception as e:
        print(f"[warn] Telegram 通知失敗：{e}")


def run_script(name: str, extra_args: list[str]) -> tuple[int, str]:
    """跑子腳本，回 (returncode, 最後一行 stdout)。"""
    cmd = [sys.executable, str(SCRIPTS / name), *extra_args]
    p = subprocess.run(cmd, capture_output=True, text=True)
    out = (p.stdout or "").strip()
    if p.stdout:
        print(p.stdout)
    if p.stderr:
        print(p.stderr, file=sys.stderr)
    last = out.splitlines()[-1] if out else ""
    return p.returncode, last


def parse_json_tail(line: str) -> dict:
    try:
        return json.loads(line)
    except Exception:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD（預設今天 MYT）")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    date = args.date or datetime.now(MYT).strftime("%Y-%m-%d")
    mpath = QUEUE / f"{date}.json"
    if not mpath.exists():
        print(f"[info] 今天（{date}）沒有 manifest，無事可做。")
        return 0

    m = json.loads(mpath.read_text())
    tag = "[DRY] " if args.dry else ""
    results = []

    # ---- IG carousel ----
    ig = m.get("ig", {})
    if ig.get("status") == "published":
        print("[skip] IG 已發佈過")
    else:
        images = m.get("images", [])
        cap_file = REPO / "queue" / f".{date}.ig_caption.txt"
        cap_file.write_text(m.get("ig_caption", ""))
        ig_args = ["--images", *images, "--caption-file", str(cap_file)]
        if args.dry:
            ig_args.append("--dry")
        rc, last = run_script("publish_ig.py", ig_args)
        cap_file.unlink(missing_ok=True)
        info = parse_json_tail(last)
        if rc == 0 and not args.dry:
            m["ig"] = {"status": "published", "permalink": info.get("permalink", ""), "post_id": info.get("post_id", "")}
            results.append(f"✅ IG：{info.get('permalink','(ok)')}")
        elif rc == 0 and args.dry:
            results.append(f"✅ IG dry ok（carousel_id={info.get('carousel_id','?')}）")
        else:
            m.setdefault("ig", {})["status"] = "failed"
            results.append("❌ IG 發佈失敗（看 log）")

    # ---- Threads ----
    th = m.get("threads", {})
    if th.get("status") == "published":
        print("[skip] Threads 已發佈過")
    else:
        th_file = REPO / "queue" / f".{date}.threads.txt"
        th_file.write_text(m.get("threads_text", ""))
        th_args = ["--file", str(th_file)]
        if args.dry:
            th_args.append("--dry")
        rc, last = run_script("publish_threads.py", th_args)
        th_file.unlink(missing_ok=True)
        info = parse_json_tail(last)
        if rc == 0 and not args.dry:
            m["threads"] = {"status": "published", "permalink": info.get("permalink", ""), "post_id": info.get("post_id", "")}
            results.append(f"✅ Threads：{info.get('permalink','(ok)')}")
        elif rc == 0 and args.dry:
            results.append("✅ Threads dry ok")
        else:
            m.setdefault("threads", {})["status"] = "failed"
            results.append("❌ Threads 發佈失敗（看 log）")

    if not args.dry:
        mpath.write_text(json.dumps(m, ensure_ascii=False, indent=2))

    title = m.get("card_title") or m.get("card_path", date)
    telegram(f"{tag}IG carousel 排程發佈 {date}\n「{title}」\n" + "\n".join(results) +
             "\n（FB 走平台原生排程，另計）")
    print("\n".join(results))
    # 任一真發失敗回非 0，讓 workflow 標紅
    return 1 if any(r.startswith("❌") for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
