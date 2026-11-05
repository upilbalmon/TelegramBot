import os
import json
import time
from http.server import BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, MessageHandler, filters
from google import genai

# Inisialisasi Gemini Client dengan API Key dari Environment Variables Vercel
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

async def process_update(data):
    application = Application.builder().token(TOKEN).build()
    
    async def handle_message(update: Update, context):
        user_message = update.message.text
        reply_text = None
        
        # Menggunakan model gemini-flash-latest agar selalu merujuk ke model aktif yang stabil
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model='gemini-flash-latest',
                    contents=user_message
                )
                reply_text = response.text
                break
            except Exception as e:
                error_str = str(e)
                if "503" in error_str or "UNAVAILABLE" in error_str:
                    if attempt < 2:
                        time.sleep(1)
                        continue
                reply_text = f"Maaf, terjadi gangguan pada sistem: {error_str}"
            
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
