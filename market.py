"""
market.py — orkestrator chat pool.

Inti yang divalidasi di sini:
  1. POOL        : satu ruang bersama yang semua tokoh lihat (= "pasar").
  2. SUTRADARA   : otak orkestrasi. Tiap beat, dia menilai relevansi tiap tokoh
                   lalu memilih SATU yang bicara (atau menunggu manusia).
  3. ANTI-LOOP   : batasi giliran agent beruntun supaya tidak saling balas tanpa henti.
  4. MANUSIA     : kamu bisa nyelonong kapan saja; itu otomatis me-reset prioritas.

Catatan penting soal "diskusi vs handover":
  Di sini agent HANYA boleh menghasilkan satu pesan percakapan per giliran, lalu
  melepas giliran. Mereka TIDAK punya tool eksekusi. Itulah yang menegakkan prinsip
  "diskusi dulu, bukan menyerahkan task ke agent" — bukan sekadar konvensi UI.
  Nanti, "gate" eksekusi tinggal: kalau MANUSIA mengetik approve -> state berubah ->
  tool baru di-unlock. Pasar ini adalah mode 'discussion' tanpa gate apa pun.
"""

import os

from dotenv import load_dotenv

from llm import BASE_URL, chat, check_connection, extract_json
import scenario

load_dotenv()

DIRECTOR_MODEL = os.getenv("DIRECTOR_MODEL") or os.getenv("AGENT_MODEL", "deepseek/deepseek-v3:free")
AGENT_MODEL = os.getenv("AGENT_MODEL", "deepseek/deepseek-v3:free")
HUMAN_NAME = os.getenv("HUMAN_NAME", "Kamu")
MAX_STREAK = int(os.getenv("MAX_AGENT_STREAK", "4"))
AUTO_CHAIN_BEATS = int(os.getenv("AUTO_CHAIN_BEATS", str(MAX_STREAK)))
CONTEXT_TURNS = 14
SCENE_EVENT_KEYWORDS = (
    "aktivitas",
    "berjalan",
    "buka pasar",
    "hidup",
    "interaksi",
    "lanjutkan",
    "mulai",
    "pasar sudah buka",
)


# --------------------------------------------------------------------------- #
# POOL — ruang bersama
# --------------------------------------------------------------------------- #
class Pool:
    def __init__(self):
        self.messages = []  # {"speaker", "content", "kind"}

    def add(self, speaker, content, kind="agent"):
        self.messages.append({"speaker": speaker, "content": content, "kind": kind})

    def transcript(self, n=CONTEXT_TURNS):
        rows = self.messages[-n:]
        return "\n".join(f"{m['speaker']}: {m['content']}" for m in rows) or "(belum ada percakapan)"


