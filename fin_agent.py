import logging
import yfinance as yf
import pandas as pd
import ta
import os
import time
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask
import threading

# Sadece kritik uyarıları görelim
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.WARNING)

flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Finans Ajani Calisiyor!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port)

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

def analyze_market_sync(ticker, timeframe='1d'):
    try:
        asset = yf.Ticker(ticker)
        df = asset.history(period='3mo', interval=timeframe)
        
        if df.empty or len(df) < 15:
            return f"❌ {ticker}: Veri alinamadi.\n"
        
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
        
        if score >= 2: signal = "[STRONGBUY]"
        elif score == 1: signal = "[BUY]"
        elif score == -1: signal = "[SELL]"
        elif score <= -2: signal = "[STRONGSELL]"
        else: signal = "[NEUTRAL]"
        
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
            f"Periyot: {tf_labels[timeframe]}\n"
            f"Fiyat: {current_price:.4f}\n"
            f"SINYAL: {signal}\n"
            f"SL: {sl:.4f} | TP: {tp:.4f}\n"
            f"RSI: {rsi:.2f}\n"
            f"----------------------------------------"
        )
        return report
    except:
        return f"❌ {ticker}: Analiz sirasinda hata olustu.\n"

def start(update: Update, context):
    keyboard = [['/analiz_gunluk', '/analiz_haftalik'], ['/analiz_aylik', '/guncelle']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    update.message.reply_text("HaPeFin Gelişmiş Finans Ajanına Hoş Geldiniz! İstediğiniz periyodu seçin:", reply_markup=reply_markup)

def send_bulk_report_sync(bot, target_chat_id, timeframe='1d'):
    tf_labels = {'1d': 'GUNLUK', '1wk': 'HAFTALIK', '1mo': 'AYLIK'}
    bot.send_message(chat_id=target_chat_id, text=f"📊 HaPeFin {tf_labels[timeframe]} PİYASA RAPORU BAŞLADI...\n========================")
    
    for ticker in POPULAR_MARKETS.keys():
        report_part = analyze_market_sync(ticker, timeframe)
        bot.send_message(chat_id=target_chat_id, text=report_part)
        time.sleep(0.5)

def handle_commands(update: Update, context):
    text = update.message.text
    user_chat_id = update.message.chat_id
    bot = context.bot
    
    if text == '/analiz_gunluk' or text == '/guncelle':
        send_bulk_report_sync(bot, user_chat_id, '1d')
    elif text == '/analiz_haftalik':
        send_bulk_report_sync(bot, user_chat_id, '1wk')
    elif text == '/analiz_aylik':
        send_bulk_report_sync(bot, user_chat_id, '1mo')

def scheduled_morning_report():
    # Zamanlayıcı tetiklendiğinde bağımsız bir bot nesnesiyle doğrudan gönderim yapar
    from telegram import Bot
    bot = Bot(token=TELEGRAM_TOKEN)
    send_bulk_report_sync(bot, MY_CHAT_ID, '1d')

def main():
    # Sanal Web Kapısını Başlat
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Senkron Yapılandırıcı (Mevcut kütüphane versiyonunuzla tam uyumludur)
    updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_commands))
    
    # Klasik Senkron Zamanlayıcı (Sabah 09:00 Ayarı)
    scheduler = BackgroundScheduler(timezone="Europe/Istanbul")
    scheduler.add_job(scheduled_morning_report, 'cron', hour=9, minute=0)
    scheduler.start()
    
    print("🤖 Finans Ajani Basariyla Aktif Edildi!")
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
