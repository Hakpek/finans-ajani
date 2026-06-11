import logging
import yfinance as yf
import pandas as pd
import ta
import os
import asyncio
import pytz
import random  # Yahoo engeli aşmak için eklendi
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
TELEGRAM_TOKEN = "8714335607:AAGt-nPJUsPPIGGmVeQzEnJi3mIbVNMluc0"
MY_CHAT_ID = 965495144

POPULAR_MARKETS = {
    "EURUSD=X": "EUR/USD Forex",
    "GBPUSD=X": "GBP/USD Forex",
    "USDCHF=X": "USD/CHF Forex",
    "USDJPY=X": "USD/JPY Forex",
    "USDCNH=X": "USD/CNH Forex",
    "USDRUB=X": "USD/RUB Forex",
    "AUDUSD=X": "AUD/USD Forex",
    "NZDUSD=X": "NZD/USD Forex",
    "USDCAD=X": "USD/CAD Forex",
    "USDSEK=X": "USD/SEK Forex",
    "USDTRY=X": "USD/TRY Forex",
    "GC=F": "Altin ONS (Gold)",
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum",
    "THYAO.IS": "Turk Hava Yollari",
    "XU100.IS": "BIST 100 Endeksi"
}

# 3. YAHHO FINANCE ENGELLERİNE KARŞI GÜÇLENDİRİLMİŞ ANALİZ MOTORU
async def analyze_market_async(ticker, timeframe='1d'):
    try:
        # Yahoo Finance IP engellemesini aşmak için her istek öncesi 1-3 saniye arası rastgele bekleme
        await asyncio.sleep(random.uniform(1.0, 3.0))
        
        # yfinance proxy veya session kısıtlamalarını aşmak için temiz kütüphane çağrısı
        asset = yf.Ticker(ticker)
        
        # Asenkron yapıda çalışırken engel yememek için kütüphanenin thread yönetimini optimize ediyoruz
        df = await asyncio.to_thread(asset.history, period='3mo', interval='1d')
        
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
        risk_orani = 0.015  # %1.5 risk
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
    except Exception as e:
        logging.error(f"Hata olustu {ticker}: {str(e)}")
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

# 4. BOT KOMUTLARI VE GÜVENLİ ASENKRON ZAMANLAYICILAR
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [['📊 Günlük Analiz', '🕒 Sinyalleri Yeniden Başlat']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "👋 Finans Analiz Ajanı Aktif!\n\n"
        "Bot şu an arka planda 15 dakikalık periyotlarla taramaya başladı. "
        "Sadece [STRONGBUY] veya [STRONGSELL] durumları oluştuğunda buraya otomatik bilgi düşecektir.",
        reply_markup=reply_markup
    )

async def send_daily_analysis(context: ContextTypes.DEFAULT_TYPE):
    full_report = "🌅 **SABAH PİYASA ÖZETİ RAPORU (06:45)** 🌅\n\n"
    for ticker in POPULAR_MARKETS.keys():
        data = await analyze_market_async(ticker, timeframe='1d')
        if data and data != "LOW_LIQUIDITY":
            full_report += build_report_string(data) + "\n"
    await context.bot.send_message(chat_id=MY_CHAT_ID, text=full_report, parse_mode="Markdown")

async def scan_market_15min(context: ContextTypes.DEFAULT_TYPE):
    alert_report = ""
    for ticker in POPULAR_MARKETS.keys():
        data = await analyze_market_async(ticker, timeframe='1d')
        if data and data != "LOW_LIQUIDITY":
            if data['signal'] in ["[STRONGBUY]", "[STRONGSELL]"]:
                alert_report += "🚨 **GÜÇLÜ SİNYAL YAKALANDI** 🚨\n" + build_report_string(data) + "\n"
        
    if alert_report:
        await context.bot.send_message(chat_id=MY_CHAT_ID, text=alert_report, parse_mode="Markdown")

async def manual_analysis_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == '📊 Günlük Analiz':
        await update.message.reply_text("🔄 Tüm pariteler güvenli sırayla taranıyor, lütfen 15-20 saniye bekleyin...")
        full_report = "📊 **ANLIK PİYASA ANALİZ RAPORU** 📊\n\n"
        for ticker in POPULAR_MARKETS.keys():
            data = await analyze_market_async(ticker, timeframe='1d')
            if data == "LOW_LIQUIDITY":
                full_report += f"⚠️ {ticker}: Düşük likidite dönemi. Sinyal üretilmedi.\n\n"
            elif data:
                full_report += build_report_string(data) + "\n"
        await context.bot.send_message(chat_id=MY_CHAT_ID, text=full_report, parse_mode="Markdown")

async def post_init(application: Application) -> None:
    job_queue = application.job_queue
    
    # 15 dakikalık otomatik tarama
    job_queue.run_repeating(
        scan_market_15min,
        interval=900,
        first=15,  # Çakışmayı önlemek için bot açıldıktan 15 saniye sonra ilk tarama başlar
        name="otomatik_15dk_tarama"
    )
    
    # Sabah 06:45 raporu
    target_time = datetime.strptime("06:45", "%H:%M").time()
    job_queue.run_daily(
        send_daily_analysis,
        time=target_time,
        name="sabah_ozeti_0645"
    )
    logging.warning("🚀 Güvenli zamanlayıcı kalkanı başarıyla kuruldu.")

# 5. ANA ÇALIŞTIRICI (MAIN)
def main():
    threading.Thread(target=run_flask, daemon=True).start()

    application = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Text(['📊 Günlük Analiz']), manual_analysis_trigger))
    application.add_handler(MessageHandler(filters.Text(['🕒 Sinyalleri Yeniden Başlat']), start))

    application.run_polling()

if __name__ == '__main__':
    main()
