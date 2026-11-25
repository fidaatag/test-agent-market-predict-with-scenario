"""
llm.py — koneksi tipis ke 9router (OpenAI-compatible).

9router itu proxy lokal yang ngomong "bahasa" OpenAI, jadi kita pakai
SDK `openai` biasa, cuma base_url-nya diarahkan ke 9router.

Ada retry + fallback model otomatis karena model :free di OpenRouter
sering kena rate-limit (429).
"""

import os
import re
import json
import time

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:20128/v1")
API_KEY = os.getenv("LLM_API_KEY", "sk-no-key-needed")  # 9router lokal biasanya cuek soal key
TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "20"))

client = OpenAI(base_url=BASE_URL, api_key=API_KEY, timeout=TIMEOUT_SECONDS)

# Daftar model cadangan kalau model utama gagal / kena 429. Diisi dari .env.
FALLBACKS = [m.strip() for m in os.getenv("FALLBACK_MODELS", "").split(",") if m.strip()]


def check_connection():
    """Return (ok, detail) for the configured OpenAI-compatible endpoint."""
    try:
        models = client.models.list()
        names = [getattr(m, "id", "") for m in getattr(models, "data", [])[:5]]
        detail = ", ".join(n for n in names if n) or "endpoint merespons"
        return True, detail
    except Exception as e:  # noqa: BLE001 - startup diagnostic only
        return False, str(e)


def chat(model, system, user, temperature=0.7, max_tokens=400, retries=2):
    """
    Satu panggilan chat sederhana (system + user -> teks).
    Coba model utama dulu; kalau gagal, geser ke FALLBACKS.
    """
    candidates = [model] + [m for m in FALLBACKS if m != model]
    last_err = None

    for m in candidates:
        for attempt in range(retries):
            try:
                resp = client.chat.completions.create(
                    model=m,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                content = resp.choices[0].message.content
                if content and content.strip():
                    return content.strip()
            except Exception as e:  # noqa: BLE001 - kita memang mau nangkap semua
                last_err = e
                msg = str(e).lower()
                if "429" in msg or "rate" in msg:
                    time.sleep(2 + attempt * 2)  # backoff kecil
                else:
                    break  # error lain: langsung coba model berikutnya

    raise RuntimeError(f"Panggilan LLM gagal untuk '{model}' (+fallback): {last_err}")


def extract_json(text):
    """
    Ambil objek JSON pertama dari respons LLM yang mungkin berantakan
    (kadang ada ```json ... ``` atau kalimat pembuka).
    Return dict, atau None kalau gagal.
    """
    if not text:
        return None
    text = re.sub(r"```(?:json)?", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start:end + 1])
    except Exception:  # noqa: BLE001
        return None
