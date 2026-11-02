# Ruang Tumbuh

**Status: PR #15 sudah merged ke `main` pada `825452f`; release belum dinyatakan siap untuk data keluarga nyata.** Core database/build telah diuji melalui CI. Live Telegram/provider, hosting TLS, pengelolaan kunci dan acceptance klinis tetap perlu bukti. Lihat [peta implementasi dan runbook](docs/REVIEW-IMPLEMENTATION.md).

Backend menggunakan Python/FastAPI dan PostgreSQL; proses migrasi dan worker berjalan terpisah. Pilihan ini menjaga satu basis kode dan transaksi database. Agent dan parser chat masih terbatas; rencana dan gap tersedia di [IMPLEMENTATION.md](IMPLEMENTATION.md). Referensi WHO dinonaktifkan sampai data dan perhitungan tervalidasi; lihat [catatan validasi, sumber, dan lisensi WHO](docs/WHO-growth-validation.md).

## Menjalankan fondasi secara lokal

1. Salin `.env.example` ke `.env`, lalu batasi akses file dengan `chmod 600 .env`. Isi `POSTGRES_PASSWORD` dengan nilai acak panjang yang hanya mengandung huruf, angka, `_`, atau `-`, lalu buat `APP_DATA_ENCRYPTION_KEY` dengan `openssl rand -base64 32`. Simpan salinan kunci secara terpisah dan terlindungi; kehilangan kunci membuat kolom terenkripsi tidak dapat dibaca. Jangan bagikan atau commit `.env`.
2. Untuk data sintetis saja, set `APP_ENV=development` dan `DEV_AUTH_ENABLED=1`. Ini memungkinkan siapa pun yang dapat mengakses server menyamar sebagai pengguna apa pun. Jangan buka server atau database ke jaringan.
3. Jalankan `docker compose up --build -d`. API hanya diikat ke `127.0.0.1:8000`; `curl http://127.0.0.1:8000/ready` memeriksa database dan skema dasar.
4. `docker compose logs api` menampilkan status tanpa access log. `docker compose down` menghentikan container dan mempertahankan volume database. Jangan gunakan `down -v` jika data perlu dipertahankan.

Buka `http://127.0.0.1:8000/` untuk Mini App. Mode pengembangan menyediakan login dengan ID sintetis. Tampilan mendukung profil anak, undangan, peran, catatan, ringkasan harian, ekspor dan preferensi check-in; belum semua alur PRD tersedia. Pada Telegram, Mini App memerlukan domain HTTPS dan validasi `initData`; penggunaan dengan Telegram nyata belum diuji.

## Hosting nonkomersial dengan HTTPS

Siapkan host yang dapat dijangkau publik, arahkan DNS `APP_DOMAIN` ke alamat host, dan izinkan koneksi masuk TCP pada port 80 dan 443. Isi `APP_DOMAIN` di `.env`, pastikan `APP_ENV=production` dan `DEV_AUTH_ENABLED=0`, lalu jalankan `docker compose -f compose.yaml -f compose.hosted.yaml up --build -d`. Caddy memperoleh dan memperbarui sertifikat TLS; data sertifikat disimpan pada volume `caddy_data`. API tetap terbit hanya pada loopback host, sedangkan Caddy meneruskan trafik melalui jaringan internal Compose. Jangan publikasikan port PostgreSQL.

Setelah domain melayani HTTPS, atur URL Mini App bot Telegram ke `https://<domain-anda>`. Untuk menerima pesan lewat polling, pilih `TELEGRAM_TRANSPORT=polling`, isi token bot, dan tambahkan `--profile polling` pada perintah Compose. Hosting, DNS, firewall, kredensial nyata, backup/pemulihan, dan integrasi bot belum diverifikasi di server; konfigurasi ini menyediakan jalur deployment, bukan bukti siap operasi.

Migrasi dijalankan oleh service `migrate` sebelum API. Migrasi 011 mengenkripsi data lama; migrasi 012 mengikat persetujuan AI ke provider/model/endpoint aktif sehingga persetujuan lama perlu diberikan ulang. `APP_DATA_ENCRYPTION_KEY` yang sama wajib tersedia bagi migrasi, API, worker, dan poller. Jangan mengubah file migrasi yang sudah diterapkan; buat migrasi baru. Token bot dapat disetel melalui `TELEGRAM_BOT_TOKEN`; tanpa token, verifikasi Telegram ditolak. Compose hanya memberi kunci API provider kompatibel ke `worker` dan hanya memberi token bot ke service yang memerlukannya. Mode production adalah default dan endpoint identitas palsu tidak tersedia di mode tersebut. Ini belum cukup untuk deployment production.

