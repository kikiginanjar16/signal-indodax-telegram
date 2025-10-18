## Indodax Signal Telegram Bot

Bot ringan untuk memantau pergerakan harga coin di Indodax dan mengirimkan alert / ringkasan ke Telegram. Mendukung insight tambahan via OpenRouter (opsional).

---

### Fitur
- Pantau beberapa pair Indodax sekaligus (default: `mogidr`, `pepeidr`, `ucjlidr`, `twelveidr`).
- Kirim alert Telegram ketika perubahan harga melebihi threshold yang ditentukan.
- Kirim ringkasan berkala (opsional) lengkap dengan high/low 24 jam.
- Integrasi OpenRouter untuk insight singkat (opsional).

---

### Prasyarat
- Python 3.10+
- Token bot Telegram dan ID chat target.
- (Opsional) API key OpenRouter jika ingin insight AI.

---

### Konfigurasi Environment
1. Duplikasi file contoh environment:
   ```bash
   cp .env.example .env
   ```
2. Isi nilai berikut pada `.env`:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `COINS` (opsional, koma-separator tanpa spasi; tiap coin otomatis ditambahkan akhiran `idr`)
   - `POLL_INTERVAL_SEC`, `ALERT_THRESHOLD_PCT`, `SEND_INTERVAL_MIN` untuk pengaturan ritme bot.
   - `OPENROUTER_API_KEY` & `OPENROUTER_MODEL` bila ingin insight tambahan.

---

### Menjalankan Secara Lokal
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Bot akan melakukan polling sesuai interval yang ditentukan. Tekan `Ctrl+C` untuk berhenti.

---

### Menjalankan via Docker
```bash
docker build -t indodax-signal .
docker run --env-file .env indodax-signal
```

Jika ingin override variabel langsung:
```bash
docker run -e TELEGRAM_BOT_TOKEN=xxx -e TELEGRAM_CHAT_ID=yyy indodax-signal
```

---

### Troubleshooting
- **Tidak ada pesan Telegram**: pastikan token/chat ID benar dan bot sudah diundang ke chat/kanal.
- **Insight OpenRouter kosong**: cek apakah `OPENROUTER_API_KEY` valid. Tanpa API key, bagian insight otomatis dilewati.
- **Polling terlalu cepat/lambat**: sesuaikan `POLL_INTERVAL_SEC` dan `ALERT_THRESHOLD_PCT` di `.env`.

---
Happy trading (secara bertanggung jawab)!
