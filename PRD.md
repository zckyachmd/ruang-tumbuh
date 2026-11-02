# PRD — Ruang Tumbuh

Status: Approve. Versi: 1.0 — 2 November 2026.

## 1. Ringkasan dan tujuan

Ruang Tumbuh adalah asisten keluarga chat-first untuk mencatat aktivitas dan pertumbuhan anak melalui Telegram. AI agent memproses chat, menggunakan tools aplikasi dan memberikan respons; scheduler dapat memulai check-in dan reminder yang disetujui. Telegram Mini App memberikan timeline, ringkasan, dan pengelolaan data visual. Data database adalah sumber kebenaran, bukan memori model.

Pengguna awal adalah dua orang tua; produk wajib mendukung **dua orang atau lebih** dalam keluarga yang sama, tanpa batas hard-coded dua. Setiap anggota memiliki identitas Telegram, akses dan preferensi notifikasi sendiri. Produk memudahkan dokumentasi dan persiapan konsultasi; bukan perangkat diagnosis, pemantauan medis real-time, atau layanan darurat.

## 2. Tujuan dan ukuran keberhasilan

- Catat beberapa aktivitas dengan satu pesan natural; sistem meminta klarifikasi bila ambigu.
- Jawab pertanyaan riwayat dan agregat dari data aktual, menyebut waktu dan cakupan.
- Anggota keluarga melihat data yang sama dan dapat bekerja bersamaan tanpa kehilangan perubahan.
- Check-in dan reminder hanya berjalan sesuai persetujuan dan preferensi penerima.
- Mini App responsif, mudah dipakai di ponsel dan terhubung ke data yang sama dengan bot.
- Seluruh aplikasi berjalan di Docker Compose dengan data persisten, health check, backup dan restore yang terdokumentasi.

Kriteria keberhasilan adalah acceptance criteria dan skenario uji di bawah; jangan mengklaim target kuantitatif yang belum diukur.

## 3. Pengguna, peran dan akses

Keluarga mempunyai satu atau lebih owner dan banyak anggota. Owner membuat profil, mengundang/mencabut anggota, mengatur peran dan mengelola ekspor/penghapusan. Anggota aktif dapat melihat, membuat, dan mengoreksi catatan serta mengatur preferensi notifikasinya. Owner tidak boleh mencabut owner terakhir; alih kepemilikan harus eksplisit. Semua akses dan tool call dibatasi family_id di server, termasuk ekspor dan file unduhan.

Setiap pengguna memulai chat pribadi dengan bot. Undangan harus sekali pakai, acak, masa berlaku terbatas, tidak tercatat dalam log, dan ditukar secara atomik dengan keanggotaan setelah Telegram user ID terverifikasi. Username bukan identitas otorisasi. Pencabutan memutus akses API, Mini App, pending job, dan notifikasi anggota; cek otorisasi ulang saat tugas dijalankan. Dukungan grup bukan syarat MVP. Keputusan penerima notifikasi keluarga eksplisit; undangan tidak otomatis menyetujui notifikasi.

Multi-anak didukung oleh model family/child. MVP boleh mengaktifkan satu profil anak pada satu waktu, dengan alur pilih anak yang jelas saat terdapat lebih dari satu. Tidak boleh membuat asumsi satu keluarga hanya dua anggota.

## 4. User journeys

1. Owner `/start`, membuat keluarga dan profil anak, lalu mengundang anggota kedua atau berikutnya.
2. Pengguna: “jam 9 ASIP 120 ml, jam setengah 10 pup”. Agent memvalidasi tanggal, mencatat dua event dan mengonfirmasi kedua hasil aktual.
3. Pengguna: “yang minum tadi sebenarnya 8.30”. Agent menemukan catatan; jika beberapa cocok, tawarkan pilihan. Backend mencatat revisi dan mengonfirmasi perubahan.
4. Pengguna: “terakhir pup kapan?” Backend mencari menurut waktu kejadian dan agent menjawab beserta tanggal/jam. Jika kosong, jawab belum tercatat.
5. Pengguna mengaktifkan check-in 13.00. Bot bertanya apakah ada catatan yang terlewat; jawaban dapat membuat event hanya bila pengguna menyampaikan fakta yang cukup.
6. Pengguna membuka Mini App dan melihat timeline, ringkasan, pertumbuhan serta pengaturan yang sama dengan data chat.

## 5. Kebutuhan fungsional

### F1. Profil keluarga dan anak — P0

Profil menyimpan nama panggilan, tanggal lahir, zona waktu IANA (default Asia/Jakarta), jenis kelamin untuk memilih referensi WHO jika dipakai, dan informasi prematur opsional. Data wajib diminta hanya ketika relevan. Owner mengundang, menetapkan peran dan mencabut akses. Jangan menyimpulkan penyesuaian klinis dari data prematur.

