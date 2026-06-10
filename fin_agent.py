import logging, yfinance as yf, pandas as pd, ta, os, asyncio, threading, psycopg2
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from flask import Flask

logging.basicConfig(level=logging.WARNING)
flask_app = Flask(__name__)

@flask_app.route('/')
def home(): return "Yapay Zeka Destekli Finans Ajani Aktif!"

def run_flask(): flask_app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

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
        conn = psycopg2.connect(DB_URL, connect_timeout=5)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS signals (id SERIAL PRIMARY KEY, ticker TEXT, signal TEXT, price REAL, sl REAL, tp REAL, timestamp TEXT, status TEXT)")
        conn.commit(); conn.close()
    except: pass
init_db()

def get_news_sentiment(ticker):
    try:
        news = yf.Ticker(ticker).news
        if not news: return 0, "NOTR"
        pos, neg, score = ["bullish", "growth", "buy", "profit", "surge"], ["bearish", "drop", "sell", "loss", "crash"], 0
        for n in news[:3]:
            t = n.get('title', '').lower()
            score += sum(1 for w in pos if w in t) - sum(1 for w in neg if w in t)
        return (score, "POZITIF") if score > 0 else (score, "NEGATIF") if score < 0 else (0, "NOTR")
    except: return 0, "NOTR"
def get_db_win_rate(ticker):
    try:
        conn = psycopg2.connect(DB_URL, connect_timeout=3)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM signals WHERE ticker=%s AND status='PROFIT'", (ticker,))
        w = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM signals WHERE ticker=%s AND status IS NOT NULL AND status != 'PENDING'", (ticker,))
        t = cur.fetchone()[0]
        conn.close()
        return "Veri Yok (%0)" if t == 0 else f"%{(w/t)*100:.1f} Basari"
    except: return "Veri Yok (%0)"

def analyze_market_sync(ticker, timeframe='1d'):
    try:
        df = yf.Ticker(ticker).history(period='3mo', interval='1d')
        if df.empty or len(df) < 20: return f"❌ {ticker}: Veri alinamadi.\n"
        df['RSI'] = ta.momentum.rsi(df['Close'])
        df['MACD'] = ta.trend.macd(df['Close'])
        df['MACD_S'] = ta.trend.macd_signal(df['Close'])
        df['ATR'] = ta.volatility.average_true_range(df['High'], df['Low'], df['Close'])
        df['BB_H'] = ta.volatility.bollinger_hband(df['Close'])
        df['BB_L'] = ta.volatility.bollinger_lband(df['Close'])
        df['STOCH'] = ta.momentum.stoch(df['High'], df['Low'], df['Close'])
        p, rsi, macd, macd_s = df['Close'].iloc[-1], df['RSI'].iloc[-1], df['MACD'].iloc[-1], df['MACD_S'].iloc[-1]
        bb_h, bb_l, stoch, atr = df['BB_H'].iloc[-1], df['BB_L'].iloc[-1], df['STOCH'].iloc[-1], df['ATR'].iloc[-1]
        sc = (1 if rsi < 30 else -1 if rsi > 70 else 0) + (1 if macd > macd_s else -1) + (1 if p <= bb_l else -1 if p >= bb_h else 0) + (1 if stoch < 20 else -1 if stoch > 80 else 0)
        n_sc, n_txt = get_news_sentiment(ticker)
        sc += (1 if n_sc > 0 else -1 if n_sc < 0 else 0)
        sig = "[STRONGBUY]" if sc >= 3 else "[BUY]" if sc >= 1 else "[SELL]" if sc <= -1 else "[STRONGSELL]" if sc <= -3 else "[NEUTRAL]"
        wr = get_db_win_rate(ticker)
        cfg = FOREX_CONFIG.get(ticker, {"pip_size": 0.01, "spread_pips": 0, "is_forex": False})
        if cfg["is_forex"]:
            pip, atr_p = cfg["pip_size"], atr / cfg["pip_size"]
            sl_p = max(atr_p * 2.0, 15.0)
            tp_p = sl_p * 1.5
            if "BUY" in sig: sl, tp, mt, ok = p - (sl_p * pip), p + (tp_p * pip), "Piyasa Fiyatindan AL (Buy)", True
            elif "SELL" in sig: sl, tp, mt, ok = p + (sl_p * pip), p - (tp_p * pip), "Piyasa Fiyatindan SAT (Sell)", True
            else: ok = False
            if ok:
                try:
                    conn = psycopg2.connect(DB_URL, connect_timeout=3)
                    conn.cursor().execute("INSERT INTO signals (ticker, signal, price, sl, tp, timestamp, status) VALUES (%s,%s,%s,%s,%s,%s,'PENDING')", (ticker, sig, p, sl, tp, datetime.now().strftime("%m-%d %H:%M")))
                    conn.commit(); conn.close()
                except: pass
                lot = max(min(100.0 / (sl_p * (10.0 if cfg["type"] == "fx" else cfg["contract_size"] * pip if cfg["type"] == "commodity" else cfg["contract_size"])), 5.0), 0.01)
                mc = (cfg["contract_size"] * lot) / 100 if cfg["type"] == "fx" else (cfg["contract_size"] * lot * p) / 100
                tk = ticker.replace("=X", "").replace("=F", "").replace("^", "")
                stk = "XAUUSD" if tk == "GC" else "XAGUSD" if tk == "SI" else "BRENT" if tk == "BZ" else "NAS100" if tk == "NDX" else tk
                return f"📈 Sembol: {ticker}\nPeriyot: GUNLUK | Basari: {wr}\n📢 SİNYAL: {sig}\n💵 Fiyat: {p:.4f}\n📰 Haber: {n_txt}\n🛑 SL: {sl:.4f} | 🎯 TP: {tp:.4f}\n⚙️ Lot: {lot:.2f} | 💰 Maliyet: ~{mc:.2f} USD\n----------------------------------------\n🛠 MT REHBERI:\n1. '{stk}' bulun.\n2. Hacim: '{lot:.2f}' | SL: '{sl:.4f}' | TP: '{tp:.4f}' yazin.\n3. '{mt}' butonuna basin."
            return f"📈 Sembol: {ticker}\n📢 SİNYAL: {sig}\n💵 Fiyat: {p:.4f}\n⏳ PİYASA NOTU: Yon belirsiz, islem acmayin."
        sl, tp = (p * 0.95, p * 1.10) if "BUY" in sig else (p * 1.05, p * 0.90) if "SELL" in sig else (p * 0.97, p * 1.03)
        return f"📈 Sembol: {ticker}\nPeriyot: GUNLUK | Basari: {wr}\n📢 SİNYAL: {sig}\n💵 Fiyat: {p:.4f}\n🛑 SL: {sl:.2f} | 🎯 TP: {tp:.2f}\n📊 RSI: {rsi:.2f}"
    except Exception as e: return f"❌ {ticker}: Hata. ({str(e)})\n"

