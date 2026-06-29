import logging
import asyncio
import aiohttp
import numpy as np
from datetime import datetime, timezone, timedelta
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8764163505:AAHDcE7Ilby66k6VLwOmDFxuQ7gd29x0msE"

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
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        params = {"interval": "1m", "range": "1d", "includePrePost": "false"}
        headers = {"User-Agent": "Mozilla/5.0"}
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
    macd = ema12 - ema26
    signal = calc_ema(closes[-9:], 9) if len(closes) >= 9 else macd
    return round(macd, 6), round(signal, 6)

def analyze_candles(candles):
    closes = [c["close"] for c in candles]
    rsi = calc_rsi(closes)
    ema9 = calc_ema(closes, 9)
    ema21 = calc_ema(closes, 21)
    macd, signal = calc_macd(closes)
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

    if macd > signal:
        buy_score += 2
        signals.append("MACD Bullish")
    elif macd < signal:
        sell_score += 2
        signals.append("MACD Bearish")

    net = buy_score - sell_score
    direction = "BUY" if net >= 3 else "SELL" if net <= -3 else "WAIT"
    confidence = min(96, max(55, 60 + abs(net) * 4))
    return {"direction": direction, "confidence": confidence, "signals": signals[:3]}

def get_entry_time():
    utc3 = timezone(timedelta(hours=3))
    now = datetime.now(utc3)
    if now.second >= 30:
        entry = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        candle_note = "الشمعة القادمة ⏭"
    else:
        entry = now.replace(second=0, microsecond=0)
        candle_note = "الشمعة الحالية ▶️"
    hour = entry.hour
    period = "صباحاً" if hour < 12 else "مساءً"
    hour_12 = hour % 12 or 12
    return f"{hour_12}:{entry.strftime('%M')} {period}", candle_note

def get_expiry_keyboard(pair_name, pair_type):
    if pair_type == "otc":
        buttons = [
            [InlineKeyboardButton("⚡ S5", callback_data=f"exp|S5|{pair_name}|{pair_type}"),
             InlineKeyboardButton("⚡ S10", callback_data=f"exp|S10|{pair_name}|{pair_type}")],
            [InlineKeyboardButton("⏱ M1", callback_data=f"exp|M1|{pair_name}|{pair_type}"),
             InlineKeyboardButton("⏱ M2", callback_data=f"exp|M2|{pair_name}|{pair_type}")]
        ]
    else:
        buttons = [
            [InlineKeyboardButton("⏱ M1", callback_data=f"exp|M1|{pair_name}|{pair_type}"),
             InlineKeyboardButton("⏱ M2", callback_data=f"exp|M2|{pair_name}|{pair_type}")]
        ]
    return InlineKeyboardMarkup(buttons)

def get_otc_keyboard():
    keyboard = [[KeyboardButton(f"{p['flag']} {p['name']}")] for p in OTC_PAIRS] + [[KeyboardButton("🔙 رجوع")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_live_keyboard():
    keyboard = [[KeyboardButton(f"{p['flag']} {p['name']}")] for p in LIVE_PAIRS] + [[KeyboardButton("🔙 رجوع")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = ReplyKeyboardMarkup([
        [KeyboardButton("📊 OTC Pairs"), KeyboardButton("📈 Live Market")]
    ], resize_keyboard=True)
    await update.message.reply_text(
        "🤖 *VaultFX Bot*\n━━━━━━━━━━━━━━━━━━\n"
        "📡 *المصدر:* Yahoo Finance\n"
        "✅ *بيانات حقيقية*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "اختر السوق:",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🔙 رجوع":
        await update.message.reply_text(
            "🏠 القائمة الرئيسية:",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("📊 OTC Pairs"), KeyboardButton("📈 Live Market")]],
                resize_keyboard=True
            )
        )
        return
    if text == "📊 OTC Pairs":
        await update.message.reply_text("📊 اختر زوج OTC:", reply_markup=get_otc_keyboard())
        return
    if text == "📈 Live Market":
        await update.message.reply_text("📈 اختر زوج Live:", reply_markup=get_live_keyboard())
        return
    for pair in ALL_PAIRS:
        if pair["name"] in text:
            pair_type = "otc" if "OTC" in pair["name"] else "live"
            await update.message.reply_text(
                f"{pair['flag']} *{pair['name']}*\n\n⏱ اختر الفريم:",
                parse_mode="Markdown",
                reply_markup=get_expiry_keyboard(pair["name"], pair_type)
            )
            return
    await update.message.reply_text("👆 اختر من القائمة.")

async def handle_expiry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("|")
    expiry, pair_name, pair_type = data[1], data[2], data[3]
    pair = next((p for p in ALL_PAIRS if p["name"] == pair_name), None)
    if not pair:
        await query.edit_message_text("❌ خطأ، حاول مجدداً.")
        return

    await query.edit_message_text(
        f"{pair['flag']} *{pair_name}* — ⏱ {expiry}\n⏳ جاري التحليل...",
        parse_mode="Markdown"
    )

    candles = await fetch_yahoo_candles(pair["symbol"])
    if not candles or len(candles) < 20:
        await query.edit_message_text("⚠️ لا توجد بيانات كافية، حاول لاحقاً.")
        return

    result = analyze_candles(candles)
    entry_time, candle_note = get_entry_time()

    if result['confidence'] >= 80: rocket = "🚀🚀🚀🚀"
    elif result['confidence'] >= 70: rocket = "🚀🚀🚀"
    elif result['confidence'] >= 60: rocket = "🚀🚀"
    else: rocket = "🚀"

    if result['direction'] == "WAIT":
        final_text = (
            f"⏳ *انتظر*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💱 {pair['flag']} *{pair_name}*\n"
            f"⏱ *الفريم:* {expiry}\n"
            f"🚀 *القوة:* {rocket}\n"
            f"💯 *الثقة:* {result['confidence']}%\n"
            f"📡 *المصدر:* Yahoo Finance\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ *لا تدخل الصفقة الآن*"
        )
    else:
        emoji = "🟢" if result['direction'] == "BUY" else "🔴"
        direction_ar = "شراء" if result['direction'] == "BUY" else "بيع"
        final_text = (
            f"{emoji} *{result['direction']}*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💱 {pair['flag']} *{pair_name}*\n"
            f"⏱ *الفريم:* {expiry}\n"
            f"🕐 *الدخول:* {entry_time} (UTC+3)\n"
            f"📌 *الدخول في:* {candle_note}\n"
            f"📊 *الإشارة:* {direction_ar}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🚀 *القوة:* {rocket}\n"
            f"💯 *الثقة:* {result['confidence']}%\n"
            f"📌 *الإشارات:* {', '.join(result['signals']) if result['signals'] else 'لا توجد'}\n"
            f"📡 *المصدر:* Yahoo Finance\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ _Trade at your own risk_"
        )

    keyboard = get_live_keyboard() if pair_type == "live" else get_otc_keyboard()
    await query.edit_message_text(final_text, parse_mode="Markdown", reply_markup=keyboard)

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_expiry, pattern="^exp\\|"))
    print("🚀 VaultFX Bot — يعمل مع Yahoo Finance")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
