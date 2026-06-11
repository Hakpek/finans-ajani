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
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from flask import Flask
import threading

# 1. LOGLAMA VE FLASK YAPILANDIRMASI (Render'ın açık kalması için)
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

# 3. YENİ FOREX VE 1000$ BAKIYE UYUMLU TEKNİK ANALİZ FONKSİYONU
def analyze_market_sync(ticker, timeframe='1d'):
    try:
        asset = yf.Ticker(ticker)
        df = asset.history(period='3mo', interval='1d')
        
        if df.empty or len(df) < 20:
            return f"❌ {ticker} ({POPULAR_MARKETS[ticker]}): Yetersiz veri.\n"
        
        # İndikatörler
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
        
        # Seans / Likidite Filtresi (Forex için)
        if is_forex:
            tz_turkey = pytz.timezone('Europe/Istanbul')
            now_turkey = datetime.now(tz_turkey)
            current_hour = now_turkey.hour
            if 0 <= current_hour < 8:
                return f"⚠️ {ticker}: Düşük likidite/Yüksek spread dönemi (Asya Seansı). Sinyal üretilmedi.\n"

        # Sinyal Skorlama
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
        
        # Spread ve Giriş Bölgesi
        spread_buffer = atr * 0.1
        entry_low = current_price - spread_buffer
        entry_high = current_price + spread_buffer
        
        # 1000$ Risk Yönetimi Hesaplamaları
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
            
        # Dinamik Lot Önerisi
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
        
        report = (
            f"📈 **Sembol:** {ticker} ({POPULAR_MARKETS[ticker]})\n"
            f"Periyot: {tf_labels.get(timeframe, 'GUNLUK')}\n"
            f"Mevcut Fiyat: {current_price:.5f}\n"
            f"🎯 Güvenli Giriş Bölgesi: {entry_low:.5f} - {entry_high:.5f}\n"
            f"📢 **SİNYAL:** {signal}\n"
            f"🛑 **SL (Stop):** {sl:.5f} | 🎯 **TP (Kar):** {tp:.5f}\n"
            f"📊 RSI: {rsi:.2f} | ATR (Volatilite): {atr:.5f}\n"
        )
        
        if is_forex and lot_onerisi != "N/A":
            report += f"💰 **Önerilen Pozisyon (1k$ Bakiye / %1.5 Risk):** {lot_onerisi}\n"
            
        report += f"----------------------------------------"
        return report
    except Exception as e:
        return f"❌ {ticker} ({POPULAR_MARKETS[ticker]}): Analiz sirasinda hata olustu.\n"

# 4. TELEGRAM BOT KOMUTLARI VE ARAYÜZ (Geri Getirilen Eski Özellikler)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Kullanıcıya kolaylık sağlayan alt klavye butonları
    keyboard = [['📊 Günlük Analiz', '🕒 Otomatik Sinyal Aç']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "👋 Finans Analiz Ajanına Hoş Geldiniz!\n\n"
        "Aşağıdaki butonları kullanarak piyasa analizlerini anlık alabilir veya otomatik takibi başlatabilirsiniz.",
        reply_markup=reply_markup
    )

async def send_daily_analysis(context: ContextTypes.DEFAULT_TYPE):
    # Hem otomatik zamanlayıcının hem de butonun kullandığı ortak analiz gönderici
    chat_id = context.job.context if context.job else MY_CHAT_ID
    await context.bot.send_message(chat_id=chat_id, text="🔄 Piyasalar taranıyor, lütfen bekleyin...")
    
    full_report = "📊 **GÜNLÜK PİYASA ANALİZ RAPORU** 📊\n\n"
    for ticker in POPULAR_MARKETS.keys():
        report = analyze_market_sync(ticker, timeframe='1d')
        full_report += report + "\n\n"
        await asyncio.sleep(1) # Yahoo Finance engelini önlemek için kısa bekleme
        
    await context.bot.send_message(chat_id=chat_id, text=full_report, parse_mode="Markdown")

async def manual_analysis_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Butona basıldığında tetiklenen fonksiyon
    if update.message.text == '📊 Günlük Analiz':
        # Arka planda çalışması için job yapısına paslıyoruz
        context.job_queue.run_once(send_daily_analysis, when=0, context=update.effective_chat.id)

async def set_auto_signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Her gün belirli saatte otomatik çalışması için Scheduler ayarı
    chat_id = update.effective_chat.id
    
    # Mevcut kuyrukta aynı iş varsa temizle
    current_jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    for job in current_jobs:
        job.schedule_removal()
        
    # Her gün sabah 09:00'da (TSİ) rapor gönderecek şekilde ayarla
    # Render üzerinde sunucu saati UTC olabileceği için zamanlamayı kontrol edin
    context.job_queue.run_daily(
        send_daily_analysis, 
        time=datetime.strptime("09:00", "%H:%M").time(), 
        context=chat_id, 
        name=str(chat_id)
    )
    await update.message.reply_text("🔔 Otomatik sinyaller başarıyla açıldı! Her gün TSİ 09:00'da rapor iletilecek.")

# 5. ANA ÇALIŞTIRICI (MAIN)
def main():
    # Flask sunucusunu ayrı bir thread (iş parçacığı) olarak başlatıyoruz
    threading.Thread(target=run_flask, daemon=True).start()

    # Telegram botunu ayağa kaldırıyoruz
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Komut ve mesaj yönlendiricileri
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("otomatik_ac", set_auto_signals))
    application.add_handler(MessageHandler(filters.Text(['📊 Günlük Analiz']), manual_analysis_trigger))
    application.add_handler(MessageHandler(filters.Text(['🕒 Otomatik Sinyal Aç']), set_auto_signals))

    # Botu başlat
    application.run_polling()

if __name__ == '__main__':
    main()
