import logging
import yfinance as yf
import pandas as pd
import ta
import os
import asyncio
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
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

# EN YENİ VE GÜVENLİ TOKEN BİLGİNİZ
TELEGRAM_TOKEN = "8714335607:AAGm1tEntd9ZFUabMDYx87lDiUZy9NfHK_A"
MY_CHAT_ID = 965495144

POPULAR_MARKETS = {
    "EURUSD=X": "EUR-USD Forex",
    "GBPUSD=X": "GBP-USD Forex",
    "USDCHF=X": "USD-CHF Forex",
    "USDJPY=X": "USD-JPY Forex",
    "USDTRY=X": "USD-TRY Forex",
    "GC=F": "Altin ONS",
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum"
}

def analyze_market_sync(ticker, timeframe='1d'):
    try:
        asset = yf.Ticker(ticker)
        df = asset.history(period='3mo', interval='1d')
        if df.empty or len(df) < 15:
            return f"❌ {ticker}: Veri alinamadi.\n"
            
        df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
        df['MACD'] = ta.trend.macd(df['Close'])
        df['MACD_Signal'] = ta.trend.macd_signal(df['Close'])
        df['ATR'] = ta.volatility.average_true_range(df['High'], df['Low'], df['Close'], window=14)
        
        current_price = df['Close'].iloc[-1]
        rsi = df['RSI'].iloc[-1] if not pd.isna(df['RSI'].iloc[-1]) else 50.0
        macd = df['MACD'].iloc[-1] if not pd.isna(df['MACD'].iloc[-1]) else 0.0
        macd_sig = df['MACD_Signal'].iloc[-1] if not pd.isna(df['MACD_Signal'].iloc[-1]) else 0.0
        atr = df['ATR'].iloc[-1] if not pd.isna(df['ATR'].iloc[-1]) else (current_price * 0.002)
        
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
        
        entry_low = current_price * 0.9995
        entry_high = current_price * 1.0005
        
        demo_bakiye = 1000.0
        risk_tutari = demo_bakiye * 0.015
        
        if "BUY" in signal:
            sl = current_price - (atr * 1.5)
            tp = current_price + (atr * 3.0)
        elif "SELL" in signal:
            sl = current_price + (atr * 1.5)
            tp = current_price - (atr * 3.0)
        else:
            sl = current_price * 0.995
            tp = current_price * 1.005
            
        pips_at_risk = abs(current_price - sl)
        lot_onerisi = "0.01 Lot"
        if pips_at_risk > 0:
            if ticker.endswith("=X"):
                lot_onerisi = f"{max(0.01, round(risk_tutari / (pips_at_risk * 100000), 2))} Lot"
            elif ticker == "GC=F":
                lot_onerisi = f"{max(0.01, round(risk_tutari / (pips_at_risk * 100), 2))} Lot"

        report = (
            f"Sembol: {ticker.replace('=X', '')} ({POPULAR_MARKETS[ticker]})\n"
            f"Mevcut Fiyat: {current_price:.4f}\n"
            f"Giris Bolgesi: {entry_low:.4f} - {entry_high:.4f}\n"
            f"SINYAL: {signal}\n"
            f"SL: {sl:.4f} | TP: {tp:.4f}\n"
            f"RSI: {rsi:.2f}\n"
        )
        if ticker.endswith("=X") or ticker == "GC=F":
            report += f"Onerilen Pozisyon (1k$ / %1.5 Risk): {lot_onerisi}\n"
            
        report += f"----------------------------------------"
        return report
    except:
        return f"❌ {ticker}: Analiz sirasinda hata olustu.\n"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [['📊 Günlük Analiz', '🕒 Sinyalleri Yeniden Başlat']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "Finans Analiz Ajani Aktif!\n\nAşağıdaki butonları kullanarak piyasa analizlerini anlık alabilirsiniz.",
        reply_markup=reply_markup
    )

async def send_daily_analysis(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.context if context.job else MY_CHAT_ID
    full_report = "PIYASA ANALIZ RAPORU\n\n"
    for ticker in POPULAR_MARKETS.keys():
        report = analyze_market_sync(ticker, timeframe='1d')
        full_report += report + "\n\n"
        await asyncio.sleep(1)
    await context.bot.send_message(chat_id=chat_id, text=full_report)

async def manual_analysis_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Kilitlenmeyi önlemek için doğrudan asenkron fonksiyonu çağırıyoruz, job_queue bağımlılığı kaldırıldı
    await context.bot.send_message(chat_id=update.effective_chat.id, text="🔄 Analiz hazırlanıyor, lütfen bekleyin...")
    await send_daily_analysis(context)

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Kilitlenmeleri tamamen önleyen kararlı yapı
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Text(['📊 Günlük Analiz']), manual_analysis_trigger))
    application.add_handler(MessageHandler(filters.Text(['🕒 Sinyalleri Yeniden Başlat']), start))

    application.run_polling()

if __name__ == '__main__':
    main()
