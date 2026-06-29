import logging
import asyncio
import aiohttp
import numpy as np
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8754472585:AAGIX510vMHTRCTJaGVdnsjn8HjcPqq9-HQ"

# ===== أزواج OTC (بيانات من Yahoo) =====
OTC_PAIRS = [
    {"name": "EUR/USD OTC", "flag": "🇪🇺", "symbol": "EURUSD=X"},
    {"name": "GBP/USD OTC", "flag": "🇬🇧", "symbol": "GBPUSD=X"},
    {"name": "USD/JPY OTC", "flag": "🇺🇸", "symbol": "JPY=X"},
    {"name": "AUD/USD OTC", "flag": "🇦🇺", "symbol": "AUDUSD=X"},
    {"name": "USD/CAD OTC", "flag": "🇨🇦", "symbol": "CAD=X"},
    {"name": "USD/CHF OTC", "flag": "🇨🇭", "symbol": "CHF=X"},
    {"name": "NZD/USD OTC", "flag": "🇳🇿", "symbol": "NZDUSD=X"},
    {"name": "GBP/JPY OTC", "flag": "🇬🇧", "symbol": "GBPJPY=X"},
]

LIVE_PAIRS = [
    {"name": "EUR/USD", "flag": "🇪🇺", "symbol": "EURUSD=X"},
    {"name": "GBP/USD", "flag": "🇬🇧", "symbol": "GBPUSD=X"},
    {"name": "USD/JPY", "flag": "🇺🇸", "symbol": "JPY=X"},
    {"name": "AUD/USD", "flag": "🇦🇺", "symbol": "AUDUSD=X"},
    {"name": "USD/CAD", "flag": "🇨🇦", "symbol": "CAD=X"},
    {"name": "USD/CHF", "flag": "🇨🇭", "symbol": "CHF=X"},
    {"name": "NZD/USD", "flag": "🇳🇿", "symbol": "NZDUSD=X"},
    {"name": "GBP/JPY", "flag": "🇬🇧", "symbol": "GBPJPY=X"},
]

ALL_PAIRS = OTC_PAIRS + LIVE_PAIRS

async def fetch_yahoo_candles(symbol: str, count: int = 80):
    """سحب بيانات الشموع من Yahoo Finance"""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        params = {"interval": "1m", "range": "1d", "includePrePost": "false"}
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return None
        chart = result[0]
        indicators = chart.get("indicators", {}).get("quote", [{}])[0]
        opens = indicators.get("open", [])
        closes = indicators.get("close", [])
        highs = indicators.get("high", [])
        lows = indicators.get("low", [])
        candles = []
        for i in range(len(closes)):
            if closes[i] is None or opens[i] is None:
                continue
            candles.append({
                "open": opens[i], "close": closes[i],
                "high": highs[i] if highs[i] else closes[i],
                "low": lows[i] if lows[i] else closes[i],
            })
        return candles[-count:] if len(candles) >= 20 else None
    except Exception as e:
        logger.warning(f"Yahoo error: {e}")
        return None

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

def calc_macd(closes):
    if len(closes) < 26:
        return 0, 0
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    macd_line = ema12 - ema26
    signal = calc_ema(closes[-9:], 9) if len(closes) >= 9 else macd_line
    return round(macd_line, 6), round(signal, 6)

def analyze_candles(candles, market_type="OTC"):
    closes = [c["close"] for c in candles]
    rsi = calc_rsi(closes)
    ema9 = calc_ema(closes, 9)
    ema21 = calc_ema(closes, 21)
    macd, signal = calc_macd(closes)
    current = closes[-1]
    signals = []
    buy_score, sell_score = 0, 0

    # RSI
    if rsi < 30:
        buy_score += 3
        signals.append(f"RSI Oversold ({rsi})")
    elif rsi > 70:
        sell_score += 3
        signals.append(f"RSI Overbought ({rsi})")

    # EMA
    if current > ema9 > ema21:
        buy_score += 2
        signals.append("EMA Bullish")
    elif current < ema9 < ema21:
        sell_score += 2
        signals.append("EMA Bearish")

    # MACD
    if macd > signal:
        buy_score += 2
        signals.append("MACD Bullish")
    elif macd < signal:
        sell_score += 2
        signals.append("MACD Bearish")

    net = buy_score - sell_score
    direction = "BUY" if net >= 3 else "SELL" if net <= -3 else "WAIT"
    confidence = min(96, max(55, 60 + abs(net) * 4))
    source = "📡 Yahoo Finance (Live Data)"
    return {"direction": direction, "confidence": confidence, "signals": signals[:4], "source": source}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = ReplyKeyboardMarkup([
        [KeyboardButton("📊 OTC Pairs"), KeyboardButton("📈 Live Market")]
    ], resize_keyboard=True)
    await update.message.reply_text("🤖 *VaultFX AI Bot*\nاختر السوق:", parse_mode="Markdown", reply_markup=keyboard)

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
            candles = await fetch_yahoo_candles(pair["symbol"])
            if candles and len(candles) >= 20:
                market_type = "OTC" if "OTC" in pair["name"] else "Live"
                result = analyze_candles(candles, market_type)
                msg = (f"📊 *{pair['name']}*\n"
                       f"📈 الاتجاه: {result['direction']}\n"
                       f"💯 الثقة: {result['confidence']}%\n"
                       f"📌 الإشارات: {', '.join(result['signals']) if result['signals'] else 'لا توجد'}\n"
                       f"📡 المصدر: {result['source']}")
                await update.message.reply_text(msg, parse_mode="Markdown")
            else:
                await update.message.reply_text("⚠️ لا توجد بيانات كافية حالياً، حاول لاحقاً.")
            return
    await update.message.reply_text("👆 اختر من القائمة.")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("🚀 VaultFX AI Bot — يعمل على بيانات Yahoo Finance (بدون SSID)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
