"""
LINE Health Manager Bot - Backend (FastAPI)
Runs on: Render (free tier) / Cloud Run / Fly.io
"""

import hashlib
import hmac
import json
import logging
import os
import re
from base64 import b64decode
from datetime import datetime, timezone, timedelta

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from google import generativeai as genai

load_dotenv()

# ─── Logging ───────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ─── Config ────────────────────────────────────────────────────────────────
LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
LINE_CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GAS_ENDPOINT_URL = os.environ["GAS_ENDPOINT_URL"]

LINE_API_BASE = "https://api.line.me/v2/bot"

JST = timezone(timedelta(hours=9))

# ─── Gemini Setup ──────────────────────────────────────────────────────────
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(
    model_name="gemini-2.5-flash",
    generation_config=genai.GenerationConfig(
        response_mime_type="application/json",
    ),
)

SYSTEM_PROMPT = """あなたは優秀な栄養管理AIです。ユーザーが送ってきた食事・体重・体調の記録を解析し、
以下のJSONスキーマに完全に準拠したJSONオブジェクト**のみ**を返してください。
説明文やマークダウン記法（```json等）は一切含めないこと。

JSONスキーマ:
{
  "date": "YYYY/MM/DD",          // 今日の日付（JST、YYYY/MM/DD形式）
  "timing": "朝 or 昼 or 夜 or 間食",  // 食事タイミング（テキストから推測）
  "food": "食べたものの名前（簡潔に）",
  "calories": 整数,               // 推定カロリー（kcal）
  "weight": 数値 or null,         // 体重（kg）。記載があれば数値、なければnull
  "memo": "体調・その他のメモ",    // 食事・体調の特記事項。なければ空文字
  "advice": "栄養アドバイス（100字程度）" // PFCバランスを踏まえた具体的なアドバイス
}

ルール:
- calories は整数で返すこと（小数不可）
- timing は 朝/昼/夜/間食 のいずれか1つ
- 不明な項目は推測で補完してよいが、weight だけは記載がない場合必ず null にする
- 現在日時は外部から渡されるので、そのまま date フィールドに使用する
"""

# ─── FastAPI App ───────────────────────────────────────────────────────────
app = FastAPI(title="LINE Health Manager Bot")

# ユーザーごとの確認待ちデータ（キー: user_id）
pending_records: dict[str, dict] = {}

# Quick Reply で送信されるコマンドテキスト
CMD_CONFIRM = "✅ 記録する"
CMD_CANCEL  = "❌ キャンセル"


# ─── Helpers ───────────────────────────────────────────────────────────────
def verify_line_signature(body: bytes, signature: str) -> bool:
    """LINEのHMAC-SHA256署名を検証する"""
    hash_value = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    expected = b64decode(signature)
    return hmac.compare_digest(hash_value, expected)


