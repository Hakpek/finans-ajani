# 4. BOT KOMUTLARI VE OTOMATİK BAŞLAYAN ZAMANLAYICI ALTYAPISI
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
        data = analyze_market_sync(ticker, timeframe='1d')
        if data and data != "LOW_LIQUIDITY":
            full_report += build_report_string(data) + "\n"
        await asyncio.sleep(1)
    await context.bot.send_message(chat_id=MY_CHAT_ID, text=full_report, parse_mode="Markdown")

async def scan_market_15min(context: ContextTypes.DEFAULT_TYPE):
    alert_report = ""
    for ticker in POPULAR_MARKETS.keys():
        data = analyze_market_sync(ticker, timeframe='1d')
        if data and data != "LOW_LIQUIDITY":
            if data['signal'] in ["[STRONGBUY]", "[STRONGSELL]"]:
                alert_report += "🚨 **GÜÇLÜ SİNYAL YAKALANDI** 🚨\n" + build_report_string(data) + "\n"
        await asyncio.sleep(1)
        
    if alert_report:
        await context.bot.send_message(chat_id=MY_CHAT_ID, text=alert_report, parse_mode="Markdown")

async def manual_analysis_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == '📊 Günlük Analiz':
        await context.bot.send_message(chat_id=MY_CHAT_ID, text="🔄 Görseldeki tüm pariteler taranıyor, lütfen bekleyin...")
        full_report = "📊 **ANLIK PİYASA ANALİZ RAPORU** 📊\n\n"
        for ticker in POPULAR_MARKETS.keys():
            data = analyze_market_sync(ticker, timeframe='1d')
            if data == "LOW_LIQUIDITY":
                full_report += f"⚠️ {ticker}: Düşük likidite dönemi. Sinyal üretilmedi.\n\n"
            elif data:
                full_report += build_report_string(data) + "\n"
            await asyncio.sleep(1)
        await context.bot.send_message(chat_id=MY_CHAT_ID, text=full_report, parse_mode="Markdown")

# DÖNGÜYÜ ENGELLEYEN YENİ GÜVENLİ BAŞLATICI FONKSİYON
async def post_init(application: Application) -> None:
    job_queue = application.job_queue
    
    # 1. Zamanlayıcı: 15 dakikalık Güçlü Sinyal Kontrolü (Hemen Başlar)
    job_queue.run_repeating(
        scan_market_15min,
        interval=900,
        first=5,
        name="otomatik_15dk_tarama"
    )
    
    # 2. Zamanlayıcı: Sabah 06:45 Genel Raporu
    target_time = datetime.strptime("06:45", "%H:%M").time()
    job_queue.run_daily(
        send_daily_analysis,
        time=target_time,
        name="sabah_ozeti_0645"
    )
    logging.warning("🚀 Zamanlanmış görevler güvenli başlatıcı (post_init) ile devreye alındı.")

# 5. ANA ÇALIŞTIRICI (MAIN)
def main():
    threading.Thread(target=run_flask, daemon=True).start()

    # Bot uygulamasını post_init kancasıyla inşa ediyoruz (Kilitlenmeyi önler)
    application = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    # Yönlendiriciler
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Text(['📊 Günlük Analiz']), manual_analysis_trigger))
    application.add_handler(MessageHandler(filters.Text(['🕒 Sinyalleri Yeniden Başlat']), start))

    application.run_polling()

if __name__ == '__main__':
    main()
