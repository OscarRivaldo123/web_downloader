# Unduhin — Pengunduh Video & Audio (YouTube · Instagram · TikTok)

Web app lokal untuk mengunduh video (MP4) dan audio (MP3) dari tautan **YouTube**, **Instagram**, dan **TikTok** — lengkap dengan pratinjau thumbnail, pilihan resolusi/bitrate, dan estimasi ukuran file sebelum diunduh.

Dibangun dengan **Python (FastAPI) + yt-dlp** di backend, dan HTML/CSS/JS murni di frontend (tanpa framework, ringan).

## Fitur

- Analisis tautan otomatis: judul, pembuat, durasi, dan pratinjau thumbnail
- **MP4** dari 144p hingga 4K — ukuran tiap resolusi tampil sebelum diunduh
- **MP3** 64–320 kbps — ukuran tiap bitrate tampil sebelum diunduh
- TikTok diunduh tanpa watermark
- Progres unduhan real-time (bar persen) + status "Memproses…" saat konversi
- Riwayat unduhan per sesi, tombol simpan ulang
- File sementara di server lokal dihapus otomatis setelah 20 menit
- Tanpa iklan, tanpa akun, berjalan sepenuhnya di komputermu

## Cara menjalankan

### Pertama kali
1. Pastikan **Python 3.10+** terpasang.
2. Jalankan `setup.bat` (membuat venv, memasang dependensi, mengunduh ffmpeg bila belum ada).

### Setiap hari
Jalankan `start.bat` — server menyala di `http://127.0.0.1:8000` dan browser terbuka otomatis.

### Manual (tanpa bat)
```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

> ffmpeg dibundel di folder `bin/`. Jika ffmpeg sudah ada di sistem, folder ini boleh dikosongkan.

## Konten privat / berbatas usia

Beberapa konten Instagram/TikTok/YouTube meminta login. Ekspor cookies browser kamu (format **Netscape**, misalnya lewat ekstensi "Get cookies.txt") ke file `cookies.txt` di folder aplikasi — yt-dlp akan memakainya secara otomatis.

## Struktur proyek

```
app.py            Backend FastAPI (API info/prepare/task/file/thumbnail)
static/           Frontend (index.html, style.css, app.js)
bin/              ffmpeg & ffprobe (bundel lokal)
downloads/        File sementara (dibersihkan otomatis)
venv/             Virtual environment Python
```

## Catatan

- Akun privat, konten yang sudah dihapus, dan pemblokiran wilayah tidak bisa diunduh.
- Gunakan hanya untuk konten milikmu sendiri atau berlisensi bebas — hormati hak cipta pencipta.
