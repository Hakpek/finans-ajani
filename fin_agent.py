import logging, yfinance as yf, pandas as pd, ta, os, asyncio, threading, psycopg2
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from flask import Flask

logging.basicConfig(level=logging.WARNING)
flask_app = Flask(__name__)

@flask_app.route('/')
def home(): return "Maksimum Donanimli Finans Ajani Aktif!"

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

DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")

def init_db():
    try:
        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS signals 
                          (id SERIAL PRIMARY KEY, ticker TEXT, signal TEXT, price REAL, sl REAL, tp REAL, timestamp TEXT, status TEXT)''')
        conn.commit()
        conn.close()
    except Exception as e: print(f"Veri tabani baglanti hatasi: {str(e)}")
init_db()
def get_news_sentiment(ticker):
    try:
        news_list = yf.Ticker(ticker).news
        if not news_list: return 0, "NOTR (Haber Yok)"
        pos = ["bullish", "growth", "buy", "profit", "surge", "rate cut", "ralli", "kazanc"]
        neg = ["bearish", "drop", "sell", "loss", "crash", "inflation", "rate hike", "risk", "gerilim", "dusus"]
        score = 0
        for n in news_list[:3]:
            title = n.get('title', '').lower()
            for w in pos:
                if w in title: score += 1
            for w in neg:
                if w in title: score -= 1
        if score > 0: return score, "POZITIF (Haber Destekli Yukselis)"
        elif score < 0: return score, "NEGATIF (Haber Kaynakli Baski)"
        return 0, "NOTR (Yatay Beklenti)"
    except: return 0, "NOTR (Haber Alinamadi)"

def get_db_win_rate(ticker):
    try:
        conn = psycopg2.connect(DB_URL)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM signals WHERE ticker=%s AND status='PROFIT'", (ticker,))
        wins = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) FROM signals WHERE ticker=%s AND status IS NOT NULL AND status != 'PENDING'", (ticker,))
        total = cursor.fetchone()
        conn.close()
        if total == 0: return "Veri Yok (%0)"
        return f"%{(wins/total)*100:.1f} Sinyal Basarisi"
    except: return "Hesaplanamadi"
def analyze_market_sync(ticker, timeframe='1d'):
    try:
        df = yf.Ticker(ticker).history(period='3mo', interval='1d')
        if df.empty or len(df) < 20: return f"❌ {ticker}: Veri alinamadi.\n"
        df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
        df['MACD'] = ta.trend.macd(df['Close'])
        df['MACD_Signal'] = ta.trend.macd_signal(df['Close'])
        df['ATR'] = ta.volatility.average_true_range(df['High'], df['Low'], df['Close'], window=14)
        df['BB_High'] = ta.volatility.bollinger_hband(df['Close'], window=20, window_dev=2)
        df['BB_Low'] = ta.volatility.bollinger_lband(df['Close'], window=20, window_dev=2)
        df['STOCH_K'] = ta.momentum.stoch(df['High'], df['Low'], df['Close'], window=14, smooth_window=3)
        current_price = df['Close'].iloc[-1]
        rsi = df['RSI'].iloc[-1] if not pd.isna(df['RSI'].iloc[-1]) else 50.0
        macd, macd_sig = df['MACD'].iloc[-1], df['MACD_Signal'].iloc[-1]
        bb_high, bb_low = df['BB_High'].iloc[-1], df['BB_Low'].iloc[-1]
        stoch_k = df['STOCH_K'].iloc[-1] if not pd.isna(df['STOCH_K'].iloc[-1]) else 50.0
        atr = df['ATR'].iloc[-1] if not pd.isna(df['ATR'].iloc[-1]) else (current_price * 0.005)
        score = (1 if rsi < 30 else -1 if rsi > 70 else 0) + (1 if macd > macd_sig else -1) + (1 if current_price <= bb_low else -1 if current_price >= bb_high else 0) + (1 if stoch_k < 20 else -1 if stoch_k > 80 else 0)
        news_score, news_text = get_news_sentiment(ticker)
        score += (1 if news_score > 0 else -1 if news_score < 0 else 0)
        signal = "[STRONGBUY]" if score >= 3 else "[BUY]" if score >= 1 else "[SELL]" if score <= -1 else "[STRONGSELL]" if score <= -3 else "[NEUTRAL]"
        win_rate_text = get_db_win_rate(ticker)
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
                    conn = psycopg2.connect(DB_URL)
                    conn.cursor().execute("INSERT INTO signals (ticker, signal, price, sl, tp, timestamp, status) VALUES (%s,%s,%s,%s,%s,%s,%s)", (ticker, signal, current_price, sl, tp, datetime.now().strftime("%Y-%m-%d %H:%M"), "PENDING"))
                    conn.commit()
                    conn.close()
                except: pass
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
                mt_guide = f"----------------------------------------\n🛠 METATRADER ISLEM REHBERI:\n1. Seçim: MetaTrader'da '{mt_search_name}' bulun.\n2. Tip: 'Piyasa Emri' secin.\n3. Hacim: '{calculated_lot:.2f}' lot yazin.\n4. SL: '{sl:.4f}' | 5. TP: '{tp:.4f}' yazin.\n6. Son Adım: Ekranda '{mt_type}' butonuna basın."
            else: sl_tp_text, lot_text, mt_guide = "", "", "⏳ PİYASA NOTU: Yon belirsiz. MetaTrader'da islem acmayin, beklemede kalin."
        else:
            lot_text, mt_guide = "", ""
            if "BUY" in signal: sl, tp = current_price * 0.95, current_price * 1.10
            elif "SELL" in signal: sl, tp = current_price * 1.05, current_price * 0.90
            else: sl, tp = current_price * 0.97, current_price * 1.03
            sl_tp_text = f"🛑 SL: {sl:.2f} | 🎯 TP: {tp:.2f}\n"
        tf_text = "GUNLUK" if timeframe == "1d" else "HAFTALIK" if timeframe == "1wk" else "AYLIK"
        return f"📈 Sembol: {ticker} ({POPULAR_MARKETS[ticker]})\nPeriyot: {tf_text} | 📊 Bot Gecmis Basarisi: {win_rate_text}\n📢 SİNYAL: {signal}\n💵 Giriş Fiyatı: {current_price:.4f}\n📰 Guncel Haber Duyarliligi: {news_text}\n" + sl_tp_text + lot_text + f"📊 RSI Değeri: {rsi:.2f}\n" + mt_guide
    except Exception as e: return f"❌ {ticker}: Hata. ({str(e)})\n"
async def send_bulk_report(application, target_chat_id, timeframe='1d'):
    tf_labels = {'1d': 'GUNLUK', '1wk': 'HAFTALIK', '1mo': 'AYLIK'}
    # Başlangıç mesajını ayrı gönderiyoruz
    await application.bot.send_message(chat_id=target_chat_id, text=f"📊 {tf_labels[timeframe]} YAPAY ZEKA PIYASA RAPORU BAŞLADI...\n==========", reply_markup=get_main_keyboard())
    loop = asyncio.get_event_loop()
    
    # Eski sinyalleri arkada güncelle
    await loop.run_in_executor(None, update_db_signals_status)
    
    for ticker in POPULAR_MARKETS.keys():
        report_part = await loop.run_in_executor(None, analyze_market_sync, ticker, timeframe)
        # KRİTİK DÜZELTME: Her sembolü ayrı bir mesaj olarak gönder, böylece Telegram asla engellemez
        await application.bot.send_message(chat_id=target_chat_id, text=report_part, reply_markup=get_main_keyboard())
        await asyncio.sleep(0.8) # Hız sınırına takılmamak için bekleme süresini hafifçe artırdık
        
    potential_report = await loop.run_in_executor(None, get_highest_potential_report_sync, timeframe)
    await application.bot.send_message(chat_id=target_chat_id, text=potential_report, reply_markup=get_main_keyboard())
