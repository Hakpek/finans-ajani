import logging
import yfinance as yf
import pandas as pd
import ta
import os
import asyncio
import pytz
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

# 2. AYARLAR VE SABİTLER
TELEGRAM_TOKEN = "8714335607:AAGt-nPJUsPPIGGmVeQzEnJi3mIbVNMluc0"
MY_CHAT_ID = 965495144

POPULAR_MARKETS = {
    "THYAO.IS": "Turk Hava Yollari",
    "EREGL.IS": "Eregli Demir Celik",
    "ASELS.IS": "Aselsan",
    "XU100.IS": "BIST 100 Endeksi",
    "AAPL": "Apple Stock",
    "NVDA": "Nvidia Stock",
    "^GSPC": "S&P 500 Endeksi",
    "GC=F": "Altin ONS (Gold)",
    "EURUSD=X": "EUR/USD Forex",
    "USDTRY=X": "USD/TRY Forex",
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum",
    "SOL-USD": "Solana"
}

# 3. FOREX VE 1000$ BAKIYE UYUMLU TEKNİK ANALİZ FONKSİYONU
def analyze_market_sync(ticker, timeframe='1d'):
    try:
        asset = yf.Ticker(ticker)
        df = asset.history(period='3mo', interval='1d')
        
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
        
        # Seans / Likidite Filtresi (Sadece Forex için)
        if is_forex:
            tz_turkey = pytz.timezone('Europe/Istanbul')
            now_turkey = datetime.now(tz_turkey)
            current_hour = now_turkey.hour
            if 0 <= current_hour < 8:
                # Düşük likiditede sinyali es geçiyoruz
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
        risk_orani = 0.015  # %1.5 risk (15$)
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

        tf_labels = {'1d': 'GUNLUK', '1wk': 'HAFTALIK', '1mo': 'AYLIK'}
        
        return {
            "ticker": ticker,
            "name": POPULAR_MARKETS[ticker],
            "timeframe": tf_labels.get(timeframe, 'GUNLUK'),
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
        f"Periyot: {data['timeframe']}\n"
        f"Mevcut Fiyat: {data['price']}\n"
        f"🎯 Güvenli Giriş Bölgesi: {data['entry']}\n"
        f"📢 **SİNYAL:** {data['signal']}\n"
        f"🛑 **SL (Stop):** {data['sl']} | 🎯 **TP (Kar):** {data['tp']}\n"
        f"📊 RSI: {data['rsi']} | ATR (Volatilite): {data['atr']}\n"
    )
    if data['lot'] != "N/A":
        report += f"💰 **Önerilen Pozisyon (1k$ Bakiye / %1.5 Risk):** {data['lot']}\n"
    report += "----------------------------------------\n"
    return report

# 4. TELEGRAM BOT KOMUTLARI VE ZAMANLAYICILAR
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [['📊 Günlük Analiz', '🕒 Otomatik Sinyal Aç']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "👋 Finans Analiz Ajanı Başlatıldı!\n\n"
        "Bot artık her 15 dakikada bir arka planda piyasaları tarayacak ve [STRONGBUY] / [STRONGSELL] durumlarını size anında iletecektir.",
        reply_markup=reply_markup
    )

async def send_daily_analysis(context: ContextTypes.DEFAULT_TYPE):
    # Sabah 06:45'te çalışan toplu rapor fonksiyonu
    chat_id = context.job.context if context.job else MY_CHAT_ID
    full_report = "🌅 **SABAH PİYASA ÖZETİ RAPORU (06:45)** 🌅\n\n"
    for ticker in POPULAR_MARKETS.keys():
        data = analyze_market_sync(ticker, timeframe='1d')
        if data and data != "LOW_LIQUIDITY":
            full_report += build_report_string(data) + "\n"
        await asyncio.sleep(1)
    await context.bot.send_message(chat_id=chat_id, text=full_report, parse_mode="Markdown")

async def scan_market_15min(context: ContextTypes.DEFAULT_TYPE):
    # HER 15 DAKİKADA BİR ÇALIŞAN GÜÇLÜ SİNYAL AVCISI
    chat_id = context.job.context if context.job else MY_CHAT_ID
    alert_report = ""
    
    for ticker in POPULAR_MARKETS.keys():
        data = analyze_market_sync(ticker, timeframe='1d')
        # Sadece Güçlü Al veya Güçlü Sat sinyali olanları filtrele
        if data and data != "LOW_LIQUIDITY":
            if data['signal'] in ["[STRONGBUY]", "[STRONGSELL]"]:
                alert_report += "🚨 **GÜÇLÜ SİNYAL YAKALANDI** 🚨\n" + build_report_string(data) + "\n"
        await asyncio.sleep(1)
        
    if alert_report:
        await context.bot.send_message(chat_id=chat_id, text=alert_report, parse_mode="Markdown")

async def manual_analysis_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == '📊 Günlük Analiz':
        chat_id = update.effective_chat.id
        await context.bot.send_message(chat_id=chat_id, text="🔄 Anlık veri çekiliyor, lütfen bekleyin...")
        full_report = "📊 **ANLIK PİYASA ANALİZ RAPORU** 📊\n\n"
        for ticker in POPULAR_MARKETS.keys():
            data = analyze_market_sync(ticker, timeframe='1d')
            if data == "LOW_LIQUIDITY":
                full_report += f"⚠️ {ticker}: Düşük likidite dönemi. Sinyal üretilmedi.\n\n"
            elif data:
                full_report += build_report_string(data) + "\n"
            await asyncio.sleep(1)
        await context.bot.send_message(chat_id=chat_id, text=full_report, parse_mode="Markdown")

async def set_auto_signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    current_jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    for job in current_jobs:
        job.schedule_removal()
        
    tz_turkey = pytz.timezone('Europe/Istanbul')
    
    # 1. Görev: Her Sabah 06:45 Genel Raporu (Türkiye saatine duyarlı)
    target_time = datetime.strptime("06:45", "%H:%M").time()
    context.job_queue.run_daily(
        send_daily_analysis, 
        time=target_time, 
        context=chat_id, 
        name=str(chat_id)
    )
    
    # 2. Görev: Her 15 dakikada bir Güçlü Sinyal Kontrolü
    context.job_queue.run_repeating(
        scan_market_15min,
        interval=900,  # 15 dakika = 900 saniye
        first=10,      # Bot açıldıktan 10 saniye sonra ilk taramayı yap
        context=chat_id,
        name=str(chat_id)
    )
    
    await update.message.reply_text(
        "🔔 Otomatik Sinyal Takibi Aktif!\n\n"
        "• Her sabah saat **06:45**'te toplu rapor iletilecek.\n"
        "• **Her 15 dakikada bir** arka planda piyasa taranıp sadece [STRONGBUY] ve [STRONGSELL] durumları anlık bildirilecek."
    )

# 5. ANA ÇALIŞTIRICI (MAIN)
def main():
    threading.Thread(target=run_flask, daemon=True).start()

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("otomatik_ac", set_auto_signals))
    application.add_handler(MessageHandler(filters.Text(['📊 Günlük Analiz']), manual_analysis_trigger))
    application.add_handler(MessageHandler(filters.Text(['🕒 Otomatik Sinyal Aç']), set_auto_signals))

    application.run_polling()

if __name__ == '__main__':
    main()
