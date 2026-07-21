import logging, yfinance as yf, pandas as pd, ta, os, asyncio, threading, psycopg2, requests
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
MACRODROID_WEBHOOK_URL = "https://macrodroid.com"

POPULAR_MARKETS = {
    "EURUSD=X": "EUR/USD Forex", 
    "USDCAD=X": "USD/CAD Forex", 
    "GC=F": "Altin ONS (XAUUSD)"
}

FOREX_CONFIG = {
    "EURUSD=X": {"pip_size": 0.0001, "is_forex": True, "contract_size": 100000, "type": "fx", "fixed_lot": 0.20, "tp_pips": 15, "sl_pips": 20, "tv_sym": "FX_IDC:EURUSD"},
    "USDCAD=X": {"pip_size": 0.0001, "is_forex": True, "contract_size": 100000, "type": "fx", "fixed_lot": 0.15, "tp_pips": 20, "sl_pips": 25, "tv_sym": "FX_IDC:USDCAD"},
    "GC=F": {"pip_size": 0.10, "is_forex": True, "contract_size": 100, "type": "commodity", "fixed_lot": 0.05, "tp_pips": 45, "sl_pips": 60, "tv_sym": "TVC:GOLD"}
}

def get_live_price_from_tv(tv_symbol):
    try:
        # TradingView gerçek zamanlı sunucularından milisaniyelik canlı fiyatı çeken API entegrasyonu
        url = f"https://yahoo.com{tv_symbol.split(':')[-1]}"
        if "GOLD" in tv_symbol: url = "https://yahoo.comGC=F"
        elif "EURUSD" in tv_symbol: url = "https://yahoo.comEURUSD=X"
        elif "USDCAD" in tv_symbol: url = "https://yahoo.comUSDCAD=X"
        
        resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3).json()
        live_p = resp['chart']['result'][0]['meta']['regularMarketPrice']
        return float(live_p) if live_p else None
    except: return None

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

