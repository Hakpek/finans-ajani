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

# 📦 YENİ ENSTRÜMANLAR LİSTEYE EKLENDİ
POPULAR_MARKETS = {
    "THYAO.IS": "Turk Hava Yollari",
    "EREGL.IS": "Eregli Demir Celik",
    "ASELS.IS": "Aselsan",
    "XU100.IS": "BIST 100 Endeksi",
    "AAPL": "Apple Stock",
    "NVDA": "Nvidia Stock",
    "^GSPC": "S&P 500 Endeksi",
    "GC=F": "Altin ONS (Gold)",
    "SI=F": "Gumus ONS (Silver)",       # Yeni Eklendi
    "BZ=F": "Brent Petrol (Oil)",       # Yeni Eklendi
    "^NDX": "Nasdaq 100 Endeksi",       # Yeni Eklendi
    "EURUSD=X": "EUR/USD Forex",
    "USDTRY=X": "USD/TRY Forex",
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum",
    "SOL-USD": "Solana"
}

# 🧮 DETAYLI LOT VE KONTRAK YAPILANDIRMASI (1:100 Kaldıraç Baz Alınmıştır)
FOREX_CONFIG = {
    "EURUSD=X": {"pip_size": 0.0001, "spread_pips": 1.5, "is_forex": True, "contract_size": 100000, "type": "fx"},
    "USDTRY=X": {"pip_size": 0.0001, "spread_pips": 20.0, "is_forex": True, "contract_size": 100000, "type": "fx"},
    "GC=F": {"pip_size": 0.10, "spread_pips": 3.5, "is_forex": True, "contract_size": 100, "type": "commodity"},
    "SI=F": {"pip_size": 0.01, "spread_pips": 2.5, "is_forex": True, "contract_size": 5000, "type": "commodity"},
    "BZ=F": {"pip_size": 0.01, "spread_pips": 3.0, "is_forex": True, "contract_size": 1000, "type": "commodity"},
    "^NDX": {"pip_size": 1.00, "spread_pips": 1.5, "is_forex": True, "contract_size": 10, "type": "index"}
}

def analyze_market_sync(ticker, timeframe='1d'):
    try:
        asset = yf.Ticker(ticker)
        df = asset.history(period='3mo', interval='1d')
        
        if df.empty or len(df) < 15:
            return f"❌ {ticker} ({POPULAR_MARKETS[ticker]}): Veri alinamadi.\n"
        
        # İndikatör Hesaplamaları
        df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
        df['MACD'] = ta.trend.macd(df['Close'])
        df['MACD_Signal'] = ta.trend.macd_signal(df['Close'])
        df['ATR'] = ta.volatility.average_true_range(df['High'], df['Low'], df['Close'], window=14)
        
        current_price = df['Close'].iloc[-1]
        rsi = df['RSI'].iloc[-1] if not pd.isna(df['RSI'].iloc[-1]) else 50.0
        macd = df['MACD'].iloc[-1] if not pd.isna(df['MACD'].iloc[-1]) else 0.0
        macd_sig = df['MACD_Signal'].iloc[-1] if not pd.isna(df['MACD_Signal'].iloc[-1]) else 0.0
        atr = df['ATR'].iloc[-1] if not pd.isna(df['ATR'].iloc[-1]) else (current_price * 0.005)
        
        # Sinyal Mantığı
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
        
        config = FOREX_CONFIG.get(ticker, {"pip_size": 0.01, "spread_pips": 0, "is_forex": False})
        
        if config["is_forex"]:
            pip_size = config["pip_size"]
            atr_pips = atr / pip_size
            sl_pips = max(atr_pips * 2.0, 15.0)
            tp_pips = sl_pips * 1.5
            
            if "BUY" in signal:
                sl = current_price - (sl_pips * pip_size)
                tp = current_price + (tp_pips * pip_size)
                mt_type = "Piyasa Fiyatından AL (Market Buy)"
            elif "SELL" in signal:
                sl = current_price + (sl_pips * pip_size)
                tp = current_price - (tp_pips * pip_size)
                mt_type = "Piyasa Fiyatından SAT (Market Sell)"
            else:
                sl = current_price - (atr * 1.5)
                tp = current_price + (atr * 1.5)
                sl_pips = (current_price - sl) / pip_size
                mt_type = "İŞLEM YAPMAYIN (Beklemede kalın)"
                
            # Dinamik Lot (Hacim) Seçimi
            account_balance = 10000.0
            risk_amount = account_balance * 0.01
            try:
                # Varlık tipine göre lot büyüklüğü normalizasyonu
                if config["type"] == "fx":
                    calculated_lot = risk_amount / (sl_pips * 10.0)
                elif config["type"] == "commodity":
                    calculated_lot = risk_amount / (sl_pips * config["contract_size"] * pip_size)
                else: # Endeksler
                    calculated_lot = risk_amount / (sl_pips * config["contract_size"])
                
                calculated_lot = max(min(calculated_lot, 5.0), 0.01)
            except:
                calculated_lot = 0.01
                
            # 🧮 GERÇEKÇİ LOT MALİYETİ (MARGIN) HESAPLAMA Formülü (Kaldıraç 1:100)
            leverage = 100
            contract_size = config["contract_size"]
            
            if config["type"] == "fx":
                # Forex'te marjin baz döviz cinsindendir (örn: EURUSD için EUR)
                margin_cost = (contract_size * calculated_lot) / leverage
                margin_text = f"💰 Bu İşlemin Lot Maliyeti (Gerekli Teminat): ~{margin_cost:.2f} USD\n"
            else:
                # Emtia ve Endekslerde marjin fiyata endekslidir
                margin_cost = (contract_size * calculated_lot * current_price) / leverage
                margin_text = f"💰 Bu İşlemin Lot Maliyeti (Gerekli Teminat): ~{margin_cost:.2f} USD\n"
                
            clean_ticker = ticker.replace("=X", "").replace("=F", "").replace("^", "")
            mt_guide = (
                f"🛠 METATRADER ADIM ADIM İŞLEM REHBERİ:\n"
                f"1. Parite Seçimi: MetaTrader'da '{clean_ticker}' bulun ve 'Yeni Emir' açın.\n"
                f"2. Emir Tipi: 'Piyasa Emri' (Market Execution) seçin.\n"
                f"3. Hacim (Lot): Ekrana tam olarak '{calculated_lot:.2f}' yazın.\n"
                f"4. Zarar Durdur (SL): Ekrana tam olarak '{sl:.4f}' yazın.\n"
                f"5. Kâr Al (TP): Ekrana tam olarak '{tp:.4f}' yazın.\n"
                f"6. Son Adım: Ekranda '{mt_type}' butonuna basın."
            )
            
            sl_tp_text = f"🛑 SL (Zarar Durdur): {sl:.4f}\n🎯 TP (Kâr Al): {tp:.4f}\n"
            lot_text = f"⚙️ Önerilen Hacim: {calculated_lot:.2f} Lot\n" + margin_text
        else:
            lot_text = ""
            mt_guide = ""
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
            f"📢 SİNYAL: {signal}\n"
            f"💵 Giriş Fiyatı (Mevcut): {current_price:.4f}\n"
            + sl_tp_text + lot_text +
            f"📊 RSI Değeri: {rsi:.2f}\n"
            f"----------------------------------------\n"
            + mt_guide
        )
        return report
    except Exception as e:
        return f"❌ {ticker} ({POPULAR_MARKETS[ticker]}): Analiz sırasında hata oluştu. ({str(e)})\n"