### F2. Pencatatan — P0

- Minum: jenis ASI langsung, ASIP, formula atau tidak diketahui; volume jika diketahui; durasi/sisi bila relevan; waktu dan catatan. Jangan konversi durasi menyusu ke ml.
- Popok: pipis, pup, atau keduanya, waktu dan catatan opsional.
- Tidur: mulai, selesai bila diketahui, durasi yang dihitung hanya dari pasangan valid.
- Pertumbuhan: berat, panjang berbaring atau tinggi berdiri, lingkar kepala; nilai, satuan, metode dan tanggal pengukuran.
- Catatan bebas: observasi dan pertanyaan konsultasi.

Bedakan fakta, pertanyaan, rencana dan koreksi. Input ambigu ditanyakan; jangan isi nilai yang tidak diberikan. Catatan jelas boleh disimpan langsung; hasil menyebut event yang benar-benar tersimpan. Tentukan kebijakan atomik: satu pesan valid multi-event diproses satu transaksi; bila sebagian ambigu, minta klarifikasi sebelum commit seluruh paket, dan simpan draft sementara. Setelah commit respons menyertakan tanggal dan zona waktu jika konteks memerlukannya. ASIP dan formula boleh dijumlahkan hanya dengan label jenis dan cakupan; ASI langsung tanpa volume tidak masuk total ml.

### F3. Tanya jawab dan koreksi — P0

Cari terakhir minum/pup, jumlah aktivitas, volume per periode, riwayat pertumbuhan dan timeline. Gunakan occurred_at, bukan created_at. Batas hari mengikuti zona keluarga. “Tidak ada catatan” tidak berarti aktivitas tidak terjadi. Perhitungan angka dilakukan backend. Referensi percakapan mengikat ID event dan memiliki waktu kedaluwarsa; konflik atau beberapa kandidat memerlukan klarifikasi.

Edit memakai optimistic concurrency/version; tampilkan nilai lama dan baru. Hapus hanya setelah konfirmasi eksplisit; perubahan dan soft delete dapat diaudit tanpa menyalin seluruh teks sensitif ke log umum. Saat menghapus permanen jelaskan retensi audit dan backup.

### F4. Proaktif — P0

Check-in berkala, reminder buatan pengguna, ringkasan harian dan satu tindak lanjut untuk klarifikasi tertunda. Opt-in per pengguna dan jenis, tentukan target, jadwal, zona waktu, quiet hours, snooze, penghentian sementara dan batas harian. Default check-in dan ringkasan off. Pesan tidak boleh menganggap aktivitas tidak terjadi hanya karena tidak tercatat. Pengguna dapat mengubah atau mematikan notifikasi kapan saja.

Check-in keluarga yang sudah terjawab di-suppress sesuai aturan yang ditampilkan kepada pengguna. Job mengecek ulang keanggotaan, consent, quiet hours, status penyelesaian dan data terbaru sebelum kirim. Aturan eksplisit reminder melewati quiet hours jika pengguna memilih waktunya; jika tidak, tunda atau batalkan sesuai pengaturan. Setelah downtime jangan flood: reminder punya expires_at dan deduplikasi berdasarkan occurrence dan recipient, retry dibatasi. Bedakan job diklaim, kirim dicoba, berhasil dan gagal; network timeout pada sendMessage dapat menghasilkan status tidak pasti, jangan mengklaim exactly-once delivery atau retry buta. Bot tidak dapat menjamin diterima jika pengguna memblokirnya.

Contoh: “Ada minum atau popok yang belum sempat dicatat?” Jawaban “tidak ada” menutup check-in tanpa membuat event. Tidak ada notifikasi medis otomatis, target konsumsi, dosis, atau pernyataan bahwa anak aman berdasarkan data kosong.

### F5. Mini App — P0

Tombol menu bot membuka web app mobile-first dengan Beranda, Timeline (filter dan pagination), Tambah/Edit, Pertumbuhan dan Pengaturan. Beranda menyebut periode dan cakupan ringkasan. Tampilan memiliki loading/empty/error/retry states, kontrol yang mudah disentuh, teks dan kontras dapat diakses, navigasi keyboard, dukungan reduced motion, dan bukan warna sebagai satu-satunya indikator. Semua mutasi memakai backend dan validasi yang sama seperti chat. Validasi initData Telegram secara server-side termasuk integritas dan freshness, lalu buat sesi terbatas; jangan percaya initDataUnsafe. Batasi akses per family pada setiap request. Kebutuhan HTTPS dan domain ditulis dalam dokumentasi.