# --------------------------------------------------------------------------- #
# SUTRADARA — otak orkestrasi (satu panggilan murah per beat)
# --------------------------------------------------------------------------- #
def run_director(pool, agents, streak):
    roster = "\n".join(
        f"- {a['name']} ({a['role']}) — ikut bicara kalau: {a['trigger']}"
        for a in agents
    )
    world_rules = getattr(scenario, "WORLD_RULES", "").strip()
    system = (
        "Kamu SUTRADARA percakapan sebuah pasar. Tugasmu memutuskan SIAPA yang paling "
        "pantas bicara berikutnya, berdasarkan peran & pemicu (trigger) tiap tokoh serta "
        "isi percakapan terakhir.\n"
        f"\nATURAN DUNIA:\n{world_rules or '(tidak ada aturan dunia tambahan)'}\n\n"
        "Aturan:\n"
        "- Hanya SATU tokoh bicara per giliran.\n"
        "- Tokoh hanya bicara kalau pemicunya benar-benar relevan dengan situasi sekarang.\n"
        "- Pesan dari 'Situasi' adalah perubahan dunia, bukan ucapan pembeli. Kalau Situasi "
        "meminta pasar dibuka, aktivitas dimulai, atau interaksi dilanjutkan, pilih tokoh "
        "yang wajar menginisiasi percakapan (biasanya pembeli mulai melihat-lihat, atau "
        "penjual menawarkan dagangan).\n"
        "- Setelah satu tokoh menginisiasi, lanjutkan respons tokoh lain yang relevan supaya "
        "percakapan benar-benar bergerak sampai natural berhenti.\n"
        "- Kalau pembeli bertanya 'ada yang jual ...?' atau mencari kategori barang, pilih "
        "tokoh penjual yang paling relevan dengan barang itu, walaupun pembeli tidak "
        "menyebut nama tokohnya.\n"
        "- Jangan berhenti hanya karena satu transaksi selesai. Kalau Acely belum menyatakan "
        "selesai belanja, prioritaskan Acely untuk menghitung sisa uang/lanjut melihat-lihat, "
        "atau penjual lain untuk menawarkan barang lanjutan.\n"
        "- Kalau Acely menyebut uangnya kurang/habis, prioritaskan Areku. Kalau Areku sudah "
        "memberi uang dan Acely masih mengejar pembelian boros, prioritaskan Areku untuk "
        "menghentikan belanja.\n"
        "- Kalau penjual menawarkan paket yang tampaknya lebih mahal dari sisa uang Acely, "
        "jangan berhenti. Pilih Acely agar ia menyatakan uangnya kurang, lalu pilih Areku "
        "pada beat berikutnya.\n"
        "- Hindari memilih tokoh yang baru saja bicara berturut-turut kalau tidak perlu.\n"
        "- Kalau tidak ada yang benar-benar perlu bicara (situasi menunggu manusia), "
        "set speaker = null.\n\n"
        "Balas HANYA JSON valid, tanpa penjelasan tambahan, dengan format:\n"
        '{"scores":[{"name":"Nama","priority":0-10,"reason":"singkat"}],"speaker":"Nama atau null"}'
    )
    hint = ""
    if streak >= MAX_STREAK:
        hint = (
            f"\nCATATAN: sudah {streak} giliran agent beruntun. Pertimbangkan berhenti "
            "(speaker=null) untuk memberi ruang manusia, kecuali ada yang benar-benar mendesak."
        )
    user = (
        f"TOKOH:\n{roster}\n\n"
        f"PERCAKAPAN TERAKHIR:\n{pool.transcript()}{hint}\n\n"
        "Siapa yang bicara berikutnya?"
    )
    raw = chat(DIRECTOR_MODEL, system, user, temperature=0.2, max_tokens=400)
    return extract_json(raw)


# --------------------------------------------------------------------------- #
# AGENT — menghasilkan SATU ucapan, lalu melepas giliran
# --------------------------------------------------------------------------- #
def agent_speak(agent, pool):
    rules = "\n".join(f"- {r}" for r in agent.get("rules", [])) or "- (tidak ada)"
    world_rules = getattr(scenario, "WORLD_RULES", "").strip()
    system = (
        f"Kamu adalah {agent['name']}, {agent['role']}.\n\n"
        f"ATURAN DUNIA:\n{world_rules or '(tidak ada aturan dunia tambahan)'}\n\n"
        f"KARAKTER & KEBIASAAN:\n{agent['persona']}\n\n"
        f"ATURAN KERAS (tidak boleh dilanggar):\n{rules}\n\n"
        f"KAPAN KAMU BICARA:\n{agent['trigger']}\n\n"
        "Kamu sedang berada di sebuah pasar bersama orang lain. Ini fase interaksi: kamu "
        "HANYA bisa berbicara, tidak bisa melakukan aksi nyata apa pun selain mengobrol. "
        "Bicaralah natural, singkat (1-2 kalimat), sesuai karakter, dalam bahasa Indonesia. "
        "Jangan menulis narasi panjang; cukup ucapanmu saja."
    )
    user = (
        f"PERCAKAPAN DI PASAR:\n{pool.transcript()}\n\n"
        f"Sekarang giliranmu bicara sebagai {agent['name']}. Apa yang kamu katakan?"
    )
    return chat(agent.get("model", AGENT_MODEL), system, user, temperature=0.85, max_tokens=200)


# --------------------------------------------------------------------------- #
# BEAT — satu langkah: sutradara memilih, lalu tokoh bicara
# --------------------------------------------------------------------------- #
def find_agent(agents, name):
    for a in agents:
        if a["name"].lower() == str(name).lower():
            return a
    return None


