import logging
import yfinance as yf
import pandas as pd
import ta
import os
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from flask import Flask
import threading

# Loglama ayarı
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.WARNING)

# --- SÜREKLİ AKTİF KALMASI İÇİN SANAL WEB SUNUCUSU (FLASK) ---
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Finans Ajani Calisiyor!"

def run_flask():
    # Render'ın ücretsiz sunucusunun istediği port ayarı
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port)

# --- FİNANS AJANI KODLARI ---
TELEGRAM_TOKEN = "8714335607:AAGt-nPJUsPPIGGmVeQzEnJi3mIbVNMluc0"
MY_CHAT_ID = 965495144 

POPULAR_MARKETS = {
    "THYAO.IS": "Turk Hava Yollari",
    "AAPL": "Apple Stock",
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum",
    "EURUSD=X": "EUR/USD Forex",
    "USDTRY=X": "USD/TRY Forex"
}

def analyze_market(ticker, timeframe='1d'):
    try:
        asset = yf.Ticker(ticker)
        df = asset.history(period='3mo', interval=timeframe)
        if df.empty or len(df) < 15:
            return f"❌ Veri alinamadi: {ticker}\n"
        
        df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
        df['MACD'] = ta.trend.macd(df['Close'])
        df['MACD_Signal'] = ta.trend.macd_signal(df['Close'])
        
        current_price = df['Close'].iloc[-1]
        rsi = df['RSI'].iloc[-1] if not pd.isna(df['RSI'].iloc[-1]) else 50.0
        macd = df['MACD'].iloc[-1] if not pd.isna(df['MACD'].iloc[-1]) else 0.0
        macd_sig = df['MACD_Signal'].iloc[-1] if not pd.isna(df['MACD_Signal'].iloc[-1]) else 0.0
        
        score = 0
        if rsi < 30: score += 1
        elif rsi > 70: score -= 1
        if macd > macd_sig: score += 1
        else: score -= 1
        
        if score >= 2: signal = "🟢 STRONG BUY"
        elif score == 1: signal = "🌱 BUY"
        elif score == -1: signal = "🚨 SELL"
        elif score <= -2: signal = "🔴 STRONG SELL"
        else: signal = "🟡 NEUTRAL"
        
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
            f"📈 **Symbol:** {ticker} ({POPULAR_MARKETS[ticker]})\n"
            f"⏱ **Zaman Dilimi:** {tf_labels[timeframe]}\n"
            f"💰 **Fiyat:** {current_price:.4f}\n"
            f"📢 **SINYAL:** {signal}\n"
            f"🛑 **SL:** {sl:.4f} | 🎯 **TP:** {tp:.4f}\n"
            f"📊 **RSI:** {rsi:.2f}\n"
            f"----------------------------------------\n"
        )
        return report
    except Exception as e:
        return f"❌ Hata {ticker}: {str(e)}\n"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [['/analiz_gunluk', '/analiz_haftalik'], ['/analiz_aylik', '/guncelle']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("👋 HaPeFin Finans Ajanina Hos Geldiniz!\n\nLütfen analiz periyodunu seçin:", reply_markup=reply_markup)

async def send_bulk_report(application, target_chat_id, timeframe='1d'):
    tf_labels = {'1d': 'GÜNLÜK', '1wk': 'HAFTALIK', '1mo': 'AYLIK'}
    master_report = f"📊 **PİYASA {tf_labels[timeframe]} RAPORU**\n📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
    for ticker in POPULAR_MARKETS.keys():
        master_report += analyze_market(ticker, timeframe)
    await application.bot.send_message(chat_id=target_chat_id, text=master_report, parse_mode="Markdown")

async def scheduled_morning_report(application):
    await send_bulk_report(application, MY_CHAT_ID, '1d')

async def handle_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_chat_id = update.message.chat_id
    
    status_msg = await update.message.reply_text("🔄 Yapay zeka verileri analiz ediyor, lütfen bekleyin...")
    
    if text == '/analiz_gunluk' or text == '/guncelle':
        await send_bulk_report(context.application, user_chat_id, '1d')
    elif text == '/analiz_haftalik':
        await send_bulk_report(context.application, user_chat_id, '1wk')
    elif text == '/analiz_aylik':
        await send_bulk_report(context.application, user_chat_id, '1mo')
        
    try:
        await status_msg.delete()
    except:
        pass

async def post_init(application: Application):
    scheduler = AsyncIOScheduler(timezone="Europe/Istanbul")
    scheduler.add_job(scheduled_morning_report, 'cron', hour=9, minute=0, args=[application])
    scheduler.start()

def main():
    # Sanal web sunucusunu ayri bir kanalda baslatıyoruz (Render uyumu icin)
    threading.Thread(target=run_flask, daemon=True).start()
    
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_commands))
    
    print("🤖 Finans Ajani Basariyla Aktif Edildi!")
    app.run_polling()

if __name__ == '__main__':
    main()
