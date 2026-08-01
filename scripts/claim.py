#!/usr/bin/env python3
"""睡醒後重新判斷今天還要發什麼，並在 manifest 寫入「發佈鎖」。

為什麼需要這支（2026-08-01 重複發文事故）：
workflow 原本在「睡到 20:30 之前」就算好 todo，兩條 cron（主引信 + 備援）
各自在自己開跑那一刻讀 manifest，都看到「還沒發」，睡醒後就都發了一次，
IG 與 Threads 各出現兩則重複貼文。

修法：把判斷移到睡醒之後，且改成 git 層級的 compare-and-swap——
本腳本只負責「重讀 manifest → 算 pending → 寫鎖」，由 workflow 接著
`git push`；因為推之前已 `reset --hard origin/main`，推得成功代表期間
沒有別的 run 搶先，推被拒代表輸掉競賽、該 run 就不發。

輸出：stdout 印一行 `ig,threads` / `ig` / `threads` / `none`（給 workflow 讀）。
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

QUEUE = Path(__file__).resolve().parent.parent / "queue"
MYT = timezone(timedelta(hours=8))
STALE_AFTER = timedelta(minutes=60)  # 鎖過期時間：持鎖的 run 掛了才允許接手
TARGETS = ("ig", "threads")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="YYYY-MM-DD（MYT）")
    ap.add_argument("--run-id", required=True, help="GitHub Actions run id")
    ap.add_argument("--force", action="store_true",
                    help="手動觸發用：無視他人的鎖（已 published 的仍不重發）")
    args = ap.parse_args()

    mpath = QUEUE / f"{args.date}.json"
    if not mpath.exists():
        print("none")
        return 0

    m = json.loads(mpath.read_text(encoding="utf-8"))

    # 已經發出去的一律不再發，force 也不例外——這是防重複貼文的最後一道底線。
    pending = [k for k in TARGETS if (m.get(k) or {}).get("status") != "published"]
    if not pending:
        print("none", file=sys.stdout)
        print("[claim] IG/Threads 都已 published，無事可做。", file=sys.stderr)
        return 0

    lock = m.get("lock") or {}
    owner = lock.get("run_id")
    if owner and owner != args.run_id and not args.force:
        claimed_at = lock.get("claimed_at", "")
        stale = False
        try:
            stale = datetime.now(MYT) - datetime.fromisoformat(claimed_at) > STALE_AFTER
        except ValueError:
            pass
        if not stale:
            print("none", file=sys.stdout)
            print(f"[claim] 鎖已被 run {owner} 持有（{claimed_at}），本 run 讓路。",
                  file=sys.stderr)
            return 0
        print(f"[claim] run {owner} 的鎖已逾時（{claimed_at}），接手。", file=sys.stderr)

    m["lock"] = {
        "run_id": args.run_id,
        "claimed_at": datetime.now(MYT).isoformat(timespec="seconds"),
        "targets": pending,
    }
    mpath.write_text(json.dumps(m, ensure_ascii=False, indent=1) + "\n",
                     encoding="utf-8")
    print(",".join(pending), file=sys.stdout)
    print(f"[claim] run {args.run_id} 寫入鎖，待發：{pending}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
