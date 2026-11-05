import os
import json
from http.server import BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, MessageHandler, filters
from google import genai

# Inisialisasi Gemini Client
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# Buat aplikasi Telegram tanpa run_polling()
async def process_update(data):
    application = Application.builder().token(TOKEN).build()
    
    async def handle_message(update: Update, context):
        user_message = update.message.text
        try:
            response = client.models.generate_content(
                model='gemini-1.5-flash',
                contents=user_message,
                config={
                    'system_instruction': 'Anda adalah asisten virtual yang ramah dan membantu.'
                }
            )
            reply_text = response.text
        except Exception as e:
            reply_text = "Maaf, terjadi gangguan pada sistem. Coba lagi ya!"
            
        await update.message.reply_text(reply_text)

    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    await application.initialize()
    update_obj = Update.de_json(data, application.bot)
    await application.process_update(update_obj)

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            json_data = json.loads(post_data.decode('utf-8'))
            import asyncio
            asyncio.run(process_update(json_data))
            
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'OK')
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode('utf-8'))

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'Bot Telegram Gemini sedang berjalan di Vercel!')