def step(pool, agents, streak, show_scores=True):
    """Return (spoke: bool, new_streak: int)."""
    try:
        data = run_director(pool, agents, streak)
    except Exception as e:  # noqa: BLE001
        print(f"  [error] sutradara gagal dipanggil: {e}")
        return False, streak

    if not data:
        print("  [sutradara] respons tidak valid (bukan JSON). Giliranmu.")
        return False, 0

    if show_scores and data.get("scores"):
        print("  [sutradara] penilaian relevansi:")
        for s in sorted(data["scores"], key=lambda x: -(x.get("priority") or 0)):
            print(f"     {str(s.get('name')):8} {str(s.get('priority')):>2}/10  {s.get('reason', '')}")

    speaker_name = data.get("speaker")
    if not speaker_name or str(speaker_name).lower() in ("null", "none", ""):
        print("  [sutradara] pasar lagi sepi — menunggu kamu. Ketik sesuatu untuk ikut.")
        return False, 0

    agent = find_agent(agents, speaker_name)
    if not agent:
        print(f"  [sutradara] memilih '{speaker_name}' tapi tokoh itu tidak ada. Dilewati.")
        return False, streak

    try:
        msg = agent_speak(agent, pool)
    except Exception as e:  # noqa: BLE001
        print(f"  [error] {agent['name']} gagal dipanggil: {e}")
        return False, streak

    pool.add(agent["name"], msg, kind="agent")
    print(f"\n  {agent['name']}: {msg}\n")
    return True, streak + 1


def run_beats(pool, agents, count, show_scores=True, streak=0):
    """Run several beats until the market goes quiet or anti-loop hands back."""
    for _ in range(count):
        spoke, streak = step(pool, agents, streak, show_scores)
        if not spoke:
            return 0
        if streak >= MAX_STREAK:
            print(f"  [anti-loop] {streak} giliran agent beruntun — berhenti, giliranmu.")
            return 0
    return streak


def is_scene_event(text):
    lowered = text.lower()
    return any(keyword in lowered for keyword in SCENE_EVENT_KEYWORDS)


# --------------------------------------------------------------------------- #
# REPL
# --------------------------------------------------------------------------- #
HELP = """
Perintah:
  [Enter]/n   jalankan 1 beat (sutradara pilih 1 tokoh untuk bicara)
  angka       jalankan beberapa beat otomatis, mis. 4
  go [n]      jalankan n beat otomatis (default: Auto run); berhenti kalau sepi / anti-loop
  <teks>      kirim pesan sebagai MANUSIA, lalu pasar lanjut otomatis beberapa beat
  who         daftar tokoh + trigger-nya
  log         seluruh isi percakapan
  quiet/loud  sembunyikan / tampilkan penilaian sutradara
  help        bantuan ini
  q           keluar
"""


def main():
    agents = scenario.AGENTS
    pool = Pool()
    show_scores = True
    streak = 0

    print("=" * 64)
    print(" PASAR — chat pool: human + AI agent hidup bareng")
    print(f" Endpoint : {BASE_URL}")
    print(f" Director : {DIRECTOR_MODEL}")
    print(f" Agent    : {AGENT_MODEL}")
    print(f" Auto run : {AUTO_CHAIN_BEATS} beat setelah manusia bicara")
    print(f" Loop cap : {MAX_STREAK} giliran agent beruntun")
    ok, detail = check_connection()
    if ok:
        print(f" Status   : 9Router siap ({detail})")
    else:
        print(" Status   : 9Router belum bisa dihubungi")
        print(f"            {detail}")
    print("=" * 64)
    print(HELP)

    if scenario.OPENING and scenario.OPENING.get("content"):
        pool.add(scenario.OPENING["speaker"], scenario.OPENING["content"], kind="agent")
        print(f"  {scenario.OPENING['speaker']}: {scenario.OPENING['content']}\n")

    while True:
        try:
            cmd = input("» ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nDadah!")
            break

        low = cmd.lower()

        if low in ("q", "quit", "exit"):
            print("Dadah!")
            break
        elif low in ("help", "?"):
            print(HELP)
        elif low == "who":
            for a in agents:
                print(f"  {a['name']:8} {a['role']:28} trigger: {a['trigger']}")
        elif low == "log":
            print(pool.transcript(n=9999))
        elif low == "quiet":
            show_scores = False
            print("  (penilaian sutradara disembunyikan)")
        elif low == "loud":
            show_scores = True
            print("  (penilaian sutradara ditampilkan)")
        elif cmd == "" or low in ("n", "next"):
            _, streak = step(pool, agents, streak, show_scores)
        elif low.isdigit():
            streak = run_beats(pool, agents, int(low), show_scores, streak=0)
        elif low.startswith("go"):
            parts = low.split()
            n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else AUTO_CHAIN_BEATS
            streak = run_beats(pool, agents, n, show_scores, streak=0)
        else:
            # Instruksi suasana diperlakukan sebagai world event, bukan ucapan pembeli.
            if is_scene_event(cmd):
                pool.add("Situasi", cmd, kind="scene")
            else:
                pool.add(HUMAN_NAME, cmd, kind="human")
            streak = run_beats(pool, agents, AUTO_CHAIN_BEATS, show_scores, streak=0)


if __name__ == "__main__":
    main()
