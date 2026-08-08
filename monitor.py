"""
コミックマーケット サークル申込監控腳本
自動偵測各屆 Comiket 的申込受付頁面是否公開，並發送 Discord 通知
"""

import re
import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime, date
from pathlib import Path

# ── 設定 ──────────────────────────────────────────────
DISCORD_WEBHOOK_URL = os.environ.get("COMIKET_DISCORD_WEBHOOK", "")

MAIN_URL = "https://www.comiket.co.jp/"
SCHEDULE_URL = "https://www.comiket.co.jp/info-a/{cno}/{cno}Schedule.html"
APPSET_URL   = "https://www.comiket.co.jp/info-c/{cno}/{cno}Appset.html"

STATE_FILE = Path(__file__).parent / "state.json"

SHOW_ENDED = False  # 改為 True 可顯示已結束屆次

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
# ──────────────────────────────────────────────────────

FULLWIDTH_TABLE = str.maketrans("０１２３４５６７８９", "0123456789")
WEEKDAYS_ZH = ["一", "二", "三", "四", "五", "六", "日"]
JP_WD = {"月": "一", "火": "二", "水": "三", "木": "四", "金": "五", "土": "六", "日": "日"}


def _jp_wd_to_zh(s: str) -> str:
    """將括號內的日文星期轉換為中文，如（火）→（二）。不影響日期中的月/日文字。"""
    return re.sub(r'（([月火水木金土日])）', lambda m: f'（{JP_WD[m.group(1)]}）', s)


def fetch_url(url: str) -> tuple[int, str]:
    """GET 請求，回傳 (status_code, html)。失敗回傳 (0, '')。"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        # comiket.co.jp 全站使用 ISO-2022-JP，用 content 直接解碼最可靠
        encoding = (resp.apparent_encoding or "iso-2022-jp").lower()
        try:
            html = resp.content.decode(encoding, errors="replace")
        except LookupError:
            html = resp.content.decode("utf-8", errors="replace")
        return resp.status_code, html
    except Exception as e:
        print(f"[錯誤] 無法抓取 {url}：{e}")
        return 0, ""


def get_upcoming_comikets(html: str) -> dict:
    """
    解析主頁，提取目前公告的屆次與活動日期。
    回傳 {
        "C108": {"event_date": "8/15～8/16", "event_year": 2026,
                 "event_month": 8, "event_end_day": 16},
        ...
    }
    主頁若解析不到任何屆次則回傳空 dict。
    """
    # 先用 BeautifulSoup 去除 HTML tag，再轉換全形數字
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="").translate(FULLWIDTH_TABLE)

    # コミックマーケット108は、東京ビッグサイトにて2026年8月15日〜16日開催
    # 波浪號可能是 ～ 或 〜
    pattern = re.compile(
        r'コミックマーケット(\d+)は[^。\n]*?(\d{4})年(\d{1,2})月(\d{1,2})日[～〜](\d{1,2})日'
    )
    results = {}
    for m in pattern.finditer(text):
        cno_num   = int(m.group(1))
        year      = int(m.group(2))
        month     = int(m.group(3))
        start_day = int(m.group(4))
        end_day   = int(m.group(5))
        cno = f"C{cno_num}"
        start_wd = WEEKDAYS_ZH[date(year, month, start_day).weekday()]
        end_wd   = WEEKDAYS_ZH[date(year, month, end_day).weekday()]
        results[cno] = {
            "event_date":    f"{month}/{start_day}（{start_wd}）～{month}/{end_day}（{end_wd}）",
            "event_year":    year,
            "event_month":   month,
            "event_end_day": end_day,
        }
    return results


def parse_schedule_info(html: str) -> str:
    """
    從 Schedule 頁提取申込公開予定月份。
    找不到則回傳空字串。
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")

    # 找「サークル申込」附近的 YYYY年M月 或 YYYY年M月頃
    for line in text.splitlines():
        if "サークル申込" in line or "申込受付" in line:
            m = re.search(r'(\d{4})年(\d{1,2})月', line)
            if m:
                return f"{m.group(1)}年{m.group(2)}月頃（予定）"
    # 備用：掃全文找最近一個 YYYY年M月 + 予定
    m = re.search(r'(\d{4})年(\d{1,2})月[^\n]*?予定', text)
    if m:
        return f"{m.group(1)}年{m.group(2)}月頃（予定）"
    return ""


