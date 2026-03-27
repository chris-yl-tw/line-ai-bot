"""
特約商店資料模組
================
集中管理所有商店資訊與優惠活動，供 AI 作為知識背景使用。
請依實際資料修改 STORES 與 PROMOTIONS 內容。
"""

from typing import Any

# ── 商店資料 ──────────────────────────────────────────────────────────────────
# 格式說明：每筆商店為一個 dict，欄位可依需求擴充

STORES: list[dict[str, Any]] = [
    {
        "id": "S001",
        "name": "幸福咖啡館",
        "category": "餐飲",
        "address": "台北市大安區仁愛路四段 100 號",
        "phone": "02-2700-1234",
        "hours": "週一至週五 08:00–21:00，週末 09:00–22:00",
        "tags": ["咖啡", "甜點", "輕食"],
        "notes": "提供免費 Wi-Fi，適合商務洽談",
    },
    {
        "id": "S002",
        "name": "健康生活超市",
        "category": "零售",
        "address": "台北市信義區松仁路 58 號",
        "phone": "02-8101-5678",
        "hours": "每日 07:00–23:00",
        "tags": ["有機食品", "保健品", "生鮮"],
        "notes": "持特約商店卡享 9 折優惠",
    },
    {
        "id": "S003",
        "name": "活力健身中心",
        "category": "健身",
        "address": "台北市中山區南京東路二段 200 號 5F",
        "phone": "02-2500-9900",
        "hours": "週一至週六 06:00–23:00，週日 08:00–20:00",
        "tags": ["健身房", "瑜珈", "游泳池"],
        "notes": "首次體驗免費，特約會員月費 8 折",
    },
    {
        "id": "S004",
        "name": "美麗時尚美容院",
        "category": "美容",
        "address": "台北市松山區民生東路四段 30 號",
        "phone": "02-2713-3456",
        "hours": "週二至週日 10:00–20:00（週一休）",
        "tags": ["剪髮", "染燙", "美甲", "SPA"],
        "notes": "預約可享 85 折，生日當月全館 8 折",
    },
    {
        "id": "S005",
        "name": "科技電腦旗艦店",
        "category": "3C 電子",
        "address": "台北市中正區重慶南路一段 50 號",
        "phone": "02-2311-7788",
        "hours": "每日 10:00–21:00",
        "tags": ["筆電", "手機", "周邊配件", "維修"],
        "notes": "特約會員享 0 利率 12 期分期，維修工本費 9 折",
    },
]

# ── 優惠活動資料 ──────────────────────────────────────────────────────────────

PROMOTIONS: list[dict[str, Any]] = [
    {
        "id": "P001",
        "title": "春季美食節",
        "stores": ["幸福咖啡館", "健康生活超市"],
        "period": "2026-03-01 ~ 2026-04-30",
        "content": "消費滿 300 元回饋 30 點，點數可折抵下次消費，1 點 = 1 元",
        "condition": "持特約商店會員卡或出示 LINE 綁定頁面",
    },
    {
        "id": "P002",
        "title": "健康動起來方案",
        "stores": ["活力健身中心"],
        "period": "2026-03-15 ~ 2026-05-31",
        "content": "新辦年卡享 75 折，並贈送 3 堂私人教練課（市值 $2,400）",
        "condition": "須為首次辦卡會員，憑此活動代碼 FIT2026",
    },
    {
        "id": "P003",
        "title": "美麗煥新活動",
        "stores": ["美麗時尚美容院"],
        "period": "2026-04-01 ~ 2026-04-30",
        "content": "全館服務 8 折，指定護髮療程買一送一",
        "condition": "線上預約方享折扣，現場不適用",
    },
    {
        "id": "P004",
        "title": "3C 換新季",
        "stores": ["科技電腦旗艦店"],
        "period": "2026-03-20 ~ 2026-04-20",
        "content": "舊機折價最高 $3,000，購買指定品牌筆電加贈無線滑鼠",
        "condition": "須出示舊機現場估價，折扣不與其他優惠合併",
    },
]


# ── 對外介面 ──────────────────────────────────────────────────────────────────

def get_store_context() -> str:
    """
    將商店與優惠資料整理成結構化文字，供 AI 系統提示使用。
    """
    stores_text = "\n".join(
        f"[{s['id']}] {s['name']}（{s['category']}）\n"
        f"  地址：{s['address']}\n"
        f"  電話：{s['phone']}\n"
        f"  營業時間：{s['hours']}\n"
        f"  標籤：{'、'.join(s['tags'])}\n"
        f"  備註：{s['notes']}"
        for s in STORES
    )

    promos_text = "\n".join(
        f"[{p['id']}] {p['title']}\n"
        f"  適用商店：{'、'.join(p['stores'])}\n"
        f"  活動期間：{p['period']}\n"
        f"  內容：{p['content']}\n"
        f"  條件：{p['condition']}"
        for p in PROMOTIONS
    )

    return (
        "=== 特約商店清單 ===\n"
        f"{stores_text}\n\n"
        "=== 目前優惠活動 ===\n"
        f"{promos_text}"
    )


def search_stores(keyword: str) -> list[dict]:
    """根據關鍵字搜尋商店（供進階擴充用）"""
    kw = keyword.lower()
    return [
        s for s in STORES
        if kw in s["name"].lower()
        or kw in s["category"].lower()
        or any(kw in tag.lower() for tag in s["tags"])
        or kw in s["address"].lower()
    ]