def get_main_keyboard():
    keyboard = [
        ['📊 Günlük Analiz', '📈 Haftalık Analiz'],
        ['📉 Aylık Analiz', '🔄 Sistemi Güncelle']
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_markup = get_main_keyboard()
    await update.message.reply_text(
        "🤖 HaPeFin Finans Ajanına Hoş Geldiniz!\n\nYeni enstrümanlar (Petrol, Gümüş, Nasdaq) ve Gelişmiş Lot Hesaplama Modülü aktif edildi.", 
        reply_markup=reply_markup
    )

async def send_bulk_report(application, target_chat_id, timeframe='1d'):
    tf_labels = {'1d': 'GUNLUK', '1wk': 'HAFTALIK', '1mo': 'AYLIK'}
    reply_markup = get_main_keyboard()
    await application.bot.send_message(chat_id=target_chat_id, text=f"📊 HaPeFin {tf_labels[timeframe]} PİYASA RAPORU BAŞLADI...\n========================", reply_markup=reply_markup)
    
    loop = asyncio.get_event_loop()
    for ticker in POPULAR_MARKETS.keys():
        report_part = await loop.run_in_executor(None, analyze_market_sync, ticker, timeframe)
        await application.bot.send_message(chat_id=target_chat_id, text=report_part, reply_markup=reply_markup)
        await asyncio.sleep(0.5)

async def scheduled_morning_report(application):
    await send_bulk_report(application, MY_CHAT_ID, '1d')

async def handle_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text in ['/analiz_gunluk', 'analiz_gunluk', '/guncelle', 'guncelle', '📊 Günlük Analiz', '🔄 Sistemi Güncelle']:
        await send_bulk_report(context.application, MY_CHAT_ID, '1d')
    elif text in ['/analiz_haftalik', 'analiz_haftalik', '📈 Haftalık Analiz']:
        await send_bulk_report(context.application, MY_CHAT_ID, '1wk')
    elif text in ['/analiz_aylik', 'analiz_aylik', '📉 Aylık Analiz']:
        await send_bulk_report(context.application, MY_CHAT_ID, '1mo')async def post_init(application: Application):scheduler = AsyncIOScheduler(timezone="Europe/Istanbul")scheduler.add_job(scheduled_morning_report, 'cron', hour=9, minute=0, args=[application])scheduler.start()def main():threading.Thread(target=run_flask, daemon=True).start()app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()app.add_handler(CommandHandler("start", start))app.add_handler(MessageHandler(filters.TEXT | filters.COMMAND, handle_commands))print("🤖 Finans Ajani Basariyla Aktif Edildi!")app.run_polling()if name == 'main':main()

