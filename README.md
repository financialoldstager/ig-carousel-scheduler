# ig-carousel-scheduler

理財老司機每日 IG carousel 的**伺服器端排程發佈器**——固定每天 **20:30 MYT** 把已拍板的內容
發到 Instagram ＋ Threads，跑在 GitHub Actions 上，**不依賴任何一台電腦開機**。

- Instagram / Threads 無原生排程 → 由此 repo 的 GitHub Actions cron（`30 12 * * *` = 20:30 MYT）代按發佈。
- Facebook 有原生排程 → 由 `ig-carousel-daily` skill 落地時直接排，不經此 repo。
- 圖片由本 repo 的 GitHub Pages 公開服務（Meta 抓圖用）。
- 內容由 `ig-carousel-daily` skill 在老蕭**人工拍板後**寫入 `queue/<date>.json`＋`staging/<date>/`。

完整說明見 [`docs/SETUP.md`](docs/SETUP.md)。上游計劃書：`Claude AI Agent/plans/2026-07-01-ig-carousel-排程發佈.md`。

⚠️ 本 repo 公開，但**憑證絕不進 repo**，只放 GitHub Actions Secrets。
