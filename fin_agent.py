import logging
import yfinance as yf
import pandas as pd
import ta
import os
import time
import pytz
import requests
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from flask import Flask
import threading

# 1. LOGLAMA VE FLASK YAPILANDIRMASI
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.WARNING)

flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Finans Ajani Calisiyor!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port)

# 2. AYARLAR VE FOREX PARİTELERİ
# BURAYA BOTFATHER'DAN ALACAĞINIZ YENİ TOKENI YAPIŞTIRIN!
TELEGRAM_TOKEN = "8714335607:AAEXVAqXmIdKWF1BD9R3aLWoFzkv4A3y_pc"
MY_CHAT_ID = 965495144

POPULAR_MARKETS = {
    "EURUSD=X": "EUR/USD Forex",
    "GBPUSD=X": "GBP/USD Forex",
    "USDCHF=X": "USD/CHF Forex",
    "USDJPY=X": "USD/JPY Forex",
    "USDTRY=X": "USD/TRY Forex",
    "GC=F": "Altin ONS (Gold)",
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum",
    "THYAO.IS": "Turk Hava Yollari",
    "XU100.IS": "BIST 100 Endeksi"
}

# 3. ENGELLENMEYEN VE KİLİTLENMEYEN VERİ MOTORU
def analyze_market_safe(ticker):
    try:
        # Yahoo kısıtlamasını aşmak için her parite öncesi 1 saniye bekle
        time.sleep(1.0)
        
        # yfinance kütüphanesini tarayıcı gibi davranması için özelleştirilmiş session ile tetikliyoruz
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
        
        asset = yf.Ticker(ticker, session=session)
        df = asset.history(period='3mo', interval='1d', timeout=10) # 10 saniye zaman aşımı (Kilitlenmeyi önler)
        
        if df.empty or len(df) < 20:
            return None
        
        df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
        df['MACD'] = ta.trend.macd(df['Close'])
        df['MACD_Signal'] = ta.trend.macd_signal(df['Close'])
        df['ATR'] = ta.volatility.average_true_range(df['High'], df['Low'], df['Close'], window=14)
        
        current_price = df['Close'].iloc[-1]
        rsi = df['RSI'].iloc[-1] if not pd.isna(df['RSI'].iloc[-1]) else 50.0
        macd = df['MACD'].iloc[-1] if not pd.isna(df['MACD'].iloc[-1]) else 0.0
        macd_sig = df['MACD_Signal'].iloc[-1] if not pd.isna(df['MACD_Signal'].iloc[-1]) else 0.0
        atr = df['ATR'].iloc[-1] if not pd.isna(df['ATR'].iloc[-1]) else (current_price * 0.002)
        
        is_forex = ticker.endswith("=X") or ticker == "GC=F"
        
        if is_forex:
            tz_turkey = pytz.timezone('Europe/Istanbul')
            now_turkey = datetime.now(tz_turkey)
            current_hour = now_turkey.hour
            if 0 <= current_hour < 8:
                return "LOW_LIQUIDITY"

        score = 0
        if rsi < 30: score += 1
        elif rsi > 70: score -= 1
        
        if macd > macd_sig: score += 1
        else: score -= 1
        
        if score >= 2: signal = "[STRONGBUY]"
        elif score == 1: signal = "[BUY]"
        elif score == -1: signal = "[SELL]"
        elif score <= -2: signal = "[STRONGSELL]"
        else: signal = "[NEUTRAL]"
        
        spread_buffer = atr * 0.1
        entry_low = current_price - spread_buffer
        entry_high = current_price + spread_buffer
        
        demo_bakiye = 1000.0
        risk_orani = 0.015
        risk_tutari = demo_bakiye * risk_orani
        
        atr_multiplier_sl = 1.5
        atr_multiplier_tp = 3.0
        
        if "BUY" in signal:
            sl = current_price - (atr * atr_multiplier_sl)
            tp = current_price + (atr * atr_multiplier_tp)
        elif "SELL" in signal:
            sl = current_price + (atr * atr_multiplier_sl)
            tp = current_price - (atr * atr_multiplier_tp)
        else:
            sl = current_price - (atr * 2.0)
            tp = current_price + (atr * 2.0)
            
        lot_onerisi = "N/A"
        if is_forex and ("BUY" in signal or "SELL" in signal):
            pips_at_risk = abs(current_price - sl)
            if pips_at_risk > 0:
                if ticker == "GC=F":
                    hesaplanan_lot = risk_tutari / (pips_at_risk * 100)
                else:
                    hesaplanan_lot = risk_tutari / (pips_at_risk * 100000)
                ideal_lot = max(0.01, round(hesaplanan_lot, 2))
                lot_onerisi = f"{ideal_lot} Lot"

        return {
            "ticker": ticker,
            "name": POPULAR_MARKETS[ticker],
            "price": f"{current_price:.5f}",
            "entry": f"{entry_low:.5f} - {entry_high:.5f}",
            "signal": signal,
            "sl": f"{sl:.5f}",
            "tp": f"{tp:.5f}",
            "rsi": f"{rsi:.2f}",
            "atr": f"{atr:.5f}",
            "lot": lot_onerisi if is_forex else "N/A"
        }
    except:
        return None

