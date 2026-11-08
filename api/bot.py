import asyncio
import json
import os
from http.server import BaseHTTPRequestHandler
import requests

from telegram import Bot, Update

# ---------------------------------------------------------------
# Konfigurasi Environment Variables (Atur di Vercel Settings)
# ---------------------------------------------------------------
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")

SHEETS_WEBHOOK_URL = os.environ.get("SHEETS_WEBHOOK_URL", "")
SECRET_TOKEN = os.environ.get("SECRET_TOKEN")

# SYSTEM PROMPT MULTI-MODE & STRICT DATABASE
SYSTEM_PROMPT = (
    "Kamu adalah asisten AI resmi untuk konter servis HP 'i Cell GadgetFix'. "
    "Tugasmu HANYA melayani pelanggan umum.\n\n"
    "ATURAN KERAS:\n"
    "- CEK STATUS & BIAYA NAMA/NOTA:** Jika menanyakan status servisan spesifik, tampilkan status beserta total biaya dari tabel 'tiket_servis'.\n"
    "- JANGAN mengarang harga, stok, status, estimasi waktu, atau garansi. "
    "Jika tidak ada di data, jawab: 'Untuk info itu, silakan hubungi teknisi kami di 08999479240.'\n"
)

# Inisialisasi Klien AI
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

# ---------------------------------------------------------------
# MEMORY STORAGE (Penyimpanan Riwayat Chat Berdasarkan chat_id)
# ---------------------------------------------------------------
chat_histories = {}
MAX_HISTORY = 6  # Batasi 6 pesan terakhir agar hemat token


def get_conversation_history(chat_id: int):
  if chat_id not in chat_histories:
    chat_histories[chat_id] = []
  return chat_histories[chat_id]


def add_to_history(chat_id: int, role: str, content: str):
  history = get_conversation_history(chat_id)
  history.append({"role": role, "content": content})
  if len(history) > MAX_HISTORY:
    chat_histories[chat_id] = history[-MAX_HISTORY:]


def ambil_database_sheets() -> str:
  """Mengambil seluruh data (Tiket Servis & Daftar Harga) dari Google Sheets."""
  if not SHEETS_WEBHOOK_URL:
    return "{}"
  try:
    response = requests.get(
        SHEETS_WEBHOOK_URL,
        params={"secret_token": SECRET_TOKEN},
        timeout=5,
    )
    return response.text
  except Exception as e:
    print("Gagal mengambil database Google Sheets:", e)
    return "{}"


def ask_groq_with_context(chat_id: int, user_prompt: str, sheet_data: str) -> str:
  history = get_conversation_history(chat_id)

  context_prompt = (
      f"{SYSTEM_PROMPT}\n\n"
      f"[DATABASE GOOGLE SHEET TOKO]:\n{sheet_data}"
  )

  messages = [{"role": "system", "content": context_prompt}]
  messages.extend(history)
  messages.append({"role": "user", "content": user_prompt})

  response = groq_client.chat.completions.create(
      model=GROQ_MODEL,
      messages=messages,
  )
  return response.choices[0].message.content


def ask_gemini_with_context(chat_id: int, user_prompt: str, sheet_data: str) -> str:
  history = get_conversation_history(chat_id)
  formatted_history = ""
  for h in history:
    role = "User" if h["role"] == "user" else "Asisten"
    formatted_history += f"{role}: {h['content']}\n"

  context_prompt = (
      f"[DATABASE GOOGLE SHEET TOKO]:\n{sheet_data}\n\n"
      f"{formatted_history}User: {user_prompt}\nAsisten:"
  )

  response = gemini_client.models.generate_content(
      model=GEMINI_MODEL,
      contents=context_prompt,
      config={"system_instruction": SYSTEM_PROMPT},
  )
  return response.text


def ask_ai_with_memory_and_db(chat_id: int, user_prompt: str) -> str:
  """Coba Groq dulu dengan memory + database Sheet, fallback ke Gemini jika gagal."""
  sheet_data = ambil_database_sheets()

  providers = []
  if groq_client:
    providers.append(
        ("Groq", lambda p: ask_groq_with_context(chat_id, p, sheet_data))
    )
  if gemini_client:
    providers.append(
        ("Gemini", lambda p: ask_gemini_with_context(chat_id, p, sheet_data))
    )

  if not providers:
    raise RuntimeError("Belum ada API key (GROQ_API_KEY / GEMINI_API_KEY).")

  last_error = None
  for name, fn in providers:
    try:
      text = fn(user_prompt)
      if text:
        return text
    except Exception as e:
      last_error = e
      print(f"{name} gagal: {e}")

  raise last_error or RuntimeError("Semua penyedia AI tidak memberi jawaban.")


async def process_update(data):
  async with Bot(TOKEN) as bot:
    update = Update.de_json(data, bot)

    if not update.message or not update.message.text:
      return

    chat_id = update.message.chat_id
    user_message = update.message.text.strip()

    if user_message.startswith("/start"):
      # Reset memory saat /start diketik
      if chat_id in chat_histories:
        chat_histories[chat_id] = []

      await bot.send_message(
          chat_id=chat_id,
          text=(
              "Halo! Selamat datang di layanan **i Cell GadgetFix**.\n\n"
              "Silakan tanyakan apa saja:\n"
              "• Cek status servis (Kirim nomor nota / nama)\n"
              "• Cek harga sparepart & ongkos pasang\n"
              "• Konsultasi kerusakan handphone"
          ),
      )
      return
    if user_message.startswith("/"):
      return

    try:
      # Kirim pesan user ke AI dengan membawa Memory chat dan Data Google Sheet
      reply_text = await asyncio.to_thread(
          ask_ai_with_memory_and_db, chat_id, user_message
      )

      # Simpan interaksi ke memory
      add_to_history(chat_id, "user", user_message)
      add_to_history(chat_id, "assistant", reply_text)

    except Exception as e:
      print("Error pemrosesan pesan:", e)
      reply_text = (
          "Maaf, server sedang sibuk atau gagal memproses data. Coba kirim lagi"
          " beberapa saat lagi ya."
      )

    await bot.send_message(chat_id=chat_id, text=reply_text[:4096])


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
    self.wfile.write(
        b"Bot Telegram i Cell GadgetFix (Memory + Multi-Mode + Sheets) Berjalan!"
    )
