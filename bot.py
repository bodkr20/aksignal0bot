import logging
import asyncio
import json
import numpy as np
import websockets
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ===== إعدادات =====
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== توكن البوت (ضعه مباشرة) =====
BOT_TOKEN = "8764163505:AAHDcE7Ilby66k6VLwOmDFxuQ7gd29x0msE"

# ===== SSID حق Pocket Option =====
PO_SSID = '42["auth",{"sessionToken":"a4cb7bdffb9d586292f6581ca06d58cd","uid":"130213513","lang":"en"}]'

# ===== أزواج OTC =====
OTC_PAIRS = [
    {"name": "AUD/CAD OTC", "flag": "🇦🇺", "symbol": "AUDCAD_otc"},
    {"name": "EUR/USD OTC", "flag": "🇪🇺", "symbol": "EURUSD_otc"},
    {"name": "GBP/USD OTC", "flag": "🇬🇧", "symbol": "GBPUSD_otc"},
    {"name": "USD/JPY OTC", "flag": "🇺🇸", "symbol": "USDJPY_otc"},
    {"name": "AUD/NZD OTC", "flag": "🇦🇺", "symbol": "AUDNZD_otc"},
    {"name": "USD/CHF OTC", "flag": "🇺🇸", "symbol": "USDCHF_otc"},
]

# ===== أزواج Live =====
LIVE_PAIRS = [
    {"name": "EUR/USD", "flag": "🇪🇺", "symbol": "EURUSD"},
    {"name": "GBP/USD", "flag": "🇬🇧", "symbol": "GBPUSD"},
    {"name": "USD/JPY", "flag": "🇺🇸", "symbol": "USDJPY"},
    {"name": "AUD/USD", "flag": "🇦🇺", "symbol": "AUDUSD"},
    {"name": "USD/CAD", "flag": "🇨🇦", "symbol": "USDCAD"},
    {"name": "USD/CHF", "flag": "🇨🇭", "symbol": "USDCHF"},
]

ALL_PAIRS = OTC_PAIRS + LIVE_PAIRS

# ===== WebSocket Pocket Option =====
PO_WS_REGIONS = [
    "wss://api-l.po.market/socket.io/?EIO=4&transport=websocket",
    "wss://api-c.po.market/socket.io/?EIO=4&transport=websocket",
    "wss://api-s.po.market/socket.io/?EIO=4&transport=websocket",
]

async def fetch_po_candles(symbol: str, count: int = 80):
    for ws_url in PO_WS_REGIONS:
        try:
            candles = await _connect_and_fetch(ws_url, symbol, count)
            if candles and len(candles) >= 20:
                return candles
        except Exception as e:
            logger.warning(f"PO WS failed {ws_url}: {e}")
            continue
    return None

async def _connect_and_fetch(ws_url: str, symbol: str, count: int):
    candles = []
    try:
        async with websockets.connect(ws_url, extra_headers={"Origin": "https://pocketoption.com"}, ping_interval=20, ping_timeout=10) as ws:
            await ws.recv()
            await ws.send("40")
            await ws.recv()
            await ws.send(PO_SSID)
            for _ in range(5):
                if "auth/success" in await ws.recv():
                    break
            now_ts = int(datetime.now().timestamp())
            await ws.send(f'42["subscribe",{{"asset":"{symbol}","period":60}}]')
            await ws.send(f'42["loadHistoryPeriod",{{"asset":"{symbol}","period":60,"time":{now_ts},"index":0}}]')
            for _ in range(20):
                msg = await asyncio.wait_for(ws.recv(), timeout=3)
                if "candles" in msg:
                    data = json.loads(msg[2:])
                    if isinstance(data, list) and len(data) >= 2:
                        raw = data[1].get("candles", [])
                        for c in raw:
                            if isinstance(c, dict) and "open" in c:
                                candles.append({"open": c["open"], "close": c["close"], "high": c.get("high", c["close"]), "low": c.get("low", c["close"])})
                    if len(candles) >= 20:
                        break
    except Exception as e:
        logger.warning(f"WS error: {e}")
        return None
    return candles[-count:] if len(candles) >= 20 else None

# ===== المؤشرات الأساسية =====
def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    return round(100 - (100 / (1 + avg_gain / avg_loss)), 2)

def calc_ema(closes, period):
    if len(closes) < period:
        return closes[-1]
    k = 2 / (period + 1)
    ema = np.mean(closes[:period])
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return round(ema, 6)

def analyze_candles(candles, market_type="OTC"):
    closes = [c["close"] for c in candles]
    rsi = calc_rsi(closes)
    ema9 = calc_ema(closes, 9)
    ema21 = calc_ema(closes, 21)
    current = closes[-1]
    signals = []
    buy_score, sell_score = 0, 0
    if rsi < 30:
        buy_score += 3
        signals.append(f"RSI Oversold ({rsi})")
    elif rsi > 70:
        sell_score += 3
        signals.append(f"RSI Overbought ({rsi})")
    if current > ema9 > ema21:
        buy_score += 2
        signals.append("EMA Bullish")
    elif current < ema9 < ema21:
        sell_score += 2
        signals.append("EMA Bearish")
    net = buy_score - sell_score
    direction = "BUY" if net >= 2 else "SELL" if net <= -2 else "WAIT"
    confidence = min(96, max(55, 60 + abs(net) * 5))
    source = "🔴 Pocket Option (Live OTC)" if market_type == "OTC" else "🔵 Pocket Option (Live Market)"
    return {"direction": direction, "confidence": confidence, "signals": signals[:3], "source": source}

# ===== هاندلرز =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = ReplyKeyboardMarkup([
        [KeyboardButton("📊 OTC Pairs"), KeyboardButton("📈 Live Market")]
    ], resize_keyboard=True)
    await update.message.reply_text("🤖 *VaultFX Live Bot*\nاختر السوق:", parse_mode="Markdown", reply_markup=keyboard)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🔙 رجوع":
        await update.message.reply_text("🏠 القائمة الرئيسية:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("📊 OTC Pairs"), KeyboardButton("📈 Live Market")]], resize_keyboard=True))
        return
    if text == "📊 OTC Pairs":
        keyboard = [[KeyboardButton(f"{p['flag']} {p['name']}")] for p in OTC_PAIRS] + [[KeyboardButton("🔙 رجوع")]]
        await update.message.reply_text("📊 اختر زوج OTC:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
        return
    if text == "📈 Live Market":
        keyboard = [[KeyboardButton(f"{p['flag']} {p['name']}")] for p in LIVE_PAIRS] + [[KeyboardButton("🔙 رجوع")]]
        await update.message.reply_text("📈 اختر زوج Live:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
        return
    for pair in ALL_PAIRS:
        if pair["name"] in text:
            await update.message.reply_text(f"⏳ جاري تحليل {pair['name']}...")
            candles = await fetch_po_candles(pair["symbol"])
            if candles and len(candles) >= 20:
                market_type = "OTC" if "OTC" in pair["name"] else "Live"
                result = analyze_candles(candles, market_type)
                msg = (f"📊 *{pair['name']}*\n📈 الاتجاه: {result['direction']}\n💯 الثقة: {result['confidence']}%\n📌 الإشارات: {', '.join(result['signals']) if result['signals'] else 'لا توجد'}\n📡 المصدر: {result['source']}")
                await update.message.reply_text(msg, parse_mode="Markdown")
            else:
                await update.message.reply_text("⚠️ لا توجد بيانات كافية حالياً، حاول لاحقاً.")
            return
    await update.message.reply_text("👆 اختر من القائمة.")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("🚀 VaultFX Live Bot — OTC + Live Market (بيانات حقيقية)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