def build_report_string(data):
    if not data:
        return ""
    report = (
        f"📈 **Sembol:** {data['ticker']} ({data['name']})\n"
        f"Mevcut Fiyat: {data['price']}\n"
        f"🎯 Giriş Bölgesi: {data['entry']}\n"
        f"📢 **SİNYAL:** {data['signal']}\n"
        f"🛑 **SL:** {data['sl']} | 🎯 **TP:** {data['tp']}\n"
        f"📊 RSI: {data['rsi']} | ATR: {data['atr']}\n"
    )
    if data['lot'] != "N/A":
        report += f"💰 **Önerilen Pozisyon (1k$ / %1.5 Risk):** {data['lot']}\n"
    report += "----------------------------------------\n"
    return report

# 4. TELEGRAM İŞLEYİCİLERİ
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [['📊 Günlük Analiz', '🕒 Sinyalleri Yeniden Başlat']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "👋 Finans Analiz Ajanı Aktif!\n\n"
        "Bot 15 dakikalık periyotlarla arka planda tarama yapıyor. [STRONGBUY] veya [STRONGSELL] durumlarında buraya bilgi düşecektir.",
        reply_markup=reply_markup
    )

async def send_daily_analysis(context: ContextTypes.DEFAULT_TYPE):
    full_report = "🌅 **SABAH PİYASA ÖZETİ RAPORU (06:45)** 🌅\n\n"
    for ticker in POPULAR_MARKETS.keys():
        data = analyze_market_safe(ticker)
        if data and data != "LOW_LIQUIDITY":
            full_report += build_report_string(data) + "\n"
    await context.bot.send_message(chat_id=MY_CHAT_ID, text=full_report, parse_mode="Markdown")

async def scan_market_15min(context: ContextTypes.DEFAULT_TYPE):
    alert_report = ""
    # Arka planda taramayı hafifletmek için en kritik 5 varlığı seçiyoruz
    for ticker in ["EURUSD=X", "GBPUSD=X", "GC=F", "BTC-USD", "USDTRY=X"]:
        data = analyze_market_safe(ticker)
        if data and data != "LOW_LIQUIDITY":
            if data['signal'] in ["[STRONGBUY]", "[STRONGSELL]"]:
                alert_report += "🚨 **GÜÇLÜ SİNYAL YAKALANDI** 🚨\n" + build_report_string(data) + "\n"
        
    if alert_report:
        await context.bot.send_message(chat_id=MY_CHAT_ID, text=alert_report, parse_mode="Markdown")

async def manual_analysis_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == '📊 Günlük Analiz':
        msg = await update.message.reply_text("🔄 Pariteler taranıyor, lütfen bekleyin...")
        
        full_report = "📊 **ANLIK PİYASA ANALİZ RAPORU** 📊\n\n"
        # Aşırı yüklenmeyi önlemek için eş zamanlı tarama sayısını sınırladık
        for ticker in list(POPULAR_MARKETS.keys())[:6]: 
            data = analyze_market_safe(ticker)
            if data == "LOW_LIQUIDITY":
                full_report += f"⚠️ {ticker}: Düşük likidite dönemi.\n\n"
            elif data:
                full_report += build_report_string(data) + "\n"
        
        await context.bot.send_message(chat_id=MY_CHAT_ID, text=full_report, parse_mode="Markdown")
        await context.bot.delete_message(chat_id=MY_CHAT_ID, message_id=msg.message_id)

async def post_init(application: Application) -> None:
    job_queue = application.job_queue
    job_queue.run_repeating(scan_market_15min, interval=900, first=10, name="otomatik_15dk_tarama")
    target_time = datetime.strptime("06:45", "%H:%M").time()
    job_queue.run_daily(send_daily_analysis, time=target_time, name="sabah_ozeti_0645")

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    application = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Text(['📊 Günlük Analiz']), manual_analysis_trigger))
    application.add_handler(MessageHandler(filters.Text(['🕒 Sinyalleri Yeniden Başlat']), start))
    application.run_polling()

if __name__ == '__main__':
    main()
