# Comiket（コミックマーケット）社團報名監控腳本

自動偵測官方網站，第一時間通知社團報名資訊：

- 📅 **日程公告偵測**：偵測 `C{N}Schedule.html` 首次出現（活動日程已公告、報名日期尚未公開）
- 🎉 **報名開始偵測**：偵測 `C{N}Appset.html` 首次出現（社團報名受付開始！含日期）

---

## 快速開始

```bash
pip install -r requirements.txt
set COMIKET_DISCORD_WEBHOOK=https://discord.com/api/webhooks/你的Webhook
python monitor.py
```

成功後到工作排程器設定每天 9:00 執行 `run.bat`，即可完成設定。  
詳細步驟與 Discord Webhook 取得方式見下方說明。

---

## 監控策略

Comiket 有明確的資訊公開週期，採兩段式 URL 狀態偵測：

| 狀態 | 觸發條件 | 說明 |
|------|---------|------|
| `pending` | Schedule / Appset 頁皆無回應（HTTP 404） | 尚未公告 |
| `schedule` | `C{N}Schedule.html` 首次出現 HTTP 200 | 活動日程已公告 |
| `appset` | `C{N}Appset.html` 首次出現 HTTP 200 | 報名受付開始 |

每次執行時**優先檢查 Appset 頁**，若已開放則略過 Schedule 頁直接進入 appset 狀態。

---

## 通知說明

| 情況 | Discord 收到 |
|------|-------------|
| `pending` → `schedule`（日程公告） | 📅 藍色通知（非靜音） |
| `pending` 或 `schedule` → `appset`（報名開始） | 🎉 紫色大通知（非靜音） |
| 主頁解析失敗（可能格式變更） | ⚠️ 紅色警告（非靜音） |
| 每週一腳本執行 | 📋 灰色靜音確認 |
| 首次執行偵測到屆次 | 靜默記錄，不發通知 |

每週靜音確認依狀態分四個區塊：
- **報名進行中**（截止日未到）
- **報名截止・活動待舉辦**（截止日已過但活動未舉辦）
- **日程已公告**（schedule 狀態）
- **尚未公告**（pending 狀態）

---

## 檔案結構

```
02_Comiket_Search/
├── monitor.py        ← 主程式
├── run.bat           ← Windows 排程用啟動檔
├── requirements.txt  ← 套件清單
├── README.md         ← 本說明
├── state.json        ← 自動產生，記錄上次狀態（git 忽略）
└── logs/             ← 自動產生，存放執行紀錄（git 忽略）
    └── monitor.log
```

---

## 步驟 1：安裝套件

```
pip install -r requirements.txt
```

---

## 步驟 2：取得 Discord Webhook URL

1. 打開想接收通知的 Discord **頻道**
2. 點頻道名稱右邊的齒輪（編輯頻道）
3. 左側選「整合」→「Webhook」→「新增 Webhook」
4. 取個名字（例如「Comiket 報名小助手」），複製 Webhook URL
5. URL 格式：`https://discord.com/api/webhooks/123456789/xxxxxxxxxx`

---

## 步驟 3：設定環境變數

**方法 A：永久生效（推薦）**

在 PowerShell 執行：

```powershell
[System.Environment]::SetEnvironmentVariable(
  'COMIKET_DISCORD_WEBHOOK',
  '你的 Webhook URL',
  'User'
)
```

設定後需重新開啟 cmd / PowerShell 才會生效。

**方法 B：臨時測試**

```
set COMIKET_DISCORD_WEBHOOK=https://discord.com/api/webhooks/你的網址
python monitor.py
```

---

## 步驟 4：手動測試

```
python monitor.py
```

成功的話：
- 終端機顯示解析到的屆次資訊（如 `發現屆次：['C108', 'C109']`）
- Discord 頻道收到「📋 每週確認：腳本運作中」靜音訊息

---

## 步驟 5：設定 Windows 工作排程器（每天自動執行）

1. 搜尋「工作排程器」並開啟
2. 右側點「建立基本工作」
3. 名稱：`Comiket 報名監控`
4. 觸發程序：「每天」，建議設定早上 9:00
5. 動作：「啟動程式」
6. 程式/指令碼：`run.bat` 的完整路徑
7. 起始位置：`run.bat` 所在資料夾路徑
8. 完成後右鍵該工作 → 「執行」做一次測試

---

## 進階設定

**不想收到每週確認訊息**

在 `monitor.py` 末尾將以下兩行加上 `#` 註解掉：

```python
# if datetime.today().weekday() == 0:
#     send_discord_heartbeat(current)
```

**顯示已結束屆次**

在 `monitor.py` 頂端將：

```python
SHOW_ENDED = False
```

改為：

```python
SHOW_ENDED = True
```

---

## 注意事項

- 排程執行時電腦須開著（或在工作排程器中勾選「喚醒電腦以執行此工作」）
- 執行紀錄存在 `logs/monitor.log`，可用記事本查看
- `state.json` 存放上次偵測到的狀態，刪除後下次執行會重新建立（不會重複發通知）
- 資料來源：[コミックマーケット公式サイト](https://www.comiket.co.jp/)
