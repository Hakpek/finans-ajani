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

# API Token ve Chat ID korundu
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

# Forex pariteleri ve Altın için özel piyasa yapılandırması (Spread ve Pip çarpanları)
FOREX_CONFIG = {
    "EURUSD=X": {"pip_size": 0.0001, "spread_pips": 1.5, "is_forex": True},
    "USDTRY=X": {"pip_size": 0.0001, "spread_pips": 20.0, "is_forex": True},
    "GC=F": {"pip_size": 0.10, "spread_pips": 3.5, "is_forex": True} # Altın ons bazlı
}

def analyze_market_sync(ticker, timeframe='1d'):
    try:
        asset = yf.Ticker(ticker)
        # ATR hesaplaması için daha geniş veri çekiyoruz
        df = asset.history(period='3mo', interval='1d')
        
        if df.empty or len(df) < 15:
            return f"❌ {ticker} ({POPULAR_MARKETS[ticker]}): Veri alinamadi.\n"
        
        # Temel İndikatörler
        df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
        df['MACD'] = ta.trend.macd(df['Close'])
        df['MACD_Signal'] = ta.trend.macd_signal(df['Close'])
        
        # Forex için volatilite ölçer (ATR) entegrasyonu
        df['ATR'] = ta.volatility.average_true_range(df['High'], df['Low'], df['Close'], window=14)
        
        current_price = df['Close'].iloc[-1]
        rsi = df['RSI'].iloc[-1] if not pd.isna(df['RSI'].iloc[-1]) else 50.0
        macd = df['MACD'].iloc[-1] if not pd.isna(df['MACD'].iloc[-1]) else 0.0
        macd_sig = df['MACD_Signal'].iloc[-1] if not pd.isna(df['MACD_Signal'].iloc[-1]) else 0.0
        atr = df['ATR'].iloc[-1] if not pd.isna(df['ATR'].iloc[-1]) else (current_price * 0.005)
        
        # Sinyal Skoru Üretimi
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
        
        # Pazar türüne göre dinamik SL/TP ve Risk Yönetimi Hesaplama
        config = FOREX_CONFIG.get(ticker, {"pip_size": 0.01, "spread_pips": 0, "is_forex": False})
        
        if config["is_forex"]:
            pip_size = config["pip_size"]
            spread_distance = config["spread_pips"] * pip_size
            
            # Dinamik ATR tabanlı Forex SL ve TP (2x ATR Stop, 3x ATR Kâr Al)
            atr_pips = atr / pip_size
            sl_pips = max(atr_pips * 2.0, 15.0)  # Minimum 15 pip stop koruması
            tp_pips = sl_pips * 1.5              # Risk Ödül Oranı: 1.5
            
            if "BUY" in signal:
                entry_low = current_price
                entry_high = current_price + spread_distance
                sl = current_price - (sl_pips * pip_size)
                tp = current_price + (tp_pips * pip_size)
            elif "SELL" in signal:
                entry_low = current_price - spread_distance
                entry_high = current_price
                sl = current_price + (sl_pips * pip_size)
                tp = current_price - (tp_pips * pip_size)
            else:
                entry_low = current_price * 0.999
                entry_high = current_price * 1.001
                sl = current_price - (atr * 1.5)
                tp = current_price + (atr * 1.5)
                sl_pips = (current_price - sl) / pip_size
                
            # Dinamik Forex Lot Hesaplama (Demo Hesap Yönetimi)
            # Varsayılan: 10,000$ Bakiye, İşlem başına %1 risk (100$)
            account_balance = 10000.0
            risk_amount = account_balance * 0.01
            # Standart 1 Lot Forex sözleşmesi = 100,000 birim. 1 Pip maliyeti yaklaşık 10$'dır (USD bazlı çaprazlar için)
            # Genel lot formülü: Risk / (SL Pips * Pip Başına Maliyet)
            try:
                calculated_lot = risk_amount / (sl_pips * 10.0)
                # Sınırlandırma (Min: 0.01 mikro lot, Max: 5.0 standart lot)
                calculated_lot = max(min(calculated_lot, 5.0), 0.01)
                lot_text = f"⚙️ Önerilen Risk: {calculated_lot:.2f} Lot (10K$ Bakiye / %1 Risk İçin)\n"
            except:
                lot_text = "⚙️ Önerilen Risk: 0.10 Lot\n"
                
            sl_tp_text = f"🛑 SL: {sl:.4f} ({sl_pips:.1f} Pip) | 🎯 TP: {tp:.4f} ({tp_pips:.1f} Pip)\n"
        else:
            # Kripto ve Hisse senetleri (BIST/US) için yüzdelik koruma mantığı devam ediyor
            entry_low = current_price * 0.997
            entry_high = current_price * 1.003
            lot_text = ""
            if "BUY" in signal:
                sl = current_price * 0.95
                tp = current_price * 1.10
            elif "SELL" in signal:
                sl = current_price * 1.05
                tp = current_price * 0.90
            else:
                sl = current_price * 0.97
                tp = current_price * 1.03
            sl_tp_text = f"🛑 SL: {sl:.2f} | 🎯 TP: {tp:.2f}\n"

        tf_labels = {'1d': 'GUNLUK', '1wk': 'HAFTALIK', '1mo': 'AYLIK'}
        report = (
            f"📈 Sembol: {ticker} ({POPULAR_MARKETS[ticker]})\n"
            f"Periyot: {tf_labels.get(timeframe, 'GUNLUK')}\n"
            f"Mevcut Fiyat: {current_price:.4f}\n"
            f"🎯 Önerilen Giriş Bölgesi: {entry_low:.4f} - {entry_high:.4f}\n"
            f"📢 SİNYAL: {signal}\n"
            + sl_tp_text + lot_text +
            f"📊 RSI: {rsi:.2f}\n"
            f"----------------------------------------"
        )
        return report
    except Exception as e:
        return f"❌ {ticker} ({POPULAR_MARKETS[ticker]}): Analiz sırasında hata oluştu. ({str(e)})\n"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [['/analiz_gunluk', '/analiz_haftalik'], ['/analiz_aylik', '/guncelle']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("HaPeFin Gelişmiş Finans Ajanına Hoş Geldiniz! İstediğiniz periyodu seçin:", reply_markup=reply_markup)

async def send_bulk_report(application, target_chat_id, timeframe='1d'):
    tf_labels = {'1d': 'GUNLUK', '1wk': 'HAFTALIK', '1mo': 'AYLIK'}
    await application.bot.send_message(chat_id=target_chat_id, text=f"📊 HaPeFin {tf_labels[timeframe]} PİYASA RAPORU BAŞLADI...\n========================")
    
    loop = asyncio.get_event_loop()
    for ticker in POPULAR_MARKETS.keys():
        report_part = await loop.run_in_executor(None, analyze_market_sync, ticker, timeframe)
        await application.bot.send_message(chat_id=target_chat_id, text=report_part)
        await asyncio.sleep(0.5)

async def scheduled_morning_report(application):
    await send_bulk_report(application, MY_CHAT_ID, '1d')

async def handle_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text in ['/analiz_gunluk', 'analiz_gunluk', '/guncelle', 'guncelle']:
        await send_bulk_report(context.application, MY_CHAT_ID, '1d')
    elif text in ['/analiz_haftalik', 'analiz_haftalik']:
        await send_bulk_report(context.application, MY_CHAT_ID, '1wk')
    elif text in ['/analiz_aylik', 'analiz_aylik']:
        await send_bulk_report(context.application, MY_CHAT_ID, '1mo')

async def post_init(application: Application):
    scheduler = AsyncIOScheduler(timezone="Europe/Istanbul")
    scheduler.add_job(scheduled_morning_report, 'cron', hour=9, minute=0, args=[application])
    scheduler.start()

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT | filters.COMMAND, handle_commands))
    
    print("🤖 Finans Ajani Basariyla Aktif Edildi!")
    app.run_polling()

if __name__ == '__main__':
    main()
