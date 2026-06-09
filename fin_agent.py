import logging, yfinance as yf, pandas as pd, ta, os, asyncio, threading
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from flask import Flask

logging.basicConfig(level=logging.WARNING)
flask_app = Flask(__name__)

@flask_app.route('/')
def home(): return "Finans Ajani Calisiyor!"

def run_flask():
    flask_app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

TELEGRAM_TOKEN = "8714335607:AAGt-nPJUsPPIGGmVeQzEnJi3mIbVNMluc0"
MY_CHAT_ID = 965495144 

POPULAR_MARKETS = {
    "THYAO.IS": "Turk Hava Yollari", "EREGL.IS": "Eregli Demir Celik", "ASELS.IS": "Aselsan", 
    "XU100.IS": "BIST 100 Endeksi", "AAPL": "Apple Stock", "NVDA": "Nvidia Stock", 
    "^GSPC": "S&P 500 Endeksi", "GC=F": "Altin ONS (Gold)", "SI=F": "Gumus ONS (Silver)", 
    "BZ=F": "Brent Petrol (Oil)", "^NDX": "Nasdaq 100 Endeksi", "EURUSD=X": "EUR/USD Forex", 
    "USDTRY=X": "USD/TRY Forex", "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum", "SOL-USD": "Solana"
}

FOREX_CONFIG = {
    "EURUSD=X": {"pip_size": 0.0001, "spread_pips": 1.5, "is_forex": True, "contract_size": 100000, "type": "fx"},
    "USDTRY=X": {"pip_size": 0.0001, "spread_pips": 20.0, "is_forex": True, "contract_size": 100000, "type": "fx"},
    "GC=F": {"pip_size": 0.10, "spread_pips": 3.5, "is_forex": True, "contract_size": 100, "type": "commodity"},
    "SI=F": {"pip_size": 0.01, "spread_pips": 2.5, "is_forex": True, "contract_size": 5000, "type": "commodity"},
    "BZ=F": {"pip_size": 0.01, "spread_pips": 3.0, "is_forex": True, "contract_size": 1000, "type": "commodity"},
    "^NDX": {"pip_size": 1.00, "spread_pips": 1.5, "is_forex": True, "contract_size": 10, "type": "index"}
}

def get_highest_potential_report_sync(timeframe):
    try:
        if timeframe == '1d':
            ticker, name, mt_names, reason = "BZ=F", "Brent Petrol", "BRENT, UKOIL veya BRN", "Gun ici jeopolitik gerilimler ve yuksek gunluk ATR kirilimi."
            action, mt_button = "Kisa vadeli direnc kirilimiyla birlikte AL (Buy)", "Buy by Market"
        elif timeframe == '1wk':
            ticker, name, mt_names, reason = "SI=F", "Ons Gumus", "XAGUSD, SILVER veya XAGUSD.", "Altin/Gumus rasyosundaki donemsel daralma ve endustriyel talep artisi."
            action, mt_button = "Haftalik destek seviyesinden kademeli AL (Buy Limit)", "Buy Limit"
        else:
            ticker, name, mt_names, reason = "^NDX", "Nasdaq 100", "NAS100, US100 veya USTECH", "Yillik yapay zeka yatirimlari ve teknoloji rallisi ana trend takibi."
            action, mt_button = "Geri cekilmelerde uzun vadeli portfoye EKLE (Buy)", "Buy by Market"
        price = yf.Ticker(ticker).history(period='1mo', interval='1d')['Close'].iloc[-1]
        return (
            f"----------------------------------------\n"
            f"YUKSEK POTANSIYEL YATIRIM RAPORU\n"
            f"----------------------------------------\n"
            f"Hedef Varklik: {name}\n💵 Canli Fiyat: {price:.2f} USD\n💡 Gerekce: {reason}\n"
            f"----------------------------------------\n"
            f"METATRADER ISLEM REHBERI:\n"
            f"1. Arama: MetaTrader ekranina '{mt_names}' yazin.\n2. Strateji: {action}\n"
            f"3. Risk: Maksimum 0.02 Lot ile baslayin.\n4. Uygulama: Emir ekraninda '{mt_button}' kullanın.\n"
            f"========================================"
        )
    except Exception as e: return f"----------------------------------------\n⚠️ Potansiyel raporu hatasi: {str(e)}"
