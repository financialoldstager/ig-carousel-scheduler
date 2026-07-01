# ig-carousel-scheduler — 設定與運作

理財老司機每日 IG carousel 的**伺服器端排程發佈器**。固定每天 **20:30 MYT** 把已拍板的內容
發到 IG＋Threads（FB 走平台原生排程，不在這裡）。跑在 GitHub Actions 上，**不依賴老蕭的 Mac 開機**。

## 這個 repo 一次當三件事
1. **雲端 cron**：`.github/workflows/publish.yml`（cron `30 12 * * *` = 20:30 MYT）呼叫 `run_publish.py` 代按 IG／Threads 發佈。
2. **公開圖床**：GitHub Pages 服務 `staging/<date>/*.jpg`，供 Meta 抓圖（IG 發佈要公開影像 URL）。
3. **manifest 佇列**：`queue/<date>.json` 是每天要發什麼的事實來源。

## 分工
- **FB**：`ig-carousel-daily` skill 在「落地」時就用 Graph API 原生排程（`published=false` + `scheduled_publish_time=20:30`）送出；Meta 伺服器端到點自發，**不經此 repo 的 cron**。
- **IG＋Threads**：無原生排程 → 由此 repo 的 cron 到點代發。

## manifest schema（`queue/<YYYY-MM-DD>.json`）
```json
{
  "date": "2026-07-01",
  "scheduled_myt": "2026-07-01T20:30:00+08:00",
  "card_path": "003 Card/xxx.md",
  "card_title": "卡片完整標題",
  "images": [
    "https://financialoldstager.github.io/ig-carousel-scheduler/staging/2026-07-01/1.jpg",
    "https://financialoldstager.github.io/ig-carousel-scheduler/staging/2026-07-01/2.jpg"
  ],
  "ig_caption": "IG 完整 caption（含 hashtag）",
  "threads_text": "【卡片標題】\n…（≤500 字）",
  "fb": {"scheduled_via": "native", "post_id": "...", "status": "scheduled"},
  "ig":      {"status": "pending"},
  "threads": {"status": "pending"}
}
```
cron 跑完會把 `ig`／`threads` 的 `status` 改成 `published`（附 permalink）或 `failed`，再 commit 回來（冪等：已 published 不重發）。

## GitHub Actions Secrets（Settings → Secrets and variables → Actions）
| Secret | 說明 | 續期 |
|---|---|---|
| `IG_ACCESS_TOKEN` | Instagram Business token（IGAA…，graph.instagram.com） | token-keeper 每週推 |
| `IG_BUSINESS_ACCOUNT_ID` | IG 帳號 id | 靜態 |
| `THREADS_ACCESS_TOKEN` | Threads token | token-keeper 每週推 |
| `THREADS_USER_ID` | Threads user id | 靜態 |
| `TELEGRAM_BOT_TOKEN` | 複用既有 bot | 靜態 |
| `TELEGRAM_ALLOWED_CHAT_ID` | 老蕭 chat id | 靜態 |

**token 續期**：`~/dashboard/scripts/refresh_meta_tokens.py`（launchd 每週一 10:00）刷新後，用
`gh secret set` 把最新 IG／Threads token 推進本 repo 的 Actions Secrets。需一枚 GitHub PAT（secrets 寫入權）存 `~/.env.claude-tools` 的 `GH_SCHEDULER_PAT`。

## GitHub Pages
Settings → Pages → Source: `Deploy from a branch` → `main` / root。
圖片 URL 形如 `https://financialoldstager.github.io/ig-carousel-scheduler/staging/<date>/<n>.jpg`。

## 手動測試
- Actions 頁 → `Publish IG + Threads at 8:30PM MYT` → `Run workflow` → 勾 `dry`：只建容器、驗圖抓得到、輪詢 FINISHED，**不真發**。
- 本機：`python3 scripts/publish_ig.py --check` / `publish_threads.py --check`（讀 `~/.env.claude-tools`）。

## 上線／回滾
- 停用：Actions → 關閉 workflow，或刪 `queue/<date>.json`。
- FB 排程可在發佈前用 Graph API 取消（skill 落地時記了 post_id）。
- 整條可還原：skill 改動 git rollback、repo 可刪。