### F6. Pertumbuhan WHO — P1 setelah validasi

Simpan dan visualisasikan pengukuran dasar pada P0. Untuk perbandingan WHO, gunakan hanya dataset resmi yang relevan beserta sumber, versi, lisensi, indikator, satuan dan batas rentangnya; validasi perhitungan terhadap referensi resmi dengan fixture independen. Bedakan length/height; jangan pasangkan pengukuran berbeda tanggal secara diam-diam. Tampilkan data yang kurang, cakupan dan tanggal pengukuran. Jangan buat diagnosis atau klaim interpretasi untuk anak prematur. Jika dataset atau perhitungan belum tervalidasi, nonaktifkan kurva dan jelaskan statusnya, jangan buat estimasi.

### F7. Ekspor dan penghapusan — P0

Owner dapat mengunduh CSV melalui endpoint terotorisasi dengan filter rentang; gunakan header yang jelas, satuan, event time, waktu input dan pembuat. Hindari CSV formula injection. Unduhan tidak boleh memakai URL publik tanpa autentikasi. Penghapusan keluarga memerlukan konfirmasi eksplisit dan menjelaskan dampak, periode retensi backup dan audit. Pastikan tindakan berulang aman.

## 6. AI agent dan workflow

Backend menerima update, memvalidasi webhook secret, menyimpan update dan menjadwalkan proses tahan retry. Agent menerima konteks minimal, menyimpulkan intent dan mengusulkan tool call terstruktur. Backend memvalidasi skema, identitas, akses, input, timestamp dan status, lalu menjalankan operasi transaksi. Setelah hasil diketahui agent menyusun jawaban. Agent tidak punya akses SQL atau shell dan tidak boleh mengikuti instruksi yang tersimpan di pesan/hasil tool sebagai system instruction.

Tools minimal: get_child_context, find_events, create_events, update_event, request_delete_event, get_summary, get_growth_history, manage_reminder, get_notification_preferences. Semua tool wajib memverifikasi identitas dan akses server-side. Operasi tulis idempotent per update dan aksi; jangan membuktikan sukses sebelum commit. Context percakapan berisi referensi event ID dan expired_at; data permanen selalu dibaca dari database. Struktur respons AI divalidasi secara ketat; kegagalan atau hasil ambigu menuju klarifikasi/error, bukan menebak. Jangan kirim seluruh riwayat ke model bila tidak diperlukan.

Keluhan medis yang tampak darurat harus mendapat respons yang mendorong bantuan medis segera sesuai situasi, bukan sekadar pencatatan. Jangan mendiagnosis, memberi dosis, atau jaminan aman; tinjauan klinis dibutuhkan sebelum membuat klaim fitur kesehatan.

## 7. Deployment Docker dan operasi

- `docker compose up --build -d` menjalankan backend, worker/scheduler, database persisten dan layanan lain yang memang diperlukan; image menggunakan build multi-stage dan menjalankan proses sebagai non-root bila memungkinkan.
- Sediakan Compose, Dockerfile, `.env.example` tanpa secret, named volume untuk database dan konfigurasi terdokumentasi. Pisahkan proses API dan worker bila implementasi membutuhkan; jangan bergantung pada memori container untuk data/state penting.
- Migration dijalankan secara eksplisit, aman saat restart dan terdokumentasi; health checks untuk proses dan database; readiness tidak melaporkan siap sebelum dependensi dan skema siap. Atur restart policy dan graceful shutdown.
- Dokumentasikan perintah build/start, logs, health, migrasi, tes, backup, restore, update dan shutdown; jelaskan perbedaan `down` versus `down -v`, jangan jalankan penghapusan volume otomatis.
- Dokumentasikan batas resource dan tuning build/runtime secara praktis; jangan mengklaim angka tanpa benchmark.
- Mendukung mode local development dengan Telegram long polling atau webhook sesuai konfigurasi; production webhook mensyaratkan HTTPS dan konfigurasi reverse proxy atau endpoint publik. Long polling dan webhook tidak aktif bersamaan.
- Backup database konsisten saat live, terenkripsi di luar aplikasi, dan restore diuji pada lingkungan terisolasi tanpa menimpa data produksi. Sertakan contoh perintah yang sesuai database yang dipilih.
- Tidak menyimpan token, secret, database, export, hasil backup, atau data pribadi dalam image dan Git. Sertakan `.dockerignore` dan `.gitignore` yang sesuai.

## 8. Kebutuhan nonfungsional

