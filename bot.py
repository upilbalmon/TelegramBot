import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from google import genai

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Mengambil API Key dari sistem (Environment Variable), bukan ditulis manual
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    user_name = update.effective_user.first_name
    
    logging.info(f"Pesan dari {user_name}: {user_message}")

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=user_message,
            config={
                'system_instruction': 'Anda adalah asisten virtual yang ramah dan membantu.'
            }
        )
        reply_text = response.text
    except Exception as e:
        logging.error(f"Error saat menghubungi Gemini: {e}")
        reply_text = "Maaf, terjadi gangguan pada sistem. Coba lagi ya!"

    await update.message.reply_text(reply_text)

if __name__ == '__main__':
    # Mengambil Token Telegram dari sistem (Environment Variable)
    TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    print("Bot Telegram dengan Gemini sedang berjalan...")
    app.run_polling()
