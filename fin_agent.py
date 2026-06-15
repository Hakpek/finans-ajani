import logging
import yfinance as yf
import pandas as pd
import ta
import os
import asyncio
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from flask import Flask
import threading

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.WARNING)

flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Finans Ajani Calisiyor!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port)

# 11 HAZİRAN SONRASI GÜVENLİĞE ALDIĞIMIZ YENİ TOKEN BİLGİLERİNİZ
TELEGRAM_TOKEN = "8714335607:AAEXVAqXmIdKWF1BD9R3aLWoFzkv4A3y_pc"
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

def analyze_market_sync(ticker, timeframe='1d'):
    try:
        asset = yf.Ticker(ticker)
        df = asset.history(period='3mo', interval='1d')
        if df.empty or len(df) < 15:
            return f"❌ {ticker} ({POPULAR_MARKETS[ticker]}): Veri alinamadi.\n"
            
        df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
        df['MACD'] = ta.trend.macd(df['Close'])
        df['MACD_Signal'] = ta.trend.macd_signal(df['Close'])
        
        current_price = df['Close'].iloc[-1]
        rsi = df['RSI'].iloc[-1] if not pd.isna(df['RSI'].iloc[-1]) else 50.0
        macd = df['MACD'].iloc[-1] if not pd.isna(df['MACD'].iloc[-1]) else 0.0
        macd_sig = df['MACD_Signal'].iloc[-1] if not pd.isna(df['MACD_Signal'].iloc[-1]) else 0.0
        
        score = 0
        if rsi < 30:
            score += 1
        elif rsi > 70:
            score -= 1
            
        if macd > macd_sig:
            score += 1
        else:
            score -= 1
            
        if score >= 2:
            signal = "[STRONGBUY]"
        elif score == 1:
            signal = "[BUY]"
        elif score == -1:
            signal = "[SELL]"
        elif score <= -2:
            signal = "[STRONGSELL]"
        else:
            signal = "[NEUTRAL]"
            
        entry_low = current_price * 0.997
        entry_high = current_price * 1.003
        
        if "BUY" in signal:
            sl = current_price * 0.95
            tp = current_price * 1.10
        elif "SELL" in signal:
            sl = current_price * 1.05
            tp = current_price * 0.90
        else:
            sl = current_price * 0.97
            tp = current_price * 1.03
            
        tf_labels = {'1d': 'GUNLUK', '1wk': 'HAFTALIK', '1mo': 'AYLIK'}
        report = (
            f"📈 Sembol: {ticker} ({POPULAR_MARKETS[ticker]})\n"
            f"Periyot: {tf_labels.get(timeframe, 'GUNLUK')}\n"
            f"Mevcut Fiyat: {current_price:.4f}\n"
            f"🎯 Onerilen Giris Bolgesi: {entry_low:.4f} - {entry_high:.4f}\n"
            f"📢 SINYAL: {signal}\n"
            f"🛑 SL: {sl:.4f} | 🎯 TP: {tp:.4f}\n"
            f"📊 RSI: {rsi:.2f}\n"
            f"----------------------------------------"
        )
        return report
    except:
        return f"❌ {ticker} ({POPULAR_MARKETS[ticker]}): Analiz sirasinda hata olustu.\n"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [['/analiz_gunluk', '/otomatik_ac']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "👋 Finans Analiz Ajanina Hos Geldiniz!\n\n"
        "Sistem 11 Haziran tarihindeki orijinal ve kararli versiyonuna basariyla geri donduruldu.",
        reply_markup=reply_markup
    )

async def send_daily_analysis(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.context if context.job else MY_CHAT_ID
    full_report = "📊 GUNLUK PIYASA ANALIZ RAPORU 📊\n\n"
    for ticker in POPULAR_MARKETS.keys():
        report = analyze_market_sync(ticker, timeframe='1d')
        full_report += report + "\n\n"
        await asyncio.sleep(1)
    await context.bot.send_message(chat_id=chat_id, text=full_report)

async def manual_analysis_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.job_queue.run_once(send_daily_analysis, when=0, context=update.effective_chat.id)

async def set_auto_signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    current_jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    for job in current_jobs:
        job.schedule_removal()
        
    context.job_queue.run_daily(
        send_daily_analysis, 
        time=datetime.strptime("09:00", "%H:%M").time(), 
        context=chat_id, 
        name=str(chat_id)
    )
    await update.message.reply_text("🔔 Otomatik sinyaller acildi! Her gun TSİ 09:00'da rapor iletilecek.")

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("analiz_gunluk", manual_analysis_trigger))
    application.add_handler(CommandHandler("otomatik_ac", set_auto_signals))

    application.run_polling()

if __name__ == '__main__':
    main()