Keamanan: HTTPS, verifikasi secret webhook, validasi Telegram Mini App, otorisasi per family, secret via environment/secret manager, pembatasan akses jaringan dan file, pencatatan minimum. Data dan backup disimpan terenkripsi sesuai kemampuan infrastruktur; jelaskan apa yang benar-benar terlindungi dan siapa pemegang kunci. Sertakan privasi provider AI dan konfigurasi retensi; jangan janjikan E2EE Telegram bot.

Keandalan: simpan event time terpisah dari received/created/updated; gunakan transaksi, versi event, idempotency update_id dan key aksi, scheduler tahan restart, retry terbatas, dan status yang terlihat. Jangan klaim database dan Telegram secara atomik persis sekali. Fallback berupa form Mini App ketika AI gagal. Pesan gagal tidak disebut tersimpan; sediakan status retry yang jelas.

Observability: health/readiness, status scheduler, error, retry, waktu respons, perkiraan konsumsi AI dan backup; tidak mengeluarkan token atau isi catatan mentah ke log default. Batasi dan dokumentasikan retensi data dan konteks AI. Aksesibilitas dan perilaku pada jaringan lambat merupakan syarat.

## 9. Model data minimum

Family, FamilyMember (unique family/user), Child, Invitation, Event (typed payload, occurred_at, version, deleted_at), Measurement, ConversationContext (per user/family/child dan expiry), Reminder, NotificationPreference (per user), ScheduledOccurrence, InboundUpdate (unique update_id), Outbox/DeliveryAttempt dan AuditLog. Sertakan batasan integritas, indeks untuk timeline dan idempotensi. Simpan timestamp UTC untuk instant, zona IANA untuk interpretasi; tanggal lahir sebagai date. Jam relatif diproses berdasarkan waktu pesan dan zona keluarga; jika ambigu tanyakan.

## 10. Acceptance dan pengujian

Harus dapat dibuktikan sebelum disebut selesai:

1. Tiga anggota atau lebih dapat masuk ke satu keluarga, berbagi data, mengatur notifikasi masing-masing; pengguna lain dan anggota yang dicabut ditolak, termasuk saat job tertunda berjalan.
2. Undangan kedaluwarsa, dipakai dua kali, atau dipakai bersamaan ditolak dengan benar; owner terakhir terlindungi.
3. Pesan multi-event menghasilkan data yang tepat; fakta, rencana, pertanyaan, koreksi dan pesan ambigu tidak tertukar; draft ambigu tidak menulis event.
4. Retry update dan tool call tidak menggandakan event. Optimistic concurrency mendeteksi edit bersamaan. Catatan terakhir diurutkan oleh occurred_at.
5. Dua anggota mencatat event yang tampak sama: tampilkan kandidat bila fitur deteksi disediakan, jangan gabung/hapus otomatis; dua event yang memang terpisah tetap bisa tersimpan.
6. Periode lintas tengah malam, input terlambat dan zona waktu dihitung benar. Query dan ringkasan sesuai dataset fixture dan label cakupan.
7. Jadwal opt-in, quiet hours, snooze, pembatalan, penggantian preferensi, downtime dan job retry bekerja tanpa banjir pesan. Simulasikan hasil delivery yang tidak pasti.
8. Mini App memvalidasi signature/freshness Telegram; akun lain tidak dapat mengakses data; UI menangani loading, empty, error dan aksesibilitas dasar.
9. Backup konsisten dan restore ke database terisolasi terbukti; restart/recreate container mempertahankan data. Jalankan Compose dan health check, jika runtime Docker tersedia.
10. AI/tool failures tidak membuat keberhasilan palsu. Gunakan fake provider untuk test deterministik; integrasi eksternal nyata bersifat opsional dan hasilnya harus dilaporkan apa adanya.
11. Grafik WHO hanya aktif jika dataset dan perhitungannya lulus fixture referensi resmi dan batas indikator. Tanpa verifikasi, pencatatan tetap bekerja dan fitur perbandingan dinonaktifkan.
12. CSV aman dan terbatas akses; penghapusan dan retensi dijelaskan; tidak ada rahasia dalam Git atau image.

## 11. Referensi

- Telegram Mini Apps dan validasi data: https://core.telegram.org/bots/webapps
- Telegram Bot API dan update_id: https://core.telegram.org/bots/api
- WHO Child Growth Standards: https://www.who.int/tools/child-growth-standards

## 12. Keputusan yang masih terbuka

Nama final dan username bot (ketersediaan belum diperiksa); server/domain; penyedia dan model AI serta kebijakan retensinya; database dan stack disesuaikan dengan repository/infrastruktur; jadwal dan penerima default dipilih keluarga. Jangan memblokir pembuatan aplikasi lokal karena secret atau akun belum tersedia: berikan mock/fake, konfigurasi, langkah setup dan batas verifikasi yang jujur.