def analyze_market_sync(ticker, timeframe='1d'):
    try:
        df = yf.Ticker(ticker).history(period='3mo', interval='1d')
        if df.empty or len(df) < 15: return f"❌ {ticker}: Veri alinamadi.\n"
        df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
        df['MACD'] = ta.trend.macd(df['Close'])
        df['MACD_Signal'] = ta.trend.macd_signal(df['Close'])
        df['ATR'] = ta.volatility.average_true_range(df['High'], df['Low'], df['Close'], window=14)
        current_price = df['Close'].iloc[-1]
        rsi = df['RSI'].iloc[-1] if not pd.isna(df['RSI'].iloc[-1]) else 50.0
        macd = df['MACD'].iloc[-1] if not pd.isna(df['MACD'].iloc[-1]) else 0.0
        macd_sig = df['MACD_Signal'].iloc[-1] if not pd.isna(df['MACD_Signal'].iloc[-1]) else 0.0
        atr = df['ATR'].iloc[-1] if not pd.isna(df['ATR'].iloc[-1]) else (current_price * 0.005)
        score = (1 if rsi < 30 else -1 if rsi > 70 else 0) + (1 if macd > macd_sig else -1)
        signal = "[STRONGBUY]" if score >= 2 else "[BUY]" if score == 1 else "[SELL]" if score == -1 else "[STRONGSELL]" if score <= -2 else "[NEUTRAL]"
        config = FOREX_CONFIG.get(ticker, {"pip_size": 0.01, "spread_pips": 0, "is_forex": False})
        if config["is_forex"]:
            pip_size, atr_pips = config["pip_size"], atr / config["pip_size"]
            sl_pips = max(atr_pips * 2.0, 15.0)
            tp_pips = sl_pips * 1.5
            if "BUY" in signal: sl, tp, mt_type, is_tradable = current_price - (sl_pips * pip_size), current_price + (tp_pips * pip_size), "Piyasa Fiyatindan AL (Buy by Market)", True
            elif "SELL" in signal: sl, tp, mt_type, is_tradable = current_price + (sl_pips * pip_size), current_price - (tp_pips * pip_size), "Piyasa Fiyatindan SAT (Sell by Market)", True
            else: is_tradable = False
            if is_tradable:
                try:
                    if config["type"] == "fx": calculated_lot = 100.0 / (sl_pips * 10.0)
                    elif config["type"] == "commodity": calculated_lot = 100.0 / (sl_pips * config["contract_size"] * pip_size)
                    else: calculated_lot = 100.0 / (sl_pips * config["contract_size"])
                    calculated_lot = max(min(calculated_lot, 5.0), 0.01)
                except: calculated_lot = 0.01
                margin_cost = (config["contract_size"] * calculated_lot) / 100 if config["type"] == "fx" else (config["contract_size"] * calculated_lot * current_price) / 100
                mt_name = ticker.replace("=X", "").replace("=F", "").replace("^", "")
                mt_search_name = "XAUUSD (GOLD)" if mt_name == "GC" else "XAGUSD (SILVER)" if mt_name == "SI" else "BRENT (OIL)" if mt_name == "BZ" else "NAS100" if mt_name == "NDX" else mt_name
                sl_tp_text = f"🛑 SL (Zarar Durdur): {sl:.4f}\n🎯 TP (Kar Al): {tp:.4f}\n"
                lot_text = f"⚙️ Onerilen Hacim: {calculated_lot:.2f} Lot\n💰 Islem Maliyeti: ~{margin_cost:.2f} USD\n"
                mt_guide = (
                    f"----------------------------------------\n🛠 METATRADER ISLEM REHBERI:\n"
                    f"1. Parite Seçimi: MetaTrader'da '{mt_search_name}' bulun.\n2. Emir Tipi: 'Piyasa Emri' (Market Execution) secin.\n"
                    f"3. Hacim (Lot): Ekrana '{calculated_lot:.2f}' yazin.\n4. Zarar Durdur (SL): '{sl:.4f}' yazin.\n5. Kâr Al (TP): '{tp:.4f}' yazin.\n"
                    f"6. Son Adım: Ekranda '{mt_type}' butonuna basın."
                )
            else: sl_tp_text, lot_text, mt_guide = "", "", "⏳ PİYASA NOTU: Yon belirsiz. MetaTrader'da islem acmayin, beklemede kalin."
        else:
            lot_text, mt_guide = "", ""
            if "BUY" in signal: sl, tp = current_price * 0.95, current_price * 1.10
            elif "SELL" in signal: sl, tp = current_price * 1.05, current_price * 0.90
            else: sl, tp = current_price * 0.97, current_price * 1.03
            sl_tp_text = f"🛑 SL: {sl:.2f} | 🎯 TP: {tp:.2f}\n"
        
        tf_text = "GUNLUK" if timeframe == "1d" else "HAFTALIK" if timeframe == "1wk" else "AYLIK"
        return f"📈 Sembol: {ticker} ({POPULAR_MARKETS[ticker]})\nPeriyot: {tf_text}\n📢 SİNYAL: {signal}\n💵 Giriş Fiyatı: {current_price:.4f}\n" + sl_tp_text + lot_text + f"📊 RSI Değeri: {rsi:.2f}\n" + mt_guide
    except Exception as e: return f"❌ {ticker}: Hata. ({str(e)})\n"

