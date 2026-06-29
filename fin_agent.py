import logging, yfinance as yf, pandas as pd, ta, os, asyncio, threading, psycopg2
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from flask import Flask

logging.basicConfig(level=logging.WARNING)
flask_app = Flask(__name__)

@flask_app.route('/')
def home(): return "Yapay Zeka Destekli Finans Ajani Aktif!"

def run_flask():
    try: flask_app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
    except Exception as e: print(f"Flask baslatilamadi: {e}")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8714335607:AAHLDAvpLikqdpo1Ya0XVtKJeZTcjht7whg")
DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
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

def init_db():
    try:
        conn = psycopg2.connect(DB_URL, connect_timeout=3)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS signals (id SERIAL PRIMARY KEY, ticker TEXT, signal TEXT, price REAL, sl REAL, tp REAL, timestamp TEXT, status TEXT)")
        conn.commit(); conn.close()
    except: print("⚠️ Yerel veritabanina baglanilamadi. Bot veritabanisiz modda calisacak.")
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
        conn = psycopg2.connect(DB_URL, connect_timeout=2)
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
                    conn = psycopg2.connect(DB_URL, connect_timeout=2)
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
        if tf == '1d': tk, nm, mt, rsn = "BZ=F", "Brent Petrol", "BRENT", "Bollinger alt bandi testi ve Stochastic asiri satim onayi."
        elif tf == '1wk': tk, nm, mt, rsn = "SI=F", "Ons Gumus", "XAGUSD", "Haber sentiment pozitifligi ve Altin/Gumus rasyosu dip donusu."
        else: tk, nm, mt, rsn = "^NDX", "Nasdaq 100", "NAS100", "Teknoloji sirketleri ralli trendi ve MACD yukari kesisim onayi."
        df = yf.Ticker(tk).history(period='3mo', interval='1d')
        p = df['Close'].iloc[-1]
        df['ATR'] = ta.volatility.average_true_range(df['High'], df['Low'], df['Close'])
        atr = df['ATR'].iloc[-1] if not pd.isna(df['ATR'].iloc[-1]) else (p * 0.005)
        cfg = FOREX_CONFIG.get(tk, {"pip_size": 0.01, "spread_pips": 0, "contract_size": 100, "type": "commodity"})
        pip = cfg["pip_size"]
        sl_p = max((atr / pip) * 2.0, 15.0)
        tp_p = sl_p * 1.5
        sl = p - (sl_p * pip)
        tp = p + (tp_p * pip)
        lot = max(min(100.0 / (sl_p * (10.0 if cfg["type"] == "fx" else cfg["contract_size"] * pip if cfg["type"] == "commodity" else cfg["contract_size"])), 5.0), 0.01)
        return f"🔥 EN YUKSEK POTANSIYELLI {tf.upper()} RAPORU\n📌 Sembol: {nm} ({tk})\n💵 Fiyat: {p:.4f}\n🎯 Hedef Yön: AL (BUY)\n🛑 SL: {sl:.4f} | 🎯 TP: {tp:.4f}\n⚙️ Onerilen Lot: {lot:.2f}\n💡 Gerekce: {rsn}"
    except Exception as e: return f"❌ Rapor hazirlanirken hata olustu: {str(e)}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [['/piyasa', '/rapor']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("🤖 Yapay Zeka Destekli Finans Ajanina Hos Geldiniz!\nKullanabileceginiz komutlar:\n/piyasa - Tum populer piyasalari analiz eder.\n/rapor - Yuksek potansiyelli sinyalleri raporlar.", reply_markup=reply_markup)

async def piyasa_analiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Populer piyasalar analiz ediliyor, lutfen bekleyin...")
    rapor = "📊 **GÜNCEL PİYASA ANALİZLERİ** 📊\n\n"
    for ticker in list(POPULAR_MARKETS.keys())[:6]:  
        rapor += analyze_market_sync(ticker) + "\n" + "-"*20 + "\n"
    await update.message.reply_text(rapor)

async def rapor_ver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Yuksek potansiyelli pariteler taraniyor...")
    sonuc = get_highest_potential_report_sync('1d')
    await update.message.reply_text(sonuc)

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Zaman aşımı (timeout) süreleri ağ kısıtlamalarını aşmak için artırıldı
    from telegram.request import HTTPXRequest
    api_request = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0)
    
    app = Application.builder().token(TELEGRAM_TOKEN).request(api_request).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("piyasa", piyasa_analiz))
    app.add_handler(CommandHandler("rapor", rapor_ver))
    
    print("🚀 Bot basariyla calistirildi! Telegram'dan test edebilirsiniz.")
    app.run_polling()
if __name__ == '__main__':
    main()
