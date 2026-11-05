import os
import json
import asyncio
from http.server import BaseHTTPRequestHandler
from telegram import Bot, Update
from google import genai

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
client = genai.Client()  # otomatis baca GEMINI_API_KEY dari environment


def ask_gemini(prompt: str) -> str:
    interaction = client.interactions.create(
        model=GEMINI_MODEL,
        input=prompt,
    )
    return interaction.output_text


async def process_update(data):
    async with Bot(TOKEN) as bot:
        update = Update.de_json(data, bot)

        if not update.message or not update.message.text:
            return

        user_message = update.message.text
        if user_message.startswith("/"):
            return

        try:
            # Dijalankan di thread terpisah supaya tidak memblokir event loop
            reply_text = await asyncio.to_thread(ask_gemini, user_message)
            reply_text = reply_text or "Maaf, saya tidak bisa menjawab itu."
        except Exception as e:
            print("Gemini error:", e)
            reply_text = f"Maaf, error: {e}"

        await bot.send_message(
            chat_id=update.message.chat_id,
            text=reply_text[:4096],
        )


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)
        try:
            json_data = json.loads(post_data.decode("utf-8"))
            asyncio.run(process_update(json_data))
        except Exception as e:
            print("Error:", e)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Telegram Gemini sedang berjalan di Vercel!")