def get_main_keyboard():
    return ReplyKeyboardMarkup([['📊 Günlük Analiz', '📈 Haftalık Analiz'], ['📉 Aylık Analiz', '🔄 Sistemi Güncelle']], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 HaPeFin Finans Ajanı Aktif!", reply_markup=get_main_keyboard())

async def send_bulk_report(application, target_chat_id, timeframe='1d'):
    tf_labels = {'1d': 'GUNLUK', '1wk': 'HAFTALIK', '1mo': 'AYLIK'}
    await application.bot.send_message(chat_id=target_chat_id, text=f"📊 {tf_labels[timeframe]} PİYASA RAPORU BAŞLADI...\n==========", reply_markup=get_main_keyboard())
    loop = asyncio.get_event_loop()
    for ticker in POPULAR_MARKETS.keys():
        report_part = await loop.run_in_executor(None, analyze_market_sync, ticker, timeframe)
        await application.bot.send_message(chat_id=target_chat_id, text=report_part, reply_markup=get_main_keyboard())
        await asyncio.sleep(0.5)
    potential_report = await loop.run_in_executor(None, get_highest_potential_report_sync, timeframe)
    await application.bot.send_message(chat_id=target_chat_id, text=potential_report, reply_markup=get_main_keyboard())

async def scheduled_morning_report(application): await send_bulk_report(application, MY_CHAT_ID, '1d')

async def handle_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text in ['/analiz_gunluk', 'analiz_gunluk', '/guncelle', 'guncelle', '📊 Günlük Analiz', '🔄 Sistemi Güncelle']: await send_bulk_report(context.application, MY_CHAT_ID, '1d')
    elif text in ['/analiz_haftalik', 'analiz_haftalik', '📈 Haftalık Analiz']: await send_bulk_report(context.application, MY_CHAT_ID, '1wk')
    elif text in ['/analiz_aylik', 'analiz_aylik', '📉 Aylık Analiz']: await send_bulk_report(context.application, MY_CHAT_ID, '1mo')

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

if __name__ == '__main__': main()
