# Inventaris dan rencana

**Pembaruan review:** implementasi #2–#14 dan bukti CI dijelaskan dalam [REVIEW-IMPLEMENTATION.md](docs/REVIEW-IMPLEMENTATION.md). Izin WHO ID 202611419 telah diberikan dan dibaca; [ringkasan scope](docs/WHO-license-status.md) menggantikan status perizinan lama. Bagian di bawah mempertahankan inventaris baseline, bukan status terbaru seluruh fitur.

Sumber kebutuhan: `PRD.md`.

## Deployment intent

Per 2026-11-02, deployment direncanakan sebagai layanan hosted nonkomersial dengan akses untuk keluarga terdaftar dan kerabat yang diundang oleh admin keluarga. Overlay opsional `compose.hosted.yaml` menyediakan Caddy untuk TLS dan reverse proxy; host/domain belum disiapkan dan jalur ini baru divalidasi dengan parser Compose. HTTPS publik, konfigurasi nyata, pemulihan backup, dan integrasi Telegram/provider nyata belum diverifikasi. Status ini bukan izin untuk mengoperasikan aplikasi dengan data keluarga.

## Pilihan awal

PostgreSQL dipilih untuk transaksi, batas integritas, locking, dan data persisten. Satu backend akan melayani bot dan Mini App, dengan worker terpisah sebagai proses dari aplikasi yang sama. Provider Telegram dan AI harus dapat diganti fake deterministik. Skema awal di `migrations/001_initial.sql` adalah fondasi, belum merupakan produk atau skema lengkap.

`ruang_tumbuh/store.py` menyediakan operasi awal keluarga dan event, validasi payload dasar, serta idempotensi pembuatan event. API menyediakan sesi Telegram dan endpoint terbatas. Mode identitas palsu hanya aktif dengan `APP_ENV=development` dan `DEV_AUTH_ENABLED=1`; gunakan hanya di komputer lokal dengan data sintetis. Cakupan yang diimplementasikan dan diuji belum membuktikan seluruh acceptance PRD. Jangan gunakan aplikasi sebagai layanan publik.

Webhook dan long polling menerima pesan pribadi; offset polling dan pesan masuk disimpan atomik, dengan satu poller aktif. Data sensitif di kolom database dienkripsi dengan AES-GCM; migrasi 011 mengenkripsi baris lama, dan seluruh service aplikasi memerlukan `APP_DATA_ENCRYPTION_KEY` yang sama. Kunci harus dicadangkan secara aman; rotasi tersedia melalui `python -m ruang_tumbuh.rotate_key`; kehilangan kunci tetap membuat data tidak terbaca. ID Telegram, ID entitas, waktu, status, dan metadata operasional tetap terlihat di database. Payload inbound dihapus setelah worker selesai, teks draft ambigu tidak disimpan, dan isi outbox dihapus setelah delivery final selain status `uncertain`. Chat mendukung pendaftaran keluarga, undangan satu kali, penukaran lewat `/start KODE`, dan pemilihan keluarga/profil anak melalui `/keluarga` serta `/pilih ID_KELUARGA ID_ANAK`. Provider fake dan OpenAI-compatible dengan tool calling tersedia; provider kompatibel memerlukan persetujuan eksplisit per anggota/keluarga yang terikat ke konfigurasi provider/model/endpoint dan menyamarkan nama yang dikenal, nama berlabel eksplisit, dan pola kontak umum sebelum request, tetapi anonimisasi tidak lengkap. Usulan AI harus dikonfirmasi sebelum disimpan. Agent hanya membantu pencatatan, pencarian dan ringkasan; jawaban klinis dan klaim WHO tidak tersedia. Kontrol Mini App tersedia untuk check-in dan ringkasan harian; API preferensi `reminder` belum menjadi kontrol pengiriman pengingat buatan pengguna. Round-trip backup `age` sudah diuji dengan data sintetis dalam PostgreSQL terisolasi (ciphertext mode `0600`, isi sintetis tidak tampak di ciphertext, dan hasil restore cocok). Enkripsi disk/volume untuk deployment belum diverifikasi; Compose mengandalkan perlindungan yang disediakan host. Pengelolaan kunci produksi, jadwal dan retensi backup operasional juga belum dibuktikan. Integrasi Telegram/provider AI nyata serta acceptance penerimaan penuh belum dibuktikan.

## Tahapan dan gap

1. Lengkapi skema, migration runner, layanan keluarga, otorisasi, undangan atomik, event berversi, audit dan uji isolasi/concurrency.
2. Implementasikan penerimaan Telegram, validasi identitas, idempotensi, agent terstruktur, draft ambigu dan provider fake; uji commit dan penanganan kegagalan.
3. Implementasikan preferensi dan scheduler tahan restart, pemeriksaan ulang akses dan consent, serta status delivery tidak pasti.
4. Implementasikan Mini App, validasi initData, sesi, timeline, form, ekspor dan lifecycle data.
5. Lengkapi Compose, health/readiness, backup/restore, dokumentasi operasi, dan pengujian penerimaan end-to-end.

WHO tetap nonaktif sampai dataset resmi dan perhitungan diverifikasi. Keputusan yang masih terbuka: domain dan bot, penyedia/model AI dan retensinya, serta jadwal/penerima yang dipilih pengguna. Risiko utama: privasi data keluarga, otorisasi lintas keluarga, pemrosesan waktu lokal dan delivery Telegram yang tidak dapat dijamin exactly-once. Jangan mengoperasikan fondasi ini sebagai produk sampai seluruh acceptance PRD terbukti.

