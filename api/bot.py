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

# SYSTEM PROMPT KETAT (Hanya fokus pada servis HP & menolak topik luar)
SYSTEM_PROMPT = (
    "Kamu adalah asisten AI resmi untuk toko servis HP 'i Cell GadgetFix'. "
    "Tugas utamamu HANYA menjawab pertanyaan seputar layanan servis handphone, "
    "cek status perbaikan nota, konsultasi kerusakan hardware/software HP, estimasi biaya, "
    "serta informasi jam operasional dan lokasi toko.\n\n"
    "ATURAN KETAT:\n"
    "1. DILARANG KERAS menjawab pertanyaan di luar topik servis HP atau toko (seperti politik, "
    "pemrograman umum, resep masakan, PR sekolah, percintaan, atau topik umum lainnya).\n"
    "2. Jika pengguna bertanya di luar topik servis HP, tolak dengan sopan dan arahkan kembali "
    "ke layanan servis HP. Contoh penolakan: 'Maaf, saya adalah asisten khusus konter servis HP i Cell GadgetFix. "
    "Saya hanya bisa membantu hal-hal yang berkaitan dengan perbaikan dan servis handphone Anda.'\n"
    "3. Ingat konteks percakapan sebelumnya dengan pengguna jika diperlukan.\n"
    "4. Jawab dalam bahasa yang ramah, singkat, dan jelas."
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
# MEMORY STORAGE (Penyimpanan Riwayat Chat Sementara)
# ---------------------------------------------------------------
chat_histories = {}
MAX_HISTORY = 6  # Batasi maksimal 6 pesan terakhir agar hemat token


def get_conversation_history(chat_id: int):
  if chat_id not in chat_histories:
    chat_histories[chat_id] = []
  return chat_histories[chat_id]


def add_to_history(chat_id: int, role: str, content: str):
  history = get_conversation_history(chat_id)
  history.append({"role": role, "content": content})
  if len(history) > MAX_HISTORY:
    chat_histories[chat_id] = history[-MAX_HISTORY:]


def cari_status_ke_sheets(query: str) -> str:
  """Mencari data status servisan dari Google Sheets via Webhook."""
  if not SHEETS_WEBHOOK_URL:
    return None
  try:
    response = requests.get(
        SHEETS_WEBHOOK_URL,
        params={
            "action": "search",
            "query": query,
            "secret_token": SECRET_TOKEN,
        },
        timeout=5,
    )
    data = response.json()
    if data.get("found"):
      return (
          f"🔍 Data Servis Ditemukan:\n\n"
          f"• ID Servis: {data.get('serviceId')}\n"
          f"• Pelanggan: {data.get('customerName')}\n"
          f"• Perangkat: {data.get('deviceModel')}\n"
          f"• Status: {data.get('status')}\n"
          f"• Total Biaya: Rp {data.get('totalPrice')}"
      )
    else:
      return None
  except Exception as e:
    print("Gagal akses Google Sheets:", e)
    return None


def ask_groq_with_memory(chat_id: int, user_prompt: str) -> str:
  history = get_conversation_history(chat_id)

  messages = [{"role": "system", "content": SYSTEM_PROMPT}]
  messages.extend(history)
  messages.append({"role": "user", "content": user_prompt})

  response = groq_client.chat.completions.create(
      model=GROQ_MODEL,
      messages=messages,
  )
  return response.choices[0].message.content


def ask_gemini_with_memory(chat_id: int, user_prompt: str) -> str:
  history = get_conversation_history(chat_id)
  formatted_history = ""
  for h in history:
    role = "User" if h["role"] == "user" else "Asisten"
    formatted_history += f"{role}: {h['content']}\n"

  prompt_gabungan = (
      f"{formatted_history}User: {user_prompt}\nAsisten:"
  )

  response = gemini_client.models.generate_content(
      model=GEMINI_MODEL,
      contents=prompt_gabungan,
      config={"system_instruction": SYSTEM_PROMPT},
  )
  return response.text


def ask_ai_with_memory(chat_id: int, user_prompt: str) -> str:
  """Coba Groq dulu dengan memory, kalau gagal pindah ke Gemini."""
  providers = []
  if groq_client:
    providers.append(("Groq", lambda p: ask_groq_with_memory(chat_id, p)))
  if gemini_client:
    providers.append(("Gemini", lambda p: ask_gemini_with_memory(chat_id, p)))

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
      # Reset memory saat /start ditekan
      if chat_id in chat_histories:
        chat_histories[chat_id] = []

      await bot.send_message(
          chat_id=chat_id,
          text=(
              "Halo! Selamat datang di layanan i Cell GadgetFix. "
              "Kirimkan nomor nota atau nama Anda untuk mengecek status servis HP, "
              "atau tanyakan seputar perbaikan handphone."
          ),
      )
      return
    if user_message.startswith("/"):
      return

    try:
      # 1. Cek database Google Sheets terlebih dahulu
      sheet_result = await asyncio.to_thread(
          cari_status_ke_sheets, user_message
      )

      if sheet_result:
        reply_text = sheet_result
        add_to_history(chat_id, "user", user_message)
        add_to_history(chat_id, "assistant", reply_text)
      else:
        # 2. Jika tidak ada di Sheets, lempar ke AI dengan membawa Memory
        reply_text = await asyncio.to_thread(
            ask_ai_with_memory, chat_id, user_message
        )
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
        b"Bot Telegram i Cell GadgetFix (Memory + Rules + Sheets) Berjalan!"
    )
