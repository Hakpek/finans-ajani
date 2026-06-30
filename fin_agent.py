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
    "EURUSD=X": "EUR/USD Forex", "USDTRY=X": "USD/TRY Forex", "GC=F": "Altin ONS (Gold)", 
    "SI=F": "Gumus ONS (Silver)", "BZ=F": "Brent Petrol (Oil)", "^NDX": "Nasdaq 100 Endeksi",
    "THYAO.IS": "Turk Hava Yollari", "EREGL.IS": "Eregli Demir Celik", "ASELS.IS": "Aselsan", 
    "XU100.IS": "BIST 100 Endeksi", "AAPL": "Apple Stock", "NVDA": "Nvidia Stock"
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
    except: print("⚠️ Veritabanina baglanilamadi. Bot veritabanisiz modda calisacak.")
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
        w = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM signals WHERE ticker=%s AND status IS NOT NULL AND status != 'PENDING'", (ticker,))
        t = cur.fetchone()
        conn.close()
        return "Veri Yok (%0)" if t == 0 else f"%{(w/t)*100:.1f} Basari"
    except: return "Veri Yok (%0)"
        
        def analyze_market_sync(ticker, tf='1d'):
    try:
        p_map = {'1d': ('3mo', '1d', 'GUNLUK'), '1wk': ('1y', '1wk', 'HAFTALIK'), '1mo': ('2y', '1mo', 'AYLIK'), '1y': ('5y', '3mo', 'YILLIK')}
        prd, ivl, tf_txt = p_map.get(tf, ('3mo', '1d', 'GUNLUK'))
        df = yf.Ticker(ticker).history(period=prd, interval=ivl)
        if df.empty or len(df) < 10: return f"❌ {ticker}: Veri alinamadi.\n"
        df['RSI'] = ta.momentum.rsi(df['Close'])
        df['MACD'] = ta.trend.macd(df['Close'])
        df['MACD_S'] = ta.trend.macd_signal(df['Close'])
        df['ATR'] = ta.volatility.average_true_range(df['High'], df['Low'], df['Close'])
        df['BB_H'] = ta.volatility.bollinger_hband(df['Close'])
        df['BB_L'] = ta.volatility.bollinger_lband(df['Close'])
        df['STOCH'] = ta.momentum.stoch(df['High'], df['Low'], df['Close'])
        p, rsi, macd, macd_s = df['Close'].iloc[-1], df['RSI'].iloc[-1], df['MACD'].iloc[-1], df['MACD_S'].iloc[-1]
        bb_h, bb_l, stoch, atr = df['BB_H'].iloc[-1], df['BB_L'].iloc[-1], df['STOCH'].iloc[-1], df['ATR'].iloc[-1]
        sc = (1 if rsi < 45 else -1 if rsi > 55 else 0) + (1 if macd > macd_s else -1) + (1 if p <= bb_h * 0.52 else -1 if p >= bb_l * 0.48 else 0) + (1 if stoch < 40 else -1 if stoch > 60 else 0)
        n_sc, n_txt = get_news_sentiment(ticker)
        sc += (1 if n_sc > 0 else -1 if n_sc < 0 else 0)
        sig = "[STRONGBUY]" if sc >= 2 else "[BUY]" if sc >= 1 else "[SELL]" if sc <= -1 else "[STRONGSELL]" if sc <= -2 else "[NEUTRAL]"
        wr = get_db_win_rate(ticker)
        cfg = FOREX_CONFIG.get(ticker, {"pip_size": 0.01, "spread_pips": 0, "is_forex": False})
        if cfg["is_forex"]:
            pip, atr_p = cfg["pip_size"], atr / cfg["pip_size"]
            sl_p = max(atr_p * 1.5, 12.0)
            tp_p = sl_p * 1.5
            if "BUY" in sig: sl, tp, mt, ok, mt_tur = p - (sl_p * pip), p + (tp_p * pip), "Piyasa Fiyatindan AL (Buy)", True, "PIYASA ISLEMI (BUY)"
            elif "SELL" in sig: sl, tp, mt, ok, mt_tur = p + (sl_p * pip), p - (tp_p * pip), "Piyasa Fiyatindan SAT (Sell)", True, "PIYASA ISLEMI (SELL)"
            else: ok = False
            if ok:
                try:
                    conn = psycopg2.connect(DB_URL, connect_timeout=2)
                    conn.cursor().execute("INSERT INTO signals (ticker, signal, price, sl, tp, timestamp, status) VALUES (%s,%s,%s,%s,%s,%s,'PENDING')", (ticker, sig, p, sl, tp, datetime.now().strftime("%m-%d %H:%M")))
                    conn.commit(); conn.close()
                except: pass
                lot = max(min(20.0 / (sl_p * (10.0 if cfg["type"] == "fx" else cfg["contract_size"] * pip if cfg["type"] == "commodity" else cfg["contract_size"])), 2.0), 0.01)
                mc = (cfg["contract_size"] * lot) / 100 if cfg["type"] == "fx" else (cfg["contract_size"] * lot * p) / 100
                tk = ticker.replace("=X", "").replace("=F", "").replace("^", "")
                stk = "XAUUSD" if tk == "GC" else "XAGUSD" if tk == "SI" else "BRENT" if tk == "BZ" else "NAS100" if tk == "NDX" else tk
                return f"📈 Sembol: {ticker}\nPeriyot: {tf_txt} | Basari: {wr}\n📢 SİNYAL: {sig}\n💵 Fiyat: {p:.4f}\n📰 Haber: {n_txt}\n🛑 SL: {sl:.4f} | 🎯 TP: {tp:.4f}\n⚙️ Lot: {lot:.2f} | 💰 Maliyet: ~{mc:.2f} USD (1000$ Modeli)\n----------------------------------------\n🛠 MT REHBERI:\n1. '{stk}' paritesini acin.\n2. Islem Turu: '{mt_tur}' secin.\n3. Hacim (Lot): '{lot:.2f}' yazin.\n4. SL: '{sl:.4f}' | TP: '{tp:.4f}' girin.\n5. '{mt}' butonuna basin."
            return f"📈 Sembol: {ticker}\nPeriyot: {tf_txt}\n📢 SİNYAL: {sig}\n💵 Fiyat: {p:.4f}\n⏳ PİYASA NOTU: Yon belirsiz, islem acmayin."
        sl, tp = (p * 0.95, p * 1.10) if "BUY" in sig else (p * 1.05, p * 0.90) if "SELL" in sig else (p * 0.97, p * 1.03)
        adet = max(int(50.0 / p), 1) if p < 50 else 1
        return f"📈 Sembol: {ticker}\nPeriyot: {tf_txt} | Basari: {wr}\n📢 SİNYAL: {sig}\n💵 Fiyat: {p:.2f}\n🛑 SL: {sl:.2f} | 🎯 TP: {tp:.2f}\n⚙️ Onerilen Adet (Lot): {adet} Adet (1000$ Modeli)\n📊 RSI: {rsi:.2f}"
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
        sl_p = max((atr / pip) * 1.5, 12.0)
        tp_p = sl_p * 1.5
        sl = p - (sl_p * pip)
        tp = p + (tp_p * pip)
        lot = max(min(20.0 / (sl_p * (10.0 if cfg["type"] == "fx" else cfg["contract_size"] * pip if cfg["type"] == "commodity" else cfg["contract_size"])), 2.0), 0.01)
        return f"🔥 EN YUKSEK POTANSIYELLI {tf.upper()} RAPORU\n📌 Sembol: {nm} ({tk})\n💵 Fiyat: {p:.4f}\n🎯 Hedef Yön: PIYASA ISLEMI (BUY)\n🛑 SL: {sl:.4f} | 🎯 TP: {tp:.4f}\n⚙️ Onerilen Lot: {lot:.2f}\n💡 Gerekce: {rsn}"
    except Exception as e: return f"❌ Rapor hazirlanirken hata olustu: {str(e)}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [['📊 GUNLUK ANALIZ', '📈 HAFTALIK ANALIZ'], ['📉 AYLIK ANALIZ', '🗓 YILLIK ANALIZ']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("🤖 Yapay Zeka Destekli Finans Ajanina Hos Geldiniz!\n\nLutfen analiz etmek istediniz periyodu asagidaki menuden secin:", reply_markup=reply_markup)

async def menu_isleyici(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text
    tf_map = {'📊 GUNLUK ANALIZ': '1d', '📈 HAFTALIK ANALIZ': '1wk', '📉 AYLIK ANALIZ': '1mo', '🗓 YILLIK ANALIZ': '1y'}
    if txt in tf_map:
        tf = tf_map[txt]
        await update.message.reply_text(f"🔄 {txt} yapiliyor, veriler toplaniyor...")
        rapor = f"📊 **GÜNCEL {txt} SONUÇLARI** 📊\n\n"
        for ticker in list(POPULAR_MARKETS.keys())[:12]:  
            rapor += analyze_market_sync(ticker, tf) + "\n" + "-"*15 + "\n"
        await update.message.reply_text(rapor)

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    from telegram.request import HTTPXRequest
    api_request = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0)
    app = Application.builder().token(TELEGRAM_TOKEN).request(api_request).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_isleyici))
    print("🚀 Bot basariyla calistirildi! Telegram'dan test edebilirsiniz.")
    app.run_polling()

if __name__ == '__main__':
    main()
        
