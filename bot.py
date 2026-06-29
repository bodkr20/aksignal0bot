import logging
import asyncio
import aiohttp
import numpy as np
from datetime import datetime, timezone, timedelta
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8754472585:AAGIX510vMHTRCTJaGVdnsjn8HjcPqq9-HQ"

# ===== أزواج OTC =====
OTC_PAIRS = [
    {"name": "EUR/USD OTC", "flag": "🇪🇺", "symbol": "EURUSD=X"},
    {"name": "GBP/USD OTC", "flag": "🇬🇧", "symbol": "GBPUSD=X"},
    {"name": "USD/JPY OTC", "flag": "🇺🇸", "symbol": "JPY=X"},
    {"name": "AUD/USD OTC", "flag": "🇦🇺", "symbol": "AUDUSD=X"},
    {"name": "USD/CAD OTC", "flag": "🇨🇦", "symbol": "CAD=X"},
    {"name": "USD/CHF OTC", "flag": "🇨🇭", "symbol": "CHF=X"},
    {"name": "NZD/USD OTC", "flag": "🇳🇿", "symbol": "NZDUSD=X"},
    {"name": "GBP/JPY OTC", "flag": "🇬🇧", "symbol": "GBPJPY=X"},
    {"name": "AUD/CAD OTC", "flag": "🇦🇺", "symbol": "AUDCAD=X"},
    {"name": "AUD/NZD OTC", "flag": "🇦🇺", "symbol": "AUDNZD=X"},
    {"name": "EUR/GBP OTC", "flag": "🇪🇺", "symbol": "EURGBP=X"},
    {"name": "EUR/JPY OTC", "flag": "🇪🇺", "symbol": "EURJPY=X"},
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

# ===== مؤشرات متقدمة =====
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

def calc_bollinger(closes, period=20):
    if len(closes) < period:
        return closes[-1], closes[-1], closes[-1]
    recent = closes[-period:]
    mid = np.mean(recent)
    std = np.std(recent)
    return round(mid, 6), round(mid + 2 * std, 6), round(mid - 2 * std, 6)

def calc_stochastic(closes, period=14):
    if len(closes) < period:
        return 50.0
    recent = closes[-period:]
    lowest, highest = min(recent), max(recent)
    if highest == lowest:
        return 50.0
    return round(((closes[-1] - lowest) / (highest - lowest)) * 100, 2)

def calc_williams_r(candles, period=14):
    if len(candles) < period:
        return -50.0
    recent = candles[-period:]
    hh = max(c["high"] for c in recent)
    ll = min(c["low"] for c in recent)
    if hh == ll:
        return -50.0
    return round(((hh - candles[-1]["close"]) / (hh - ll)) * -100, 2)

def calc_cci(candles, period=20):
    if len(candles) < period:
        return 0
    tp = [(c["high"] + c["low"] + c["close"]) / 3 for c in candles[-period:]]
    mean_tp = np.mean(tp)
    mean_dev = np.mean([abs(t - mean_tp) for t in tp])
    if mean_dev == 0:
        return 0
    return round((tp[-1] - mean_tp) / (0.015 * mean_dev), 2)

def calc_atr(candles, period=14):
    if len(candles) < period + 1:
        return 0
    trs = []
    for i in range(1, len(candles)):
        tr = max(candles[i]["high"] - candles[i]["low"],
                 abs(candles[i]["high"] - candles[i-1]["close"]),
                 abs(candles[i]["low"] - candles[i-1]["close"]))
        trs.append(tr)
    return round(np.mean(trs[-period:]), 6)

# ===== تحليل الأسطوري =====
def analyze_legendary(candles):
    closes = [c["close"] for c in candles]
    rsi = calc_rsi(closes)
    rsi_fast = calc_rsi(closes, 7)
    ema9 = calc_ema(closes, 9)
    ema21 = calc_ema(closes, 21)
    ema50 = calc_ema(closes, 50) if len(closes) >= 50 else closes[-1]
    macd, signal = calc_macd(closes)
    bb_mid, bb_up, bb_low = calc_bollinger(closes)
    stoch = calc_stochastic(closes)
    wr = calc_williams_r(candles)
    cci = calc_cci(candles)
    atr = calc_atr(candles)
    current = closes[-1]
    
    signals = []
    buy_score, sell_score = 0, 0
    
    # RSI
    if rsi < 25: buy_score += 4; signals.append(f"RSI Oversold ({rsi})")
    elif rsi < 35: buy_score += 2; signals.append(f"RSI Low ({rsi})")
    elif rsi > 75: sell_score += 4; signals.append(f"RSI Overbought ({rsi})")
    elif rsi > 65: sell_score += 2; signals.append(f"RSI High ({rsi})")
    
    # RSI Fast
    if rsi_fast < 20: buy_score += 2
    elif rsi_fast > 80: sell_score += 2
    
    # EMA
    if ema9 > ema21 > ema50: buy_score += 3; signals.append("Strong Uptrend")
    elif ema9 < ema21 < ema50: sell_score += 3; signals.append("Strong Downtrend")
    elif ema9 > ema21: buy_score += 1.5
    else: sell_score += 1.5
    
    # MACD
    if macd > signal: buy_score += 2.5; signals.append("MACD Bullish")
    else: sell_score += 2.5; signals.append("MACD Bearish")
    
    # Bollinger
    if current <= bb_low: buy_score += 3; signals.append("BB Oversold")
    elif current >= bb_up: sell_score += 3; signals.append("BB Overbought")
    
    # Stochastic
    if stoch < 20: buy_score += 2; signals.append(f"Stoch Oversold ({stoch})")
    elif stoch > 80: sell_score += 2; signals.append(f"Stoch Overbought ({stoch})")
    
    # Williams %R
    if wr < -80: buy_score += 2; signals.append(f"W%R Oversold ({wr})")
    elif wr > -20: sell_score += 2; signals.append(f"W%R Overbought ({wr})")
    
    # CCI
    if cci < -150: buy_score += 2; signals.append(f"CCI Oversold ({cci})")
    elif cci > 150: sell_score += 2; signals.append(f"CCI Overbought ({cci})")
    
    # ATR (volatility)
    if atr > 0 and current > 0:
        atr_pct = (atr / current) * 100
        if atr_pct > 0.5: buy_score += 0.5; signals.append(f"High Volatility ({round(atr_pct,2)}%)")
    
    net = buy_score - sell_score
    total = buy_score + sell_score
    
    direction = "BUY" if net >= 3 else "SELL" if net <= -3 else "WAIT"
    confidence = min(96, max(50, 50 + abs(net) * 5))
    
    if confidence < 60:
        direction = "WAIT"
    
    return {
        "direction": direction,
        "confidence": confidence,
        "signals": signals[:5],
        "buy_score": round(buy_score, 1),
        "sell_score": round(sell_score, 1),
        "rsi": rsi,
        "stoch": stoch,
        "wr": wr,
        "cci": cci,
        "atr": atr,
        "current": current
    }

# ===== جلب البيانات من Yahoo =====
async def fetch_yahoo_candles(symbol: str, count: int = 80):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        params = {"interval": "1m", "range": "1d", "includePrePost": "false"}
        headers = {"User-Agent": "Mozilla/5.0"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=10) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        result = data.get("chart", {}).get("result", [])
        if not result: return None
        chart = result[0]
        indicators = chart.get("indicators", {}).get("quote", [{}])[0]
        opens = indicators.get("open", [])
        closes = indicators.get("close", [])
        highs = indicators.get("high", [])
        lows = indicators.get("low", [])
        candles = []
        for i in range(len(closes)):
            if closes[i] is None or opens[i] is None: continue
            candles.append({
                "open": opens[i], "close": closes[i],
                "high": highs[i] if highs[i] else closes[i],
                "low": lows[i] if lows[i] else closes[i],
            })
        return candles[-count:] if len(candles) >= 20 else None
    except Exception as e:
        logger.warning(f"Yahoo error: {e}")
        return None

# ===== وقت الدخول =====
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

# ===== كيبوردات =====
def get_expiry_keyboard(pair_name, pair_type):
    if pair_type == "otc":
        buttons = [
            [InlineKeyboardButton("⚡ S5", callback_data=f"exp|S5|{pair_name}|{pair_type}"),
             InlineKeyboardButton("⚡ S10", callback_data=f"exp|S10|{pair_name}|{pair_type}"),
             InlineKeyboardButton("⚡ S15", callback_data=f"exp|S15|{pair_name}|{pair_type}")],
            [InlineKeyboardButton("⏱ M1", callback_data=f"exp|M1|{pair_name}|{pair_type}"),
             InlineKeyboardButton("⏱ M2", callback_data=f"exp|M2|{pair_name}|{pair_type}")]
        ]
    else:
        buttons = [
            [InlineKeyboardButton("⏱ M1", callback_data=f"exp|M1|{pair_name}|{pair_type}"),
             InlineKeyboardButton("⏱ M2", callback_data=f"exp|M2|{pair_name}|{pair_type}"),
             InlineKeyboardButton("⏱ M3", callback_data=f"exp|M3|{pair_name}|{pair_type}")],
            [InlineKeyboardButton("⏱ M5", callback_data=f"exp|M5|{pair_name}|{pair_type}")]
        ]
    return InlineKeyboardMarkup(buttons)

# ===== هاندلرز =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = ReplyKeyboardMarkup([
        [KeyboardButton("📊 OTC Pairs"), KeyboardButton("📈 Live Market")]
    ], resize_keyboard=True)
    await update.message.reply_text(
        "🤖 *VaultFX Legendary Bot*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🟢 *OTC:* استراتيجيات ثواني\n"
        "📡 *Live:* بيانات حقيقية\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚡ *استراتيجيات:* RSI, MACD, BB, Stochastic, CCI, Williams%R, ATR\n"
        "🎯 *فريمات:* S5, S10, S15, M1, M2, M3, M5\n"
        "اختر السوق:",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

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

    await query.edit_message_text(f"{pair['flag']} *{pair_name}* — ⏱ {expiry}\n⏳ جاري التحليل...", parse_mode="Markdown")

    candles = await fetch_yahoo_candles(pair["symbol"])
    if not candles or len(candles) < 20:
        await query.edit_message_text("⚠️ لا توجد بيانات كافية حالياً، حاول لاحقاً.")
        return

    result = analyze_legendary(candles)
    entry_time, candle_note = get_entry_time()

    # إحصائيات التصويت
    vote_total = result['buy_score'] + result['sell_score']
    bull_pct = int(result['buy_score'] / vote_total * 100) if vote_total > 0 else 50
    bear_pct = 100 - bull_pct

    # قوة الإشارة
    if result['confidence'] >= 85: rocket = "🚀🚀🚀🚀🚀"
    elif result['confidence'] >= 75: rocket = "🚀🚀🚀🚀"
    elif result['confidence'] >= 65: rocket = "🚀🚀🚀"
    elif result['confidence'] >= 55: rocket = "🚀🚀"
    else: rocket = "🚀"

    if result['direction'] == "WAIT":
        final_text = (
            f"⏳ *انتظر — لا توجد إشارة قوية*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💱 {pair['flag']} *{pair_name}*\n"
            f"⏱ *الفريم:* {expiry}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🚀 *قوة الإشارة:* {rocket}\n"
            f"💯 *الثقة:* {result['confidence']}% — ضعيفة\n"
            f"📡 *المصدر:* 📡 Yahoo Finance\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ *لا تدخل الصفقة الآن*\n"
            f"🔄 انتظر إشارة أقوى"
        )
    else:
        direction_ar = "شراء 🟢" if result['direction'] == "BUY" else "بيع 🔴"
        emoji = "🟢" if result['direction'] == "BUY" else "🔴"
        final_text = (
            f"{emoji} *{result['direction']}*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💱 {pair['flag']} *{pair_name}*\n"
            f"⏱ *الفريم:* {expiry}\n"
            f"🕐 *وقت الدخول:* {entry_time} (UTC+3)\n"
            f"📌 *الدخول في:* {candle_note}\n"
            f"📊 *الإشارة:* {direction_ar}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🚀 *قوة الإشارة:* {rocket}\n"
            f"💯 *الثقة:* {result['confidence']}%\n"
            f"🗳 *التصويت:* 🟢 {bull_pct}% | 🔴 {bear_pct}%\n"
            f"📊 *RSI:* {result['rsi']} | *Stoch:* {result['stoch']}\n"
            f"📊 *W%R:* {result['wr']} | *CCI:* {result['cci']}\n"
            f"📡 *المصدر:* 📡 Yahoo Finance\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ _Trade at your own risk_"
        )

    keyboard = get_live_keyboard() if pair_type == "live" else get_otc_keyboard()
    await query.edit_message_text(final_text, parse_mode="Markdown", reply_markup=keyboard)

def get_otc_keyboard():
    keyboard = [[KeyboardButton(f"{p['flag']} {p['name']}")] for p in OTC_PAIRS] + [[KeyboardButton("🔙 رجوع")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_live_keyboard():
    keyboard = [[KeyboardButton(f"{p['flag']} {p['name']}")] for p in LIVE_PAIRS] + [[KeyboardButton("🔙 رجوع")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_expiry, pattern="^exp\\|"))
    print("🚀 VaultFX Legendary Bot — أسطوري يعمل على Yahoo Finance")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