`TELEGRAM_TRANSPORT` mengatur penerimaan pesan: `disabled` (default), `webhook`, atau `polling`. Untuk polling, atur `TELEGRAM_TRANSPORT=polling`, isi token bot, lalu jalankan `docker compose --profile polling up -d --build`. `TELEGRAM_POLL_TIMEOUT` mengatur long-poll 1–50 detik (default 30); Telegram merekomendasikan timeout positif untuk long-poll dan short polling hanya untuk pengujian ([Bot API `getUpdates`](https://core.telegram.org/bots/api#getupdates)). Timeout koneksi otomatis 10 detik lebih lama. Poller menyimpan offset bersama pesan dalam PostgreSQL dan mengunci satu consumer. Polling dan webhook Telegram saling eksklusif; jika bot masih memiliki webhook, hapus webhook lewat Bot API secara sadar sebelum mengaktifkan polling. Aplikasi tidak menghapus webhook jarak jauh otomatis. Respons Telegram 401 atau 409 dicatat dengan petunjuk aman tanpa token dan dicoba ulang dengan backoff hingga 30 detik. Untuk webhook, pilih `TELEGRAM_TRANSPORT=webhook`, isi `TELEGRAM_WEBHOOK_SECRET`, dan gunakan header `X-Telegram-Bot-Api-Secret-Token` melalui HTTPS.

`TELEGRAM_DELIVERY` mengatur pengiriman balasan terpisah: `disabled` (default), `fake` hanya untuk development, atau `telegram` yang membutuhkan token bot. Pengiriman dengan hasil tidak pasti tidak diulang otomatis karena Telegram mungkin telah menerima pesan. Belum ada uji dengan bot Telegram nyata.

## Provider AI

Untuk hosted production, isi `FAMILY_CREATOR_IDS` dan `AI_FAMILY_IDS` sebelum mengaktifkan AI. Consent anggota tetap diperlukan; batas request dan antrean dijelaskan dalam [runbook](docs/REVIEW-IMPLEMENTATION.md).

Default `AI_PROVIDER=fake` memakai parser deterministik terbatas tanpa koneksi AI eksternal. Untuk memakai layanan penyedia yang kompatibel dengan OpenAI (bukan API OpenAI langsung), set `AI_PROVIDER=openai-compatible`, `AI_BASE_URL` ke URL dasar endpoint langsung (contoh berakhiran `/v1`), `AI_MODEL` yang mendukung Chat Completions function tools, dan `AI_API_KEY` dalam `.env`. Aplikasi menolak `api.openai.com`; gunakan HTTPS, kecuali endpoint loopback lokal. Redirect ditolak agar header API key tidak diteruskan ke URL lain. Periksa kebijakan retensi dan log layanan yang dipilih. Jangan tempel kunci ke chat. AI tidak mengirim pesan keluar sebelum persetujuan per pengguna dan keluarga. Di chat, `/ai aktif` menampilkan penjelasan lalu `/ai setuju` menyetujui; `/ai nonaktif` mencabutnya. Mini App juga memiliki pilihan ini di Pengaturan. Persetujuan tidak diwariskan ke anggota keluarga lain.

Agent berbicara ringkas dalam Bahasa Indonesia dan dibatasi ke pencatatan, pencarian, serta ringkasan data aplikasi. Chat mendukung query periode, daftar kandidat koreksi/hapus, dan pengingat melalui tools aplikasi. Usulan pencatatan perlu dibalas dengan `simpan <nomor>` dalam 24 jam; `batal <nomor>` membatalkan. Database mengesahkan akses dan isi, lalu baru mengonfirmasi setelah commit. Kegagalan provider tidak membuat catatan; formulir Mini App tetap tersedia. Panjang harus dinyatakan diukur berbaring dan tinggi harus dinyatakan diukur berdiri; tanpa posisi yang cocok, chat meminta klarifikasi dan API menolak. Bot tidak memberi diagnosis, dosis, atau kesimpulan pertumbuhan. Izin WHO telah diperoleh melalui ID 202611419. Loader dan perhitungan backend tersedia dengan validasi checksum serta numerical reference checks; aktifkan setelah script validasi referensi berhasil pada server deployment. Workbook tetap server-side dan tidak dikirim ke model eksternal. [Ketentuan aktif](docs/WHO-license-status.md).

Setelah persetujuan, aplikasi mengirim isi pesan (maksimal 4.000 karakter, termasuk catatan aktivitas atau kesehatan anak), waktu pesan, dan zona keluarga ke endpoint AI kompatibel yang dikonfigurasi operator. Nama keluarga/anak, tanggal lahir profil aktif jika disebut sebagai tanggal lahir, serta pola umum email, nomor telepon dan username Telegram, serta alamat berlabel eksplisit seperti alamat rumah: disamarkan sebelum dikirim. Ini bukan anonimisasi lengkap: data pribadi lain yang tidak dikenali dapat tetap terkirim. Retensi dan pencatatan data ditentukan penyedia endpoint; aplikasi tidak mengatur kebijakan tersebut. Periksa kebijakan penyedia sebelum mengaktifkan fitur. Token input/output untuk respons valid tersedia bagi owner melalui `/api/families/{id}/ai-usage`; jumlah ini tidak mencakup semua permintaan gagal atau percobaan terputus, dan bukan biaya terukur. Worker yang berhenti di tengah panggilan dapat memanggil provider kembali dan menimbulkan biaya tambahan. Integrasi dengan layanan provider nyata belum diuji.

Chat mendukung `/daftar Nama keluarga | Nama anak`, `/keluarga`, `/pilih ID_KELUARGA ID_ANAK`, `/undang ID_KELUARGA`, lalu calon anggota mengirim `/start KODE`. `/keluarga` menampilkan ID keluarga dan profil anak untuk dipilih. Pilihan keluarga/profil disimpan per pengguna Telegram dan diverifikasi terhadap keanggotaan aktif setiap kali dipakai; pendaftaran otomatis memilih profil yang baru dibuat. Undangan acak sekali pakai kedaluwarsa dalam 24 jam; kode mentah hanya disimpan sementara untuk retry pengiriman dan dibersihkan setelah dua hari. Pemakaiannya mengikat ke Telegram user ID pengirim.

Check-in harian dan ringkasan harian tersedia di Mini App dan default nonaktif. Ringkasan memilih satu profil anak dan waktu kirim per anggota; pengiriman kedaluwarsa satu jam setelah jadwal. Pengingat buatan pengguna dapat dibuat lewat chat; API preferensi `reminder` belum mengendalikan pengirimannya. Semua notifikasi default nonaktif dan diatur per anggota. Jadwal memakai zona waktu penerima; quiet hours, snooze, pembatalan, batas harian, dan akses diperiksa worker. Pencabutan anggota mematikan persetujuan AI dan notifikasi; undangan baru tidak mengaktifkannya kembali.

## Pengujian

Pasang `requirements-dev.txt` di virtual environment. `TEST_DATABASE_URL=... python -m unittest discover -s tests -v` membutuhkan **database PostgreSQL kosong dan terisolasi**; tes membuat tabel di database tersebut. Jangan arahkan tes ke database pengguna.

## Penghapusan dan retensi

Pemilik dapat mengunduh CSV dengan rentang tanggal dalam zona keluarga. Unduhan memakai sesi dan nilai yang bisa ditafsirkan sebagai formula spreadsheet diberi awalan apostrof. Anggota dapat menyembunyikan catatan setelah konfirmasi; audit dan backup tetap dapat memuatnya. Penghapusan keluarga memerlukan permintaan khusus dan konfirmasi `HAPUS KELUARGA` dalam 10 menit. Profil, catatan, preferensi, undangan, pekerjaan dan audit keluarga yang terhubung di database aktif dihapus; anggota lain serta keluarga lain tidak dihapus. Bukti minimal berisi ID keluarga, ID pelaku, hash token, dan waktu disimpan 90 hari agar pengulangan aman.

Isi pesan inbound disamarkan segera setelah pemrosesan selesai atau gagal permanen; teks draft ambigu tidak disimpan. Update yang masih dapat dicoba ulang tetap disimpan terenkripsi. `CHAT_CONTENT_RETENTION_DAYS` (1–30, default 7) mengatur usia maksimum payload inbound serta isi respons terminal; update pending atau processing dengan lease kedaluwarsa yang melewati batas ditandai gagal dan payload-nya disamarkan. Batas lebih pendek mengurangi penyimpanan teks, tetapi dapat menggagalkan pemrosesan pesan saat worker lama tidak tersedia. Kode undangan mentah dan respons pengirimannya dibersihkan setelah 2 hari. ID update dan pengirim tetap disimpan untuk mencegah pemrosesan ulang. Pembersihan berjalan oleh worker setiap jam dan tertunda jika worker berhenti. Audit biasa disimpan sampai keluarga dihapus. Backup tidak dikelola atau dihapus otomatis: operator harus menetapkan retensi dan memastikan salinan lama dimusnahkan sesuai kebijakan. Nama keluarga; data profil anak; payload event; payload inbound; hasil aksi chat; preferensi; usulan AI; reminder; serta isi draft/outbox disimpan terenkripsi dengan AES-GCM memakai `APP_DATA_ENCRYPTION_KEY`. Kunci yang hilang membuat data tersebut tidak dapat dipulihkan; rotasi kunci didukung; lihat bagian Rotasi kunci data. ID Telegram, ID keluarga/profil, waktu, status, dan metadata operasional masih terlihat di database. Enkripsi kolom tidak melindungi data saat aplikasi sedang berjalan atau menggantikan enkripsi disk/volume host. Backup `age` tetap memerlukan kunci privat pemulihan yang disimpan terpisah.

## Backup dan pemeriksaan restore

`scripts/backup-postgres.sh` membuat snapshot konsisten, mengenkripsinya langsung dengan `age`, memakai izin file privat, dan menolak menimpa backup yang sudah ada. Jalankan dari direktori proyek setelah memasang `age` dan mengatur recipient publik milik operator:

```sh
BACKUP_AGE_RECIPIENT='age1...' scripts/backup-postgres.sh
```

`BACKUP_DIR` dapat diatur untuk memilih lokasi output. Skrip hanya menulis ciphertext ke file sementara di direktori backup yang sama, lalu membuat nama tujuan tanpa menimpa file yang ada. Simpan kunci privat terpisah dari backup dan batasi akses keduanya. Volume PostgreSQL aktif tetap bergantung pada enkripsi disk/volume yang disediakan host atau layanan database; Compose ini tidak mengaktifkannya secara portabel. Uji restore hanya ke container dan database kosong yang terisolasi, bukan database aktif:

```sh
export RESTORE_TEST_PASSWORD="$(openssl rand -hex 32)"
docker run -d --name ruang-restore-check --network none -e POSTGRES_PASSWORD="$RESTORE_TEST_PASSWORD" postgres:16-alpine
# Tunggu hingga `docker logs ruang-restore-check` menunjukkan database siap.
age -d -i /path/ke/kunci-age.txt ruang-backup.dump.age | docker exec -i ruang-restore-check pg_restore -U postgres -d postgres --exit-on-error
docker exec ruang-restore-check psql -U postgres -d postgres -c '\dt'
```

Periksa data hasil restore, lalu hentikan dan hapus **hanya** container uji tersebut. Jangan gunakan `--clean` atau restore ke database yang berisi data. Retensi backup dan penghapusan salinannya adalah tanggung jawab operator. Uji lokal dengan data sintetis memverifikasi dump dienkripsi dengan `age` (mode file `0600`, teks uji tidak ditemukan di ciphertext) dan dipulihkan ke PostgreSQL terisolasi. Uji ini tidak memakai data keluarga atau kunci produksi. Enkripsi disk/volume untuk deployment belum diverifikasi; Compose mengandalkan perlindungan yang disediakan host. Pengelolaan kunci, jadwal backup, dan retensi operasional juga tetap menjadi tanggung jawab operator.

Integrasi Telegram nyata serta deployment HTTPS publik belum diverifikasi. Layanan bukan alat diagnosis atau darurat.

### Rotasi kunci data

Rotasi didukung lewat `python -m ruang_tumbuh.rotate_key`. Hentikan API, worker, dan poller; buat backup terenkripsi yang bisa dipulihkan; biarkan PostgreSQL hidup. Ekspor `APP_DATA_ENCRYPTION_KEY_OLD` dan `APP_DATA_ENCRYPTION_KEY_NEW`, lalu jalankan:

```sh
docker compose run --rm --no-deps -e APP_DATA_ENCRYPTION_KEY_OLD -e APP_DATA_ENCRYPTION_KEY_NEW migrate python -m ruang_tumbuh.rotate_key
```

Ganti `APP_DATA_ENCRYPTION_KEY` di `.env` dengan kunci baru sebelum memulai ulang layanan. Rotasi memakai satu transaksi dan gagal seluruhnya jika ada nilai yang gagal diautentikasi. Jangan hidupkan penulis aplikasi selama rotasi. Simpan kunci lama sampai aplikasi memakai kunci baru dan backup telah diuji; setelah itu hapus salinan kunci lama secara aman.

