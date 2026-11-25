# Pasar — Chat Pool (Human + AI Agent)

Prototipe kecil untuk memvalidasi **kernel orkestrasi** Agentic Work Vibe:
satu ruang bersama (pool) tempat beberapa AI agent dan kamu (manusia) hidup
dan ngobrol. Murni percakapan, nol eksekusi — sengaja, supaya kita bisa menguji
bagian tersusah (giliran bicara, persona, trigger, anti-loop) tanpa backend rumit.

Analogi: sebuah **pasar**. Atero (penjual sayur), Anola (penjual buah),
Acely (pembeli hemat), Budi (petugas pasar), dan Areku (teman Acely yang
muncul *hanya kalau* uang Acely habis). Kehidupan & percakapan muncul sendiri
dari interaksi — bukan diatur kaku.

---

## Setup

```bash
cd agentic-market
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # lalu sesuaikan model & endpoint kalau perlu
python market.py
```

Pastikan **9router jalan** di `http://localhost:20128/v1`. ID model di `.env`
mengikuti alias yang tampil dari endpoint lokalmu. Cek cepat:

```bash
curl http://localhost:20128/v1/models
```

Di setup lokal ini default-nya memakai `ds/deepseek-chat`, karena alias itu sudah
terdeteksi aktif. Kalau kamu mau pakai OpenRouter free models, aktifkan credential
OpenRouter di 9router dulu lalu ganti `DIRECTOR_MODEL` / `AGENT_MODEL` ke alias
yang tampil, biasanya berprefix `openrouter/...`.

> Free tier OpenRouter dibatasi ~20 req/menit. Tiap "beat" = ~2 panggilan
> (1 sutradara + 1 agent), jadi sudah ada retry + fallback otomatis di `llm.py`.

---

## Cara pakai (REPL)

| Perintah     | Aksi |
|--------------|------|
| `[Enter]` / `n` | jalankan 1 beat — sutradara memilih 1 tokoh untuk bicara |
| `5`          | jalankan 5 beat otomatis |
| `go` / `go 5`| jalankan beberapa beat otomatis; `go` mengikuti `AUTO_CHAIN_BEATS` |
| `<teks>`     | kirim pesan sebagai **manusia**, lalu pasar lanjut otomatis beberapa beat |
| `who`        | daftar tokoh + trigger-nya |
| `log`        | seluruh percakapan |
| `quiet`/`loud`| sembunyikan / tampilkan penilaian sutradara |
| `q`          | keluar |

Coba: ketik `go 4`, amati pasar hidup. Lalu nyelonong:
`Bu, sayur bayamnya sekilo berapa?` — lihat siapa yang nanggepin.
Untuk memicu Areku, dorong Acely sampai belanjaannya lewat Rp50.000.

Kalau pasar terasa terlalu cepat atau terlalu pendek setelah kamu bicara, ubah
`AUTO_CHAIN_BEATS` di `.env`.

---

## Cara kerja orkestrasi

**1. Pool** (`market.py` → `Pool`) — satu log pesan yang semua tokoh lihat.

**2. Sutradara** (`run_director`) — otak orkestrasi, satu panggilan murah per beat.
Dia melihat transkrip + roster (peran & trigger tiap tokoh), lalu mengembalikan
skor relevansi tiap tokoh dan memilih **satu** yang bicara — atau `null` kalau
situasinya menunggu manusia. Output skor ini sengaja ditampilkan supaya kamu bisa
*melihat* alasan keputusannya (itu "control room" dalam bentuk teks).

**3. Agent bicara** (`agent_speak`) — tokoh terpilih menghasilkan **satu** ucapan
sesuai persona + rules, lalu **melepas giliran**. Tidak ada tool eksekusi.

**4. Anti-loop** — batas `MAX_AGENT_STREAK` giliran agent beruntun. Lewat itu,
loop berhenti dan menyerahkan giliran ke manusia. Sutradara juga didorong yield.

**5. Manusia** — pesan manusia me-reset streak dan otomatis memicu beberapa beat
pendek (`AUTO_CHAIN_BEATS`), jadi percakapan terasa berjalan tanpa harus selalu
menekan Enter.

---

## Mengubah "kehidupan" pasar

Semua tombolnya ada di **`scenario.py`** (tidak perlu menyentuh `market.py`).
Tiap tokoh punya tiga lapis:

- **persona** — pola pikir + kebiasaan (naratif; bikin dia *terasa* berkarakter)
- **rules** — aturan keras yang tidak boleh dilanggar (pagar)
- **trigger** — kapan dia merasa perlu bicara (kondisi relevansi)

Tambah tokoh = tambah satu dict. Ganti pasar jadi kantor, ruang rapat, apa pun.

---

## Jembatan ke Agentic Work Vibe

Pasar ini = mode **`discussion`** murni. Yang menegakkan prinsip *"diskusi dulu,
bukan menyerahkan task ke agent"* cuma dua hal mekanis:

1. agent hanya boleh **satu giliran ngomong**, lalu yield; dan
2. **tidak ada tool** sampai sebuah **gate** dilewati manusia.

Untuk menumbuhkan ini ke PRD/RFC/Kanban nanti, tinggal tambahkan **state** pada
pool (mis. `discussion → prd_review → approved → executing`) dan sebuah gate:
ketika **manusia** mengetik approve, state berubah dan tool eksekusi baru di-unlock.
Trigger & sutradara yang sama tetap dipakai — hanya bertambah aturan: *move apa
yang boleh, dan kapan eksekusi terbuka.*