async def reply_to_line(reply_token: str, messages: list[dict]) -> None:
    """LINE Reply APIを叩く"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }
    payload = {"replyToken": reply_token, "messages": messages}
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{LINE_API_BASE}/message/reply",
            headers=headers,
            json=payload,
            timeout=10.0,
        )
    if resp.status_code != 200:
        logger.error("LINE reply failed: %s %s", resp.status_code, resp.text)


async def post_to_gas(data: dict) -> bool:
    """GAS WebアプリへJSONをPOSTする。
    GASは doPost の結果を 302 → echo エンドポイント(GET) 経由で返す。
    httpx が 302 後に POST→GET へ変換するのはこの仕様に合った正しい挙動。
    """
    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.post(
            GAS_ENDPOINT_URL,
            json=data,
            timeout=15.0,
        )
    if resp.status_code != 200:
        logger.error("GAS post failed: %s %s", resp.status_code, resp.text)
        return False
    logger.info("GAS post succeeded: %s", resp.text)
    return True


def analyze_with_gemini(user_text: str) -> dict:
    """Gemini APIでテキストを解析し、JSONを返す"""
    today = datetime.now(JST).strftime("%Y/%m/%d")
    prompt = f"{SYSTEM_PROMPT}\n\n現在の日付（JST）: {today}\n\nユーザーの入力:\n{user_text}"

    response = model.generate_content(prompt)
    raw = response.text.strip()

    # フェイルセーフ: ```json ... ``` ブロックが混入した場合でも抽出する
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"Gemini returned non-JSON response: {raw[:200]}")

    return json.loads(match.group(0))


def build_preview_message(data: dict) -> list[dict]:
    """確認用プレビューメッセージ（Quick Reply ボタン付き）を組み立てる"""
    timing   = data.get("timing", "不明")
    food     = data.get("food", "不明")
    calories = data.get("calories", "?")
    advice   = data.get("advice", "")

    lines = [
        "📋 以下の内容をスプレッドシートに記録します。よろしいですか？",
        "",
        f"📅 日付: {data.get('date', '？')}",
        f"🍽️ タイミング: {timing}",
        f"🥗 食事内容: {food}",
        f"🔥 推定カロリー: {calories} kcal",
    ]
    if data.get("weight"):
        lines.append(f"⚖️ 体重: {data['weight']} kg")
    if data.get("memo"):
        lines.append(f"📝 メモ: {data['memo']}")
    lines += ["", f"💡 {advice}"]

    text = "\n".join(lines).strip()
    return [
        {
            "type": "text",
            "text": text,
            "quickReply": {
                "items": [
                    {
                        "type": "action",
                        "action": {
                            "type": "message",
                            "label": "記録する",
                            "text": CMD_CONFIRM,
                        },
                    },
                    {
                        "type": "action",
                        "action": {
                            "type": "message",
                            "label": "キャンセル",
                            "text": CMD_CANCEL,
                        },
                    },
                ]
            },
        }
    ]


def build_confirmed_message(data: dict) -> list[dict]:
    """記録完了メッセージを組み立てる"""
    timing   = data.get("timing", "不明")
    food     = data.get("food", "不明")
    calories = data.get("calories", "?")
    advice   = data.get("advice", "")

    lines = [
        "✅ スプレッドシートに記録しました！",
        "",
        f"🍽️ {timing}食: {food}",
        f"🔥 推定カロリー: {calories} kcal",
    ]
    if data.get("weight"):
        lines.append(f"⚖️ 体重: {data['weight']} kg")
    lines.append(f"💡 {advice}")

    return [{"type": "text", "text": "\n".join(lines).strip()}]


# ─── Routes ────────────────────────────────────────────────────────────────
@app.get("/")
@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.post("/callback")
async def line_callback(request: Request):
    body_bytes = await request.body()
    signature = request.headers.get("X-Line-Signature", "")

    # 署名検証
    if not verify_line_signature(body_bytes, signature):
        logger.warning("Invalid LINE signature")
        raise HTTPException(status_code=403, detail="Invalid signature")

    body = json.loads(body_bytes.decode("utf-8"))
    events = body.get("events", [])

    for event in events:
        event_type  = event.get("type")
        reply_token = event.get("replyToken", "")
        user_id     = event.get("source", {}).get("userId", "")

        # ── テキストメッセージ以外はスキップ ──
        if event_type != "message" or event["message"].get("type") != "text":
            continue

        user_text = event["message"]["text"].strip()
        logger.info("user=%s text=%s", user_id, user_text)

        # ── ① 確認コマンドの処理 ──────────────────────────────────────
        if user_text == CMD_CONFIRM:
            data = pending_records.pop(user_id, None)
            if data is None:
                messages = [{"type": "text", "text": "⚠️ 確認待ちのデータがありません。食事内容を再送信してください。"}]
            else:
                try:
                    gas_ok = await post_to_gas(data)
                    if gas_ok:
                        messages = build_confirmed_message(data)
                    else:
                        messages = [{"type": "text", "text": "⚠️ スプレッドシートへの記録に失敗しました。しばらく後に再試行してください。"}]
                except Exception as e:
                    logger.exception("GAS post error: %s", e)
                    messages = [{"type": "text", "text": "⚠️ 記録中にエラーが発生しました。"}]
            await reply_to_line(reply_token, messages)
            continue

        # ── ② キャンセルコマンドの処理 ────────────────────────────────
        if user_text == CMD_CANCEL:
            pending_records.pop(user_id, None)
            messages = [{"type": "text", "text": "❌ キャンセルしました。記録は行われていません。"}]
            await reply_to_line(reply_token, messages)
            continue

        # ── ③ 新規入力: Gemini 解析 → 確認プレビュー ─────────────────
        try:
            data = analyze_with_gemini(user_text)
            logger.info("Gemini parsed: %s", data)
            pending_records[user_id] = data          # 確認待ちとして保存
            messages = build_preview_message(data)

        except json.JSONDecodeError as e:
            logger.error("JSON parse error from Gemini: %s", e)
            messages = [{"type": "text", "text": "⚠️ AIの応答を解析できませんでした。もう少し具体的に食事内容を入力してみてください。"}]
        except Exception as e:
            logger.exception("Unexpected error: %s", e)
            messages = [{"type": "text", "text": "⚠️ エラーが発生しました。しばらく後に再試行してください。"}]

        await reply_to_line(reply_token, messages)

    return JSONResponse(content={"status": "ok"})
