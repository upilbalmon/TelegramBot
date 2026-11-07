import os
import json
import asyncio
import requests
from http.server import BaseHTTPRequestHandler

from telegram import Bot, Update

# ---------------------------------------------------------------
# Konfigurasi (semua lewat Environment Variables di Vercel)
#   TELEGRAM_BOT_TOKEN  : token dari @BotFather         (wajib)
#   GROQ_API_KEY        : API key Groq                   (utama)
#   GEMINI_API_KEY      : API key Gemini                 (cadangan)
#   GROQ_MODEL          : opsional, default di bawah
#   GEMINI_MODEL        : opsional, default di bawah
#   SHEETS_WEBHOOK_URL  : URL Web App Google Apps Script (diatur di Vercel Settings)
# ---------------------------------------------------------------
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

SHEETS_WEBHOOK_URL = os.environ.get("SHEETS_WEBHOOK_URL", "")
SECRET_TOKEN = "TOKEN_RAHASIA_TOKO_123"

SYSTEM_PROMPT = (
    "Kamu adalah asisten toko servis HP yang ramah dan membantu di Telegram. "
    "Jawab dalam bahasa yang dipakai pengguna, singkat dan jelas."
)

# Klien dibuat hanya kalau API key-nya ada, supaya bot tidak crash
groq_client = None
if GROQ_API_KEY:
    from openai import OpenAI

    groq_client = OpenAI(
        api_key=GROQ_API_KEY,
        base_url="https://api.groq.com/openai/v1",
    )

gemini_client = None
if GEMINI_API_KEY:
    from google import genai

    gemini_client = genai.Client(api_key=GEMINI_API_KEY)


def cari_status_ke_sheets(query: str) -> str:
    """Mencari data status servisan dari Google Sheets via Webhook."""
    if not SHEETS_WEBHOOK_URL:
        return None
    try:
        response = requests.get(
            SHEETS_WEBHOOK_URL,
            params={"action": "search", "query": query, "secret_token": SECRET_TOKEN},
            timeout=5
        )
        data = response.json()
        if data.get("found"):
            return (
                f"🔍 **Data Servis Ditemukan:**\n"
                f"- ID Servis: `{data.get('serviceId')}`\n"
                f"- Pelanggan: {data.get('customerName')}\n"
                f"- Perangkat: {data.get('deviceModel')}\n"
                f"- Status: *{data.get('status')}*\n"
                f"- Total Biaya: Rp {data.get('totalPrice')}"
            )
        else:
            return None
    except Exception as e:
        print("Gagal akses Google Sheets:", e)
        return None


def ask_groq(prompt: str) -> str:
    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content


def ask_gemini(prompt: str) -> str:
    interaction = gemini_client.interactions.create(
        model=GEMINI_MODEL,
        system_instruction=SYSTEM_PROMPT,
        input=prompt,
    )
    return interaction.output_text


def ask_ai(prompt: str) -> str:
    """Coba Groq dulu, kalau gagal pindah ke Gemini."""
    providers = []
    if groq_client:
        providers.append(("Groq", ask_groq))
    if gemini_client:
        providers.append(("Gemini", ask_gemini))

    if not providers:
        raise RuntimeError("Belum ada API key (GROQ_API_KEY / GEMINI_API_KEY).")

    last_error = None
    for name, fn in providers:
        try:
            text = fn(prompt)
            if text:
                return text
        except Exception as e:
            last_error = e
            print(f"{name} gagal: {e}")  # tampil di log Vercel

    raise last_error or RuntimeError("Semua penyedia AI tidak memberi jawaban.")


async def process_update(data):
    async with Bot(TOKEN) as bot:
        update = Update.de_json(data, bot)

        # Abaikan update yang bukan pesan teks
        if not update.message or not update.message.text:
            return

        chat_id = update.message.chat_id
        user_message = update.message.text.strip()

        # Perintah dasar
        if user_message.startswith("/start"):
            await bot.send_message(
                chat_id=chat_id,
                text="Halo! Kirimkan nomor nota atau nama Anda untuk mengecek status servis HP, atau tanyakan hal lain.",
            )
            return
        if user_message.startswith("/"):
            return

        try:
            # 1. Cek dulu apakah pesan mencocokkan data di Google Sheets
            sheet_result = await asyncio.to_thread(cari_status_ke_sheets, user_message)

            if sheet_result:
                reply_text = sheet_result
            else:
                # 2. Jika tidak ditemukan di Sheets, lempar ke AI (Groq/Gemini)
                reply_text = await asyncio.to_thread(ask_ai, user_message)
        except Exception as e:
            print("Error pemrosesan pesan:", e)
            reply_text = (
                "Maaf, server sedang sibuk atau gagal memproses data. "
                "Coba kirim lagi beberapa saat lagi ya."
            )

        # Batas panjang pesan Telegram 4096 karakter
        await bot.send_message(chat_id=chat_id, text=reply_text[:4096], parse_mode="Markdown")


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)
        try:
            json_data = json.loads(post_data.decode("utf-8"))
            asyncio.run(process_update(json_data))
        except Exception as e:
            print("Error:", e)
        # Selalu balas 200 supaya Telegram tidak mengirim ulang update yang sama
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot Telegram Terhubung ke Google Sheets & AI Berjalan!")