def _clean_date_str(s: str) -> str:
    """去除全形空格與括號內的備注說明（如「以後の新規申込はできません」）。"""
    s = s.replace('\u3000', '')                          # 全形空格
    s = re.sub(r'（[^）]{0,30}(?:申込|できません)[^）]*）', '', s)  # 多餘說明括號
    return s.strip()


def parse_appset_dates(html: str) -> dict:
    """
    從 Appset 頁提取申込開始日與締切日。
    回傳 {"reg_start": "...", "reg_end": "..."}
    頁面使用全形數字，先轉換為半形再解析。
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n").translate(FULLWIDTH_TABLE)

    reg_start = "—"
    reg_end   = "—"

    for line in text.splitlines():
        line = line.strip()
        # 申込受付開始行
        if "申込受付開始" in line and reg_start == "—":
            m = re.search(r'(\d{4}年\s*\d{1,2}月\s*\d{1,2}日[^\n]{0,30})', line)
            if m:
                reg_start = _clean_date_str(m.group(1))
        # 決済締切（オンライン申込の実質締切）
        if "決済締切" in line and reg_end == "—":
            m = re.search(r'(\d{4}年\s*\d{1,2}月\s*\d{1,2}日[^\n]{0,30})', line)
            if m:
                reg_end = _clean_date_str(m.group(1))

    # fallback：找「締切」行
    if reg_end == "—":
        for line in text.splitlines():
            if "締切" in line:
                m = re.search(r'(\d{4}年\s*\d{1,2}月\s*\d{1,2}日[^\n]{0,30})', line)
                if m:
                    reg_end = _clean_date_str(m.group(1))
                    break

    return {"reg_start": _jp_wd_to_zh(reg_start), "reg_end": _jp_wd_to_zh(reg_end)}


def is_ended(event_year: int, event_month: int, event_end_day: int) -> bool:
    """判斷活動是否已結束（最後一天已過）。"""
    try:
        last_day = date(event_year, event_month, event_end_day)
        return last_day < date.today()
    except Exception:
        return False


def is_reg_ended(reg_end_str: str) -> bool:
    """判斷申込締切日是否已過。"""
    m = re.search(r'(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日', reg_end_str)
    if m:
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return d < date.today()
        except Exception:
            pass
    return False


def is_reg_started(reg_start_str: str) -> bool:
    """判斷申込受付開始日是否已到（尚未到則回傳 False，代表日期已公告但還沒開放）。"""
    m = re.search(r'(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日', reg_start_str)
    if m:
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return d <= date.today()
        except Exception:
            pass
    return False


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict):
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def send_discord_schedule(cno: str, event_date: str, tentative_date: str):
    """📅 日程公告通知（schedule 階段）"""
    if not DISCORD_WEBHOOK_URL:
        return
    now_str = datetime.now().strftime("%Y/%m/%d %H:%M")
    payload = {
        "username": "Comiket 報名小助手",
        "avatar_url": "https://www.comiket.co.jp/top/img/logo.gif",
        "embeds": [{
            "title": f"📅 Comiket · {cno} 日程公告",
            "description": (
                f"**{cno}** 的活動日程已公告，社團報名日期尚未公開。\n\n"
                f"🗓️ **活動日期**：{event_date}\n"
                f"📋 **報名公告預定**：{tentative_date or '未定'}\n\n"
                f"[➡️ 前往官網確認]({MAIN_URL})"
            ),
            "color": 0x5B9BD5,
            "footer": {"text": f"偵測時間：{now_str}"},
        }],
    }
    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
    if resp.status_code in (200, 204):
        print(f"[OK] 日程通知已發送：{cno}")
    else:
        print(f"[錯誤] 日程通知失敗：{resp.status_code} {resp.text}")


def send_discord_appset(cno: str, event_date: str, reg_start: str, reg_end: str):
    """🎉/📅 報名日期通知（appset 階段）。依受付開始日是否已到選擇不同標題文字。"""
    if not DISCORD_WEBHOOK_URL:
        return
    now_str = datetime.now().strftime("%Y/%m/%d %H:%M")
    appset_url = APPSET_URL.format(cno=cno)

    if is_reg_started(reg_start):
        title = f"🎉 Comiket · {cno} 報名開始！"
        lead  = f"**{cno}** 的社團報名已開始，快去確認！"
        color = 0x7F77DD
    else:
        # 日期已公告，但受付開始日尚未到——避免文字誤導成「已經可以報名」
        title = f"📅 Comiket · {cno} 報名日期公告！"
        lead  = f"**{cno}** 的社團報名日期已公告，尚未開放受理，記得屆時再送出申込！"
        color = 0x5B9BD5

    payload = {
        "username": "Comiket 報名小助手",
        "avatar_url": "https://www.comiket.co.jp/top/img/logo.gif",
        "embeds": [{
            "title": title,
            "description": (
                f"{lead}\n\n"
                f"🗓️ **活動日期**：{event_date}\n"
                f"📅 **報名開始**：{reg_start}\n"
                f"⏰ **報名截止**：{reg_end}\n\n"
                f"[➡️ 前往報名頁面]({appset_url})\n"
                f"[🌐 前往官網確認]({MAIN_URL})"
            ),
            "color": color,
            "footer": {"text": f"偵測時間：{now_str}"},
        }],
    }
    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
    if resp.status_code in (200, 204):
        print(f"[OK] 申込通知已發送：{cno}")
    else:
        print(f"[錯誤] 申込通知失敗：{resp.status_code} {resp.text}")


def send_discord_warning(msg: str):
    """⚠️ 格式異常警告"""
    if not DISCORD_WEBHOOK_URL:
        return
    now_str = datetime.now().strftime("%Y/%m/%d %H:%M")
    payload = {
        "username": "Comiket 報名小助手",
        "avatar_url": "https://www.comiket.co.jp/top/img/logo.gif",
        "embeds": [{
            "title": "⚠️ Comiket · 主頁解析失敗",
            "description": (
                f"{msg}\n\n"
                f"[➡️ 手動確認]({MAIN_URL})"
            ),
            "color": 0xFF5733,
            "footer": {"text": f"偵測時間：{now_str}"},
        }],
    }
    requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)


def send_discord_heartbeat(events: dict):
    """📋 每日靜音心跳通知"""
    if not DISCORD_WEBHOOK_URL:
        return
    now_str = datetime.now().strftime("%Y/%m/%d %H:%M")

    if not SHOW_ENDED:
        events = {k: v for k, v in events.items() if not v.get("ended")}

    # 依屆次號碼由大到小排序
    def cno_key(cno):
        m = re.match(r'C(\d+)', cno)
        return -int(m.group(1)) if m else 0

    # 四個分類桶
    active_lines   = []  # 報名進行中（appset 且截止日未到）
    closed_lines   = []  # 報名已截止・活動待舉辦（appset 且截止日已過）
    schedule_lines = []  # 日程已公告（schedule）
    pending_lines  = []  # 尚未公告（pending）

    for cno in sorted(events, key=cno_key):
        info      = events[cno]
        status    = info.get("status", "pending")
        ev_date   = info.get("event_date", "—")
        ended_tag = " ~~已結束~~" if info.get("ended") else ""

        if status == "appset":
            reg_s = info.get("reg_start", "—")
            reg_e = info.get("reg_end", "—")
            # 尚未截止：粗體＋⚠️ 醒目提醒即將截止；已截止：恢復一般文字，但保留「已截止」註記
            reg_e_display = f"{reg_e}（報名已截止）" if is_reg_ended(reg_e) else f"⚠️ **{reg_e}**"
            not_started_tag = " ⏳（尚未開始）" if not is_reg_started(reg_s) else ""
            line = (
                f"**{cno}**{ended_tag}{not_started_tag}\n"
                f"　活動日期：{ev_date}\n"
                f"　報名開始：{reg_s}\n"
                f"　報名截止：{reg_e_display}"
            )
            if is_reg_ended(reg_e):
                closed_lines.append(line)
            else:
                active_lines.append(line)
        elif status == "schedule":
            tentative = info.get("tentative_appset_date", "未定")
            line = (
                f"**{cno}**{ended_tag}\n"
                f"　活動日期：{ev_date}\n"
                f"　報名公告預定：{tentative}"
            )
            schedule_lines.append(line)
        else:
            line = f"**{cno}**{ended_tag}\n　活動日期：{ev_date}\n　報名：⏳ 尚未公告"
            pending_lines.append(line)

    fields = []
    if active_lines:
        fields.append({"name": "── 報名進行中 ──", "value": "\n\n".join(active_lines), "inline": False})
    if schedule_lines:
        fields.append({"name": "── 日程已公告 ──", "value": "\n\n".join(schedule_lines), "inline": False})
    if pending_lines:
        fields.append({"name": "── 尚未公告 ──", "value": "\n\n".join(pending_lines), "inline": False})
    if closed_lines:
        fields.append({"name": "── 報名截止・活動待舉辦 ──", "value": "\n\n".join(closed_lines), "inline": False})

    if not fields:
        fields.append({"name": "目前無監視中的屆次", "value": "—", "inline": False})

    payload = {
        "username": "Comiket 報名小助手",
        "avatar_url": "https://www.comiket.co.jp/top/img/logo.gif",
        "flags": 4096,
        "embeds": [{
            "title": "📋 Comiket · 每週確認",
            "description": f"[➡️ 前往官網確認]({MAIN_URL})",
            "fields": fields,
            "color": 0x888780,
            "footer": {"text": f"確認時間：{now_str}"},
        }],
    }
    requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)


def main():
    print(f"[{datetime.now().strftime('%Y/%m/%d %H:%M:%S')}] 開始檢查...")

    # 1. 抓主頁
    status_code, main_html = fetch_url(MAIN_URL)
    if status_code != 200:
        print(f"[錯誤] 主頁無法抓取（HTTP {status_code}）")
        return

    # 2. 解析目前公告的屆次
    discovered = get_upcoming_comikets(main_html)
    if not discovered:
        print("[警告] 主頁解析不到任何屆次，可能格式已變更")
        send_discord_warning("官網主頁無法解析出屆次資訊，格式可能已變更，請手動確認。")
        return

    print(f"發現屆次：{list(discovered.keys())}")

    previous = load_state()
    current  = {}

    # 3. 對每個屆次進行兩段式檢查
    for cno, meta in discovered.items():
        prev = previous.get(cno, {})
        event_date    = meta["event_date"]
        event_year    = meta["event_year"]
        event_month   = meta["event_month"]
        event_end_day = meta["event_end_day"]

        ended = is_ended(event_year, event_month, event_end_day)

        # 初始化本次狀態（從 previous 繼承或新建）
        entry = {
            "status":               prev.get("status", "pending"),
            "event_date":           event_date,
            "event_year":           event_year,
            "event_month":          event_month,
            "event_end_day":        event_end_day,
            "tentative_appset_date": prev.get("tentative_appset_date", ""),
            "reg_start":            _jp_wd_to_zh(prev.get("reg_start", "—")),
            "reg_end":              _jp_wd_to_zh(prev.get("reg_end", "—")),
            "ended":                ended,
        }

        # 3a. 檢查 Appset 頁（優先）
        appset_ok, appset_html = fetch_url(APPSET_URL.format(cno=cno))
        if appset_ok == 200:
            had_dates = entry["reg_start"] != "—" and entry["reg_end"] != "—"

            if not had_dates:
                # 日期尚未確認過：每次都重新嘗試解析
                # （頁面可能先建立、報名日期晚點才公告，不能只解析一次就鎖死）
                dates = parse_appset_dates(appset_html)
                entry["reg_start"] = dates["reg_start"]
                entry["reg_end"]   = dates["reg_end"]
                now_has_dates = entry["reg_start"] != "—" and entry["reg_end"] != "—"

                if now_has_dates:
                    entry["status"] = "appset"
                    if cno in previous:
                        # 已追蹤過的屆次：發大通知
                        print(f"[申込開始] {cno}：{entry['reg_start']}")
                        send_discord_appset(
                            cno, event_date, entry["reg_start"], entry["reg_end"]
                        )
                    else:
                        print(f"[首次記錄・已申込開始] {cno}")
                else:
                    # 頁面已建立但日期尚未公告：不升級狀態、不發通知，隔天自動重試
                    print(f"[維持] {cno}：頁面已建立，日期尚未公告")
            else:
                print(f"[維持] {cno}：申込受付中")
            current[cno] = entry
            continue

        # 3b. 檢查 Schedule 頁
        sched_ok, sched_html = fetch_url(SCHEDULE_URL.format(cno=cno))
        if sched_ok == 200:
            tentative = parse_schedule_info(sched_html) or entry["tentative_appset_date"]
            entry["tentative_appset_date"] = tentative

            if entry["status"] == "pending":
                entry["status"] = "schedule"
                if cno in previous:
                    print(f"[日程公開] {cno}：{tentative}")
                    send_discord_schedule(cno, event_date, tentative)
                else:
                    print(f"[首次記錄・日程公開] {cno}")
            else:
                print(f"[維持] {cno}：日程公開")
        else:
            print(f"[維持] {cno}：待公開")

        current[cno] = entry

    # 4. 合併並儲存 state
    previous.update(current)
    save_state(previous)

    # 5. 心跳通知（每週一發送）
    if datetime.today().weekday() == 0:  # 0 = 週一
        send_discord_heartbeat(current)

    print("完成。")


if __name__ == "__main__":
    main()
