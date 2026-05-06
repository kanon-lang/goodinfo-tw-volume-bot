# goodinfo-tw-volume-bot

這是一個最小可執行的 Python 小專案，用來從 Goodinfo 抓取台股成交量前 10 大個股，並排除 ETF、ETN、權證與特別股後輸出原始 JSON。

## 專案用途

- 從 Goodinfo 抓取成交張數熱門排行
- 排除 ETF / ETN / 權證 / 特別股等非一般個股
- 輸出 `output/goodinfo_top_volume.json`
- 保留給未來 OpenClaw 直接讀取 raw JSON 使用

## 本機執行方式

```bash
python -m pip install -r requirements.txt
python scripts/fetch_goodinfo_top_volume.py
```

成功後會輸出：

- `output/goodinfo_top_volume.json`

失敗時會輸出：

- `output/goodinfo_top_volume_error.txt`

## GitHub Actions 手動執行方式

1. 進入 GitHub repo 的 `Actions`
2. 選擇 `Fetch Goodinfo Top Volume`
3. 點 `Run workflow`
4. 執行完成後可下載 artifact 或直接查看 repo 內更新的 JSON

排程時間：

- 台灣時間週一到週五 15:10
- GitHub Actions cron: `10 7 * * 1-5`

## OpenClaw 未來讀取 raw JSON 的方式

未來 OpenClaw 只需要讀取這份 raw JSON：

- `output/goodinfo_top_volume.json`

之後可再由其他流程轉成 Markdown、PDF 或 Discord 報告，但本 repo 目前不處理分析、不接 OpenAI、不接 Discord。

## Raw JSON URL 範例

```text
https://raw.githubusercontent.com/<你的GitHub帳號>/goodinfo-tw-volume-bot/main/output/goodinfo_top_volume.json
```