def get_highest_potential_report_sync(tf):
    try:
        tk, nm, mt = ("BZ=F", "Brent Petrol", "BRENT") if tf == '1d' else ("SI=F", "Ons Gumus", "XAGUSD") if tf == '1wk' else ("^NDX", "Nasdaq 100", "NAS100")
        pr = yf.Ticker(tk).history(period='1mo')['Close'].iloc[-1]
        return f"----------------------------------------\nYUKSEK POTANSIYEL YATIRIM RAPORU\n----------------------------------------\nVarlık: {nm} | Canli: {pr:.2f} USD\nRehber: MetaTrader ekranina '{mt}' yazip islem acin.\n========================================"
    except: return "\nRapor hazirlanamadi."

def get_main_keyboard(): return ReplyKeyboardMarkup([['📊 Günlük Analiz', '📈 Haftalık Analiz'], ['📉 Aylık Analiz', '🔄 Sistemi Güncelle']], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text("🤖 HaPeFin Yapay Zeka Istasyonu Aktif!", reply_markup=get_main_keyboard())

async def auto_market_alert_scanner(app):
    for ticker in FOREX_CONFIG.keys():
        try:
            r = await asyncio.get_event_loop().run_in_executor(None, analyze_market_sync, ticker, '1d')
            if "[STRONGBUY]" in r or "[STRONGSELL]" in r: await app.bot.send_message(chat_id=MY_CHAT_ID, text=f"🚨 ⚡ 15 DK KIRILIM ALARMI ⚡ 🚨\n\n{r}")
        except: pass
        await asyncio.sleep(1)

def update_db_signals_status():
    try:
        conn = psycopg2.connect(DB_URL, connect_timeout=3); cur = conn.cursor()
        cur.execute("SELECT id, ticker, price, sl, tp FROM signals WHERE status='PENDING'")
        for row in cur.fetchall():
            sid, tk, ent, sl, tp = row
            curr = yf.Ticker(tk).history(period='1d')['Close'].iloc[-1]
            st = "PROFIT" if (tp > ent and curr >= tp) or (tp < ent and curr <= tp) else "LOSS" if (sl < ent and curr <= sl) or (sl > ent and curr >= sl) else "PENDING"
            if st != "PENDING": cur.execute("UPDATE signals SET status=%s WHERE id=%s", (st, sid))
        conn.commit(); conn.close()
    except: pass

async def send_bulk_report(app, chat_id, tf):
    await app.bot.send_message(chat_id=chat_id, text=f"📊 {tf.upper()} YAPAY ZEKA RAPORU BASLADI...\n==========")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, update_db_signals_status)
    for ticker in POPULAR_MARKETS.keys():
        r = await loop.run_in_executor(None, analyze_market_sync, ticker, tf)
        await app.bot.send_message(chat_id=chat_id, text=r)
        await asyncio.sleep(0.6)
    pot = await loop.run_in_executor(None, get_highest_potential_report_sync, tf)
    await app.bot.send_message(chat_id=chat_id, text=pot)

async def scheduled_morning_report(app): await send_bulk_report(app, MY_CHAT_ID, '1d')

async def handle_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text
    if t in ['/analiz_gunluk', 'analiz_gunluk', '/guncelle', 'guncelle', '📊 Günlük Analiz', '🔄 Sistemi Güncelle']: await send_bulk_report(context.application, MY_CHAT_ID, '1d')
    elif t in ['/analiz_haftalik', 'analiz_haftalik', '📈 Haftalık Analiz']: await send_bulk_report(context.application, MY_CHAT_ID, '1wk')
    elif t in ['/analiz_aylik', 'analiz_aylik', '📉 Aylık Analiz']: await send_bulk_report(context.application, MY_CHAT_ID, '1mo')

async def post_init(app: Application):
    sched = AsyncIOScheduler(timezone="Europe/Istanbul")
    sched.add_job(scheduled_morning_report, 'cron', hour=9, minute=0, args=[app])
    sched.add_job(auto_market_alert_scanner, 'interval', minutes=15, args=[app])
    sched.start()

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT | filters.COMMAND, handle_commands))
    app.run_polling()

if __name__ == '__main__': main()
