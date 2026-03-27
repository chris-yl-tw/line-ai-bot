"""
AI 意圖辨識與回覆生成模組（Google Gemini 版）
=============================================
使用 Google Gemini API（免費方案）分析用戶訊息意圖，
並以「個人化、有溫度」的繁體中文風格生成回覆。
"""

import os
import logging
from google import genai
from google.genai import types as genai_types

logger = logging.getLogger(__name__)

# 依序嘗試的模型清單（免費額度較寬裕的排在前面）
MODELS_TO_TRY = [
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-2.0-flash",
]

# ── 初始化 Gemini 客戶端 ──────────────────────────────────────────────────────
_client = None

def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise EnvironmentError("請在 .env 中設定 GEMINI_API_KEY")
        _client = genai.Client(api_key=api_key)
    return _client


# ── System Prompt 工廠 ────────────────────────────────────────────────────────

def _build_system_prompt(user_name: str, store_context: str) -> str:
    return f"""你是一位親切、專業的「特約商店智慧助理」，負責回覆 LINE 官方帳號上的用戶訊息。

## 你的角色定位
- 你代表特約商店聯盟，服務合作商店的顧客
- 你的語氣溫暖、有人情味，像朋友一樣聊天，但仍保持專業
- 用戶的名字是「{user_name}」，適時稱呼對方增加親切感（不要每句話都叫名字，自然即可）

## 知識庫（以下是你掌握的所有商店與優惠資訊）
{store_context}

## 回覆原則

### 意圖辨識
根據用戶訊息，判斷屬於下列哪種意圖：
1. **商店資訊查詢**：詢問地址、電話、營業時間、交通、商店類型等
2. **優惠活動查詢**：詢問折扣、回饋、活動期限、參與方式等
3. **一般互動**：打招呼、閒聊、感謝等
4. **抱怨 / 反映**：對服務或商品不滿

### 回覆風格
- 繁體中文，語氣輕鬆但不失禮
- 回覆長度適中，不過長（以 LINE 閱讀習慣為準，200 字以內為佳）
- 善用換行讓訊息易讀，避免大段文字
- 資訊正確、不捏造知識庫以外的資訊
- 若問題超出知識庫範圍，友善告知並建議用戶聯絡客服

### 特殊情境處理
- 若用戶查詢的商店或優惠不在清單中：誠實說明，並提供最相近的選項
- 若用戶語意模糊：溫柔追問，例如「請問您想了解哪間商店的資訊呢？」
- 若用戶抱怨：先表達理解與同理，再提供解決方向

### 回覆範例風格（請模仿）
✅ 好的回覆：
「{user_name}，您好！幸福咖啡館在台北市大安區仁愛路四段 100 號，
營業時間是週一到週五早上 8 點到晚上 9 點喔 ☕
如果要去的話，記得他們週末也有開到 10 點，方便很多！
需要其他資訊歡迎繼續問我 😊」

❌ 不好的回覆：
「幸福咖啡館地址：台北市大安區仁愛路四段100號。電話：02-2700-1234。」
（太生硬，像資料庫輸出）
"""


# ── 主要函式 ──────────────────────────────────────────────────────────────────

def generate_ai_response(
    user_name: str,
    user_message: str,
    store_context: str,
    model: str = "gemini-2.0-flash-lite",
    max_tokens: int = 400,
) -> str:
    """
    呼叫 Gemini API，根據用戶訊息生成個人化回覆。
    自動嘗試多個模型，避免單一模型額度耗盡。
    """
    system_prompt = _build_system_prompt(user_name, store_context)
    full_prompt = f"{system_prompt}\n\n用戶訊息：{user_message}"

    client = _get_client()
    for model_name in MODELS_TO_TRY:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=full_prompt,
                config=genai_types.GenerateContentConfig(
                    max_output_tokens=max_tokens,
                    temperature=0.7,
                ),
            )
            reply = response.text.strip()
            logger.info(f"Gemini 回覆生成成功（模型：{model_name}）")
            return reply

        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
                logger.warning(f"模型 {model_name} 額度不足，嘗試下一個模型…")
                continue
            # 其他錯誤直接中斷
            logger.error(f"Gemini API 呼叫失敗（{model_name}）：{e}")
            break

    logger.error("所有模型均無法回應，回傳備援訊息")
    return _fallback_response(user_name)


def _fallback_response(user_name: str) -> str:
    """當 AI 呼叫失敗時的備援回覆"""
    return (
        f"{user_name}，非常抱歉，我目前遇到一點小問題，暫時無法回覆您的問題 😢\n\n"
        "請稍後再試，或直接聯絡我們的客服人員為您服務，謝謝您的耐心！"
    )


# ── 工具函式（供測試或進階用）────────────────────────────────────────────────

def detect_intent(user_message: str) -> str:
    """輕量版意圖偵測（關鍵字規則，不呼叫 AI）"""
    msg = user_message.lower()
    promotion_keywords = ["優惠", "折扣", "活動", "回饋", "點數", "折價", "特價", "免費", "贈送"]
    store_keywords = ["地址", "在哪", "怎麼去", "電話", "幾點", "營業", "幾號", "位置", "交通"]
    complaint_keywords = ["投訴", "抱怨", "不滿意", "很差", "爛", "差勁", "退費", "糾紛"]

    if any(kw in msg for kw in complaint_keywords):
        return "complaint"
    if any(kw in msg for kw in promotion_keywords):
        return "promotion"
    if any(kw in msg for kw in store_keywords):
        return "store_info"
    return "general"
