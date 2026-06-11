import logging
import pandas as pd
import ta
import os
import asyncio
import pytz
import aiohttp
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

# 2. AYARLAR AND BINANCE SPOT PIYASASINDA %100 VAR OLAN PARİTELER
TELEGRAM_TOKEN = "8714335607:AAEXVAqXmIdKWF1BD9R3aLWoFzkv4A3y_pc"
MY_CHAT_ID = 965495144

# Hata riskini sıfırlamak için sadece Binance spotta kesin olan çiftleri seçtik
MARKET_PAIRS = {
    "EURUSDT": "EUR/USD Forex",
    "GBPUSDT": "GBP/USD Forex",
    "BTCUSDT": "Bitcoin",
    "ETHUSDT": "Ethereum",
    "SOLUSDT": "Solana"
}

# 3. KİLİTLENMEYEN ASENKRON VERİ MOTORU
async def fetch_market_data_async(symbol, name=""):
    async with aiohttp.ClientSession() as session:
        try:
            # Doğrudan spot klines hattı
            url = f"https://binance.com{symbol}&interval=1d&limit=30"
            async with session.get(url, timeout=8) as response:
                res = await response.json()
            
            # Hatalı veya boş yanıt kontrolü
            if not res or (isinstance(res, dict) and "code" in res) or not isinstance(res, list):
                return None
                
            df = pd.DataFrame(res, columns=['OpenTime', 'Open', 'High', 'Low', 'Close', 'Volume', 'CloseTime', 'AssetVolume', 'Trades', 'TakerBuyBase', 'TakerBuyQuote', 'Ignore'])
            
            df['Close'] = df['Close'].astype(float)
            df['High'] = df['High'].astype(float)
            df['Low'] = df['Low'].astype(float)
            
            # İndikatör Hesaplamaları
            df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
            df['ATR'] = ta.volatility.average_true_range(df['High'], df['Low'], df['Close'], window=14)
            
            current_price = df['Close'].iloc[-1]
            rsi = df['RSI'].iloc[-1] if not pd.isna(df['RSI'].iloc[-1]) else 50.0
            atr = df['ATR'].iloc[-1] if not pd.isna(df['ATR'].iloc[-1]) else (current_price * 0.002)
            
            # Sinyal Üretimi
            if rsi < 35: signal = "[STRONGBUY]"
            elif rsi < 45: signal = "[BUY]"
            elif rsi > 65: signal = "[STRONGSELL]"
            elif rsi > 55: signal = "[SELL]"
            else: signal = "[NEUTRAL]"
            
            spread_buffer = atr * 0.05
            entry_low = current_price - spread_buffer
            entry_high = current_price + spread_buffer
            
            # 1000$ Bakiye Yönetimi (%1.5 Risk = Maksimum 15$ Zarar)
            demo_bakiye = 1000.0
            risk_tutari = demo_bakiye * 0.015
            
            if "BUY" in signal:
                sl = current_price - (atr * 1.5)
                tp = current_price + (atr * 3.0)
            elif "SELL" in signal:
                sl = current_price + (atr * 1.5)
                tp = current_price - (atr * 3.0)
            else:
                sl = current_price - (atr * 2.0)
                tp = current_price + (atr * 2.0)
                
            pips_at_risk = abs(current_price - sl)
            ideal_lot = 0.01
            if pips_at_risk > 0:
                # 1000$ hesaba uygun mikro-lot ölçekleme formülü
                if "USD" in symbol and symbol != "BTCUSDT" and symbol != "ETHUSDT" and symbol != "SOLUSDT":
                    ideal_lot = max(0.01, round(risk_tutari / (pips_at_risk * 100), 2))
                else:
                    ideal_lot = max(0.01, round(risk_tutari / pips_at_risk, 4))

            return {
                "ticker": symbol.replace("USDT", ""),
                "name": name,
                "price": f"{current_price:.5f}" if "EUR" in symbol or "GBP" in symbol else f"{current_price:.2f}",
                "entry": f"{entry_low:.5f} - {entry_high:.5f}" if "EUR" in symbol or "GBP" in symbol else f"{entry_low:.2f} - {entry_high:.2f}",
                "signal": signal,
                "sl": f"{sl:.5f}" if "EUR" in symbol or "GBP" in symbol else f"{sl:.2f}",
                "tp": f"{tp:.5f}" if "EUR" in symbol or "GBP" in symbol else f"{tp:.2f}",
                "rsi": f"{rsi:.2f}",
                "lot": f"{ideal_lot} Lot"
            }
        except Exception as e:
            return None

def build_report_string(data):
    if not data:
        return ""
    return (
        f"📈 **Sembol:** {data['ticker']} ({data['name']})\n"
        f"Mevcut Fiyat: {data['price']}\n"
        f"🎯 Giriş Bölgesi: {data['entry']}\n"
        f"📢 **SİNYAL:** {data['signal']}\n"
        f"🛑 **SL:** {data['sl']} | 🎯 **TP:** {data['tp']}\n"
        f"📊 RSI: {data['rsi']}\n"
        f"💰 **Önerilen Pozisyon (1k$ / %1.5 Risk):** {data['lot']}\n"
        f"----------------------------------------\n"
    )

# 4. TELEGRAM ARAYÜZ KOMUTLARI
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [['📊 Günlük Analiz', '🕒 Sinyalleri Yeniden Başlat']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "👋 Finans Analiz Ajanı Aktif!\n\n"
        "Doğrulanan varlık listesiyle sistem çalışıyor. Analiz raporu almaya hazırsınız.",
        reply_markup=reply_markup
    )

async def manual_analysis_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == '📊 Günlük Analiz':
        msg = await update.message.reply_text("🔄 Canlı veriler asenkron kanallardan çekiliyor, lütfen bekleyin...")
        
        full_report = "📊 **GÜNLÜK PİYASA ANALİZ RAPORU** 📊\n\n"
        
        # Pariteleri güvenli sırayla tara ve metni birleştir
        for pair, name in MARKET_PAIRS.items():
            data = await fetch_market_data_async(pair, name=name)
            if data:
                full_report += build_report_string(data)

        await context.bot.send_message(chat_id=MY_CHAT_ID, text=full_report, parse_mode="Markdown")
        await context.bot.delete_message(chat_id=MY_CHAT_ID, message_id=msg.message_id)

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Text(['📊 Günlük Analiz']), manual_analysis_trigger))
    application.add_handler(MessageHandler(filters.Text(['🕒 Sinyalleri Yeniden Başlat']), start))
    application.run_polling()

if __name__ == '__main__':
    main()
