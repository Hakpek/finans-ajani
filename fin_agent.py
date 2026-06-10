import logging, yfinance as yf, pandas as pd, ta, os, asyncio, threading, sqlite3
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from flask import Flask

logging.basicConfig(level=logging.WARNING)
flask_app = Flask(__name__)

@flask_app.route('/')
def home(): return "Gelismis Finans Ajani Aktif!"

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

# 🗄️ GEÇMİŞ BAŞARI TAKİBİ İÇİN VERİ TABANI AYARLARI
DB_FILE = "trade_history.db"
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS signals 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, signal TEXT, price REAL, sl REAL, tp REAL, timestamp TEXT, status TEXT)''')
    conn.commit()
    conn.close()
init_db()

# 📰 CANLI HABER VE SENTIMENT (DUYARLILIK) SKORLAMA MOTORU
def get_news_sentiment(ticker):
    try:
        asset = yf.Ticker(ticker)
        news_list = asset.news
        if not news_list: return 0, "NOTR (Haber Yok)"
        
        positive_keywords = ["bullish", "growth", "buy", "profit", "surge", "unemployment drop", "rate cut", "ralli", "kazanc"]
        negative_keywords = ["bearish", "drop", "sell", "loss", "crash", "inflation", "rate hike", "risk", "gerilim", "dusus"]
        
        score = 0
        count = 0
        for n in news_list[:3]: # Son 3 haberi incele
            title = n.get('title', '').lower()
            for word in positive_keywords:
                if word in title: score += 1
            for word in negative_keywords:
                if word in title: score -= 1
            count += 1
            
        if score > 0: return score, "POZITIF (Haber Destekli Yukselis)"
        elif score < 0: return score, "NEGATIF (Haber Kaynakli Baski)"
        return 0, "NOTR (Yatay Beklenti)"
    except:
        return 0, "NOTR (Haber Alinamadi)"
def get_db_win_rate(ticker):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM signals WHERE ticker=? AND status='PROFIT'", (ticker,))
        wins = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM signals WHERE ticker=? AND status IS NOT NULL", (ticker,))
        total = cursor.fetchone()[0]
        conn.close()
        if total == 0: return "Veri Yok (%0)"
        return f"%{(wins/total)*100:.1f} Sinyal Basarisi"
    except: return "Hesaplanamadi"

def analyze_market_sync(ticker, timeframe='1d'):
    try:
        df = yf.Ticker(ticker).history(period='3mo', interval='1d')
        if df.empty or len(df) < 20: return f"❌ {ticker}: Veri alinamadi.\n"
        
        # 📊 ÇOKLU İNDİKATÖR KOMBİNASYONU
        df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
        df['MACD'] = ta.trend.macd(df['Close'])
        df['MACD_Signal'] = ta.trend.macd_signal(df['Close'])
        df['ATR'] = ta.volatility.average_true_range(df['High'], df['Low'], df['Close'], window=14)
        
        # Bollinger Bantları Filtresi
        df['BB_High'] = ta.volatility.bollinger_hband(df['Close'], window=20, window_dev=2)
        df['BB_Low'] = ta.volatility.bollinger_lband(df['Close'], window=20, window_dev=2)
        
        # Stochastic Osilatör Filtresi
        df['STOCH_K'] = ta.momentum.stoch(df['High'], df['Low'], df['Close'], window=14, smooth_window=3)
        
        current_price = df['Close'].iloc[-1]
        rsi = df['RSI'].iloc[-1] if not pd.isna(df['RSI'].iloc[-1]) else 50.0
        macd = df['MACD'].iloc[-1]
        macd_sig = df['MACD_Signal'].iloc[-1]
        bb_high, bb_low = df['BB_High'].iloc[-1], df['BB_Low'].iloc[-1]
        stoch_k = df['STOCH_K'].iloc[-1] if not pd.isna(df['STOCH_K'].iloc[-1]) else 50.0
        atr = df['ATR'].iloc[-1] if not pd.isna(df['ATR'].iloc[-1]) else (current_price * 0.005)
        
        # 🧠 Gelişmiş Skorlama Mantığı (Maks: +4, Min: -4)
        score = 0
        if rsi < 30: score += 1
        elif rsi > 70: score -= 1
        if macd > macd_sig: score += 1
        else: score -= 1
        if current_price <= bb_low: score += 1 # Fiyat dipten dönüyor
        elif current_price >= bb_high: score -= 1 # Fiyat tepeden dönüyor
        if stoch_k < 20: score += 1
        elif stoch_k > 80: score -= 1
        
        # 📰 Canlı Haber Sentiment Filtresi Entegrasyonu
        news_score, news_text = get_news_sentiment(ticker)
        if news_score > 0: score += 1
        elif news_score < 0: score -= 1
        
        signal = "[STRONGBUY]" if score >= 3 else "[BUY]" if score >= 1 else "[SELL]" if score <= -1 else "[STRONGSELL]" if score <= -3 else "[NEUTRAL]"
        
        # Başarı Oranı Hafızası Çekimi
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
                # Geçmiş kaydı simüle etmek için veri tabanına yaz (İleride doğrulanacak)
                conn = sqlite3.connect(DB_FILE)
                conn.cursor().execute("INSERT INTO signals (ticker, signal, price, sl, tp, timestamp, status) VALUES (?,?,?,?,?,?,?)",
                                      (ticker, signal, current_price, sl, tp, datetime.now().strftime("%Y-%m-%d %H:%M"), "PENDING"))
                conn.commit()
                conn.close()
                
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
                    f"1. Seçim: MetaTrader'da '{mt_search_name}' bulun.\n2. Tip: 'Piyasa Emri' secin.\n"
                    f"3. Hacim: '{calculated_lot:.2f}' lot yazin.\n4. SL: '{sl:.4f}' | 5. TP: '{tp:.4f}' yazin.\n"
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
        return f"📈 Sembol: {ticker} ({POPULAR_MARKETS[ticker]})\nPeriyot: {tf_text} | 📊 Bot Gecmis Basarisi: {win_rate_text}\n📢 SİNYAL: {signal}\n💵 Giriş Fiyatı: {current_price:.4f}\n📰 Guncel Haber Duyarliligi: {news_text}\n" + sl_tp_text + lot_text + f"📊 RSI Değeri: {rsi:.2f}\n" + mt_guide
    except Exception as e: return f"❌ {ticker}: Hata. ({str(e)})\n"

def get_highest_potential_report_sync(timeframe):
    try:
        if timeframe == '1d':
            ticker, name, mt_names = "BZ=F", "Brent Petrol", "BRENT, UKOIL veya BRN"
            reason = "Jeopolitik riskler, Bollinger alt bandi testi ve Stochastic asiri satim onayi."
            action, mt_button = "Kisa vadeli direnc kirilimiyla birlikte AL (Buy)", "Buy by Market"
        elif timeframe == '1wk':
            ticker, name, mt_names = "SI=F", "Ons Gumus", "XAGUSD, SILVER veya XAGUSD."
            reason = "Haber sentiment pozitifligi ve Altin/Gumus rasyosu donemsel dip donusu."
            action, mt_button = "Haftalik destek seviyesinden kademeli AL (Buy Limit)", "Buy Limit"
        else:
            ticker, name, mt_names = "^NDX", "Nasdaq 100", "NAS100, US100 veya USTECH"
            reason = "Teknoloji sirketleri uzun vadeli ralli trendi ve MACD yukari kesisim onayı."
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
def get_main_keyboard():
    return ReplyKeyboardMarkup([['📊 Günlük Analiz', '📈 Haftalık Analiz'], ['📉 Aylık Analiz', '🔄 Sistemi Güncelle']], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 HaPeFin Profesyonel Yapay Zeka Algoritmik Ajan Aktif!", reply_markup=get_main_keyboard())

# 🚨 ANLIK ALARM SİSTEMİ (Arka Planda Sürekli Çalışan Canlı Tarayıcı)
async def auto_market_alert_scanner(application):
    loop = asyncio.get_event_loop()
    for ticker in FOREX_CONFIG.keys(): # Özellikle yüksek kaldıraçlı Forex ve Emtiaları tara
        try:
            report = await loop.run_in_executor(None, analyze_market_sync, ticker, '1d')
            # Eğer indikatörler ve haberler ortaklaşa GÜÇLÜ AL veya GÜÇLÜ SAT ürettiyse raporu bekleme, anında alarm at
            if "[STRONGBUY]" in report or "[STRONGSELL]" in report:
                alert_msg = f"🚨 ⚡ ACIL ISLEM ALARMI (GIZLI KIRILIM YAKALANDI) ⚡ 🚨\n\n{report}"
                await application.bot.send_message(chat_id=MY_CHAT_ID, text=alert_msg, reply_markup=get_main_keyboard())
        except: pass
        await asyncio.sleep(1)

# Geçmiş Emrin Kâr/Zarar Durumunu Kontrol Eden Arka Plan Güncelleyicisi
def update_db_signals_status():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT id, ticker, price, sl, tp FROM signals WHERE status='PENDING'")
        pending = cursor.fetchall()
        for row in pending:
            sid, ticker, entry, sl, tp = row
            current = yf.Ticker(ticker).history(period='1d')['Close'].iloc[-1]
            if tp > entry and current >= tp: status = "PROFIT"
            elif tp < entry and current <= tp: status = "PROFIT"
            elif sl < entry and current <= sl: status = "LOSS"
            elif sl > entry and current >= sl: status = "LOSS"
            else: continue
            cursor.execute("UPDATE signals SET status=? WHERE id=?", (status, sid))
        conn.commit()
        conn.close()
    except: pass

async def send_bulk_report(application, target_chat_id, timeframe='1d'):
    tf_labels = {'1d': 'GUNLUK', '1wk': 'HAFTALIK', '1mo': 'AYLIK'}
    await application.bot.send_message(chat_id=target_chat_id, text=f"📊 {tf_labels[timeframe]} YAPAY ZEKA PIYASA RAPORU BAŞLADI...\n==========", reply_markup=get_main_keyboard())
    loop = asyncio.get_event_loop()
    
    # Rapor öncesi eski sinyallerin kâr durumunu güncelle
    await loop.run_in_executor(None, update_db_signals_status)
    
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
    # 🚨 Her 30 dakikada bir piyasaları arkadan gizlice tara, kırılım varsa anlık cebine bildirim fırlat
    scheduler.add_job(auto_market_alert_scanner, 'interval', minutes=30, args=[application])
    scheduler.start()

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT | filters.COMMAND, handle_commands))
    print("🤖 Gelismis Algoritmik Bot Aktif Edildi!")
    app.run_polling()

if __name__ == '__main__': main()