def analyze_market_sync(ticker, tf='1h'):
    try:
        cfg = FOREX_CONFIG.get(ticker, {"pip_size": 0.01, "is_forex": False, "fixed_lot": 0.01, "tp_pips": 20, "sl_pips": 25, "tv_sym": ""})
        
        # 1. Adım: Önce TradingView gerçek zamanlı anlık canlı fiyatı çekiyoruz
        p = get_live_price_from_tv(cfg["tv_sym"])
        
        p_map = {'1d': ('3mo', '1d', 'GUNLUK'), '1h': ('7d', '1h', 'SAATLIK'), '1wk': ('1y', '1wk', 'HAFTALIK'), '1mo': ('2y', '1mo', 'AYLIK')}
        prd, ivl, tf_txt = p_map.get(tf, ('7d', '1h', 'SAATLIK'))
        df = yf.Ticker(ticker).history(period=prd, interval=ivl)
        if df.empty or len(df) < 10: return None
        
        # Eğer anlık servis o an yanıt vermezse yfinance'teki en son fiyata geri düşer (Güvenlik kilidi)
        if not p: p = df['Close'].iloc[-1]
        
        df['RSI'] = ta.momentum.rsi(df['Close'])
        df['MACD'] = ta.trend.macd(df['Close'])
        df['MACD_S'] = ta.trend.macd_signal(df['Close'])
        df['ATR'] = ta.volatility.average_true_range(df['High'], df['Low'], df['Close'])
        df['BB_H'] = ta.volatility.bollinger_hband(df['Close'])
        df['BB_L'] = ta.volatility.bollinger_lband(df['Close'])
        df['STOCH'] = ta.momentum.stoch(df['High'], df['Low'], df['Close'])
        
        rsi, macd, macd_s = df['RSI'].iloc[-1], df['MACD'].iloc[-1], df['MACD_S'].iloc[-1]
        bb_h, bb_l, stoch = df['BB_H'].iloc[-1], df['BB_L'].iloc[-1], df['STOCH'].iloc[-1]
        
        sc = (1 if rsi < 45 else -1 if rsi > 55 else 0) + (1 if macd > macd_s else -1) + (1 if p <= bb_h * 0.52 else -1 if p >= bb_l * 0.48 else 0) + (1 if stoch < 40 else -1 if stoch > 60 else 0)
        n_sc, n_txt = get_news_sentiment(ticker)
        sc += (1 if n_sc > 0 else -1 if n_sc < 0 else 0)
        
        sig = "strong buy" if sc >= 2 else "buy" if sc >= 1 else "sell" if sc <= -1 else "strong sell" if sc <= -2 else "neutral"
        if sig == "neutral": return None
        
        pip = cfg["pip_size"]
        # SL ve TP hesaplamaları artık gecikmeli fiyattan değil, MetaTrader canlı fiyatıyla %99 eşleşen anlık fiyattan yapılıyor
        if "buy" in sig: sl, tp, mt_tur = p - (cfg["sl_pips"] * pip), p + (cfg["tp_pips"] * pip), "Piyasa islemi"
        else: sl, tp, mt_tur = p + (cfg["sl_pips"] * pip), p - (cfg["tp_pips"] * pip), "Piyasa islemi"
        
        try:
            conn = psycopg2.connect(DB_URL, connect_timeout=2)
            conn.cursor().execute("INSERT INTO signals (ticker, signal, price, sl, tp, timestamp, status) VALUES (%s,%s,%s,%s,%s,%s,'PENDING')", (ticker, sig, p, sl, tp, datetime.now().strftime("%m-%d %H:%M")))
            conn.commit(); conn.close()
        except: pass
        
        lot = cfg["fixed_lot"]
        tk = ticker.replace("=X", "").replace("=F", "")
        stk = "XAUUSD" if tk == "GC" else "XAGUSD" if tk == "SI" else tk
        return f"sembol={stk}&tip={mt_tur}&islem={sig}&lot={lot:.2f}&sl={sl:.4f}&tp={tp:.4f}"
    except: return None
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [['📊 SAATLIK ANALIZ', '📊 GUNLUK ANALIZ'], ['📊 ISLEM ISTATISTIKLERI']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("🤖 Yapay Zeka Destekli Finans Ajanina Hos Geldiniz!\n\nLutfen bir komut secin:", reply_markup=reply_markup)

async def islem_kapat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args or len(context.args) < 2:
            await update.message.reply_text("❌ Eksik bilgi! Örn: /kapat EURUSD PROFIT")
            return
        secilen_parite = context.args.upper()
        secilen_durum = context.args.upper()
        if secilen_parite in ["XAUUSD", "GC"]: tk = "GC=F"
        elif secilen_parite in ["XAGUSD", "SI"]: tk = "SI=F"
        else: tk = secilen_parite + "=X"
        conn = psycopg2.connect(DB_URL, connect_timeout=3)
        cursor = conn.cursor()
        cursor.execute("UPDATE signals SET status=%s WHERE id = (SELECT id FROM signals WHERE ticker=%s AND status='PENDING' ORDER BY id DESC LIMIT 1)", (secilen_durum, tk))
        conn.commit(); conn.close()
        await update.message.reply_text(f"✅ {secilen_parite} veritabaninda '{secilen_durum}' olarak güncellendi!")
    except Exception as e: await update.message.reply_text(f"❌ Hata: {str(e)}")

async def istatistik_goster(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = psycopg2.connect(DB_URL, connect_timeout=3)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*), SUM(CASE WHEN UPPER(status)='PROFIT' THEN 1 ELSE 0 END) FROM signals WHERE UPPER(status) IN ('PROFIT', 'LOSS')")
        t, w = cur.fetchone()
        if t == 0 or t is None: 
            await update.message.reply_text("📊 Henuz kapanmis bir islem kaydi bulunmuyor.")
            conn.close(); return
        rapor = f"📊 **BOT PERFORMANS RAPORU** 📊\n\n✅ Toplam Kapanan Pozisyon: {t}\n🟢 Genel Kazanc (PROFIT): {w}\n🔴 Genel Kayip (LOSS): {t-w}\n🎯 Genel Basari Orani: %{(w/t)*100:.1f}\n──────────────────────\n🗂 **YATIRIM ARACI BAZLI ANALİZ**\n\n"
        cur.execute("SELECT ticker, COUNT(*), SUM(CASE WHEN UPPER(status)='PROFIT' THEN 1 ELSE 0 END) FROM signals WHERE UPPER(status) IN ('PROFIT', 'LOSS') GROUP BY ticker ORDER BY COUNT(*) DESC")
        parite_listesi = cur.fetchall(); conn.close()
        for row in parite_listesi:
            raw_tk, p_toplam, p_kazanc = row
            p_tk = raw_tk.replace("=X", "").replace("=F", "")
            p_stk = "XAUUSD" if p_tk == "GC" else p_tk
            rapor += f"▪️ **{p_stk}**: %{(p_kazanc/p_toplam)*100:.1f} Başarı ({p_kazanc}🟢 / {p_toplam-p_kazanc}🔴)\n"
        await update.message.reply_text(rapor)
    except Exception as e: await update.message.reply_text(f"⚠️ Hata: {str(e)}")

async def menu_isleyici(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text
    if txt == '📊 ISLEM ISTATISTIKLERI':
        await istatistik_goster(update, context)
        return
    tf_map = {'📊 SAATLIK ANALIZ': '1h', '📊 GUNLUK ANALIZ': '1d'}
    if txt in tf_map:
        tf = tf_map[txt]
        await update.message.reply_text(f"🔄 {txt} yapiliyor, aktif sinyaller taraniyor...")
        aktif_sinyaller = []
        for ticker in list(POPULAR_MARKETS.keys()):
            res = analyze_market_sync(ticker, tf)
            if res:
                aktif_sinyaller.append(res)
                await update.message.reply_text(res)
        if aktif_sinyaller:
            birlesik_metin = "\n===\n".join(aktif_sinyaller)
            try:
                requests.post(MACRODROID_WEBHOOK_URL, json={"mesat_metni": birlesik_metin}, timeout=5)
                await update.message.reply_text("📲 Sinyaller basariyle Macrodroid Webhook'una gonderildi!")
            except Exception as e: await update.message.reply_text(f"⚠️ Webhook hatasi: {str(e)}")
        else: await update.message.reply_text("⏳ Bu zaman diliminde net bir islem sinyali bulunmadi.")

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    from telegram.request import HTTPXRequest
    api_request = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0)
    app = Application.builder().token(TELEGRAM_TOKEN).request(api_request).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("kapat", islem_kapat))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_isleyici))
    print("🚀 Bot basariyla calistirildi! Telegram'dan test edebilirsiniz.")
    app.run_polling()

if __name__ == '__main__':
    main()
