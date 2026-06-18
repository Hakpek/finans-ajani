def get_inline_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("📊 Günlük Analiz", callback_data="tf_1d"),
            InlineKeyboardButton("📈 Haftalık Analiz", callback_data="tf_1wk")
        ],
        [
            InlineKeyboardButton("🕒 Aylık Analiz", callback_data="tf_1mo"),
            InlineKeyboardButton("🗓️ Yıllık Analiz", callback_data="tf_1y")
        ],
        [
            InlineKeyboardButton("🔄 Sinyalleri Yeniden Başlat", callback_data="tf_start")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_markup = get_inline_keyboard()
    await update.message.reply_text(
        "👋 Finans Analiz Ajanı Canlı Sürüm Aktif!\n\n"
        "• 1.00 Fiyat hatası ve USDJPY sıfır SL kilitlenmesi tamamen çözülmüştür.\n"
        "• Tüm piyasalar gerçek MetaTrader kurlarıyla senkronize edilmiştir.\n"
        "• Her sabah saat 06:45'te günlük rapor otomatik iletilecektir.",
        reply_markup=reply_markup,
    )


async def build_and_send_report(
    context: ContextTypes.DEFAULT_TYPE, timeframe="1d", target_chat_id=None
):
    global TRADE_HISTORY
    chat_id = target_chat_id if target_chat_id else MY_CHAT_ID
    tf_titles = {"1d": "GÜNLÜK", "1wk": "HAFTALIK", "1mo": "AYLIK", "1y": "YILLIK"}

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"📊 {tf_titles.get(timeframe, 'GÜNLÜK')} RAPORU BAŞLADI 📊\n----------------------------------------",
    )

    current_chunk = ""
    msg_counter = 1
    best_opportunity = None
    max_score = -1

    tasks = [analyze_market_sync(ticker, timeframe) for ticker in POPULAR_MARKETS.keys()]
    results = await asyncio.gather(*tasks)

    for res in results:
        if res:
            current_chunk += res["text"] + "\n\n"
            if res["score"] > max_score or (res["score"] == max_score and best_opportunity is None):
                max_score = res["score"]
                best_opportunity = res

            if len(current_chunk) > 2500:
                await context.bot.send_message(
                    chat_id=chat_id, text=f"📦 [Bölüm {msg_counter}]\n\n{current_chunk}"
                )
                current_chunk = ""
                msg_counter += 1
                await asyncio.sleep(0.1)

    if current_chunk:
        await context.bot.send_message(
            chat_id=chat_id, text=f"📦 [Bölüm {msg_counter}]\n\n{current_chunk}"
        )

    stats_text = (
        f"📊 **KÜRESEL SİNYAL KÂR/ZARAR İSTATİSTİĞİ** 📊\n"
        f"• Toplam Sonuçlanan İşlem: {TRADE_HISTORY['total_trades']}\n"
        f"• Başarılı (Kâr Al - TP): {TRADE_HISTORY['successful_trades']}\n"
        f"• Başarısız (Stop Loss - SL): {TRADE_HISTORY['failed_trades']}\n"
        f"• Şu An Açık/Takip Edilen Sipariş: {len(TRADE_HISTORY['active_orders'])}\n"
        f"----------------------------------------\n"
    )

    if best_opportunity:
        final_note = stats_text + (
            f"🔥 EN YÜKSEK KAZANÇ POTANSİYELİ RAPORU 🔥\n\n"
            f"MetaTrader canlı fiyatlarına ve meşru spread marjlarına göre "
            f"en yüksek getiri sunan varlık: {best_opportunity['name']}\n"
            f"Mevcut Giriş Fiyatı: {best_opportunity['price']}\n"
            f"Sinyal Durumu: {best_opportunity['signal']}\n"
            f"Zarar Durdur (SL): {best_opportunity['sl']}\n"
            f"Kar Al (TP {best_opportunity['label']} Hedefi): {best_opportunity['tp']}\n"
            f"💰 Alınması Gereken Miktar (1k$): {best_opportunity['qty']}\n\n"
            f"{best_opportunity['guide']}\n"
            f"----------------------------------------"
        )
    else:
        final_note = stats_text + "🔥 En yüksek kazanç potansiyeli hesaplanamadı."

    await context.bot.send_message(chat_id=chat_id, text=final_note, reply_markup=get_inline_keyboard())


async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data
    
    if data == "tf_1d":
        await context.bot.send_message(chat_id=chat_id, text="🔄 Canlı MetaTrader kurları senkronize ediliyor (Günlük)...")
        await build_and_send_report(context, "1d", target_chat_id=chat_id)
    elif data == "tf_1wk":
        await context.bot.send_message(chat_id=chat_id, text="🔄 Canlı haftalık hedefler hesaplanıyor...")
        await build_and_send_report(context, "1wk", target_chat_id=chat_id)
    elif data == "tf_1mo":
        await context.bot.send_message(chat_id=chat_id, text="🔄 Canlı aylık makro döngüler inceleniyor...")
        await build_and_send_report(context, "1mo", target_chat_id=chat_id)
    elif data == "tf_1y":
        await context.bot.send_message(chat_id=chat_id, text="🔄 Canlı yıllık uzun vade verileri çekiliyor...")
        await build_and_send_report(context, "1y", target_chat_id=chat_id)
    elif data == "tf_start":
        await context.bot.send_message(chat_id=chat_id, text="👋 Finans Analiz Ajanı paneli yenileniyor...", reply_markup=get_inline_keyboard())


async def post_init(application: Application) -> None:
    job_queue = application.job_queue
    t_time = datetime.strptime("06:45", "%H:%M").time()
    if job_queue:
        job_queue.run_daily(
            lambda ctx: build_and_send_report(ctx, timeframe="1d"),
            time=t_time,
            name="sabah_raporu_0645",
        )


def main():
    threading.Thread(target=run_flask, daemon=True).start()
    application = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback_handler))
    application.run_polling()


if __name__ == "__main__":
    main()
