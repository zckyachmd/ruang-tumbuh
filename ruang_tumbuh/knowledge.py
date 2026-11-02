"""Small local source registry. Never sends licensed material/results to AI."""

import re

REGISTRY = {
    'growth_reference': {
        'source': 'https://www.who.int/tools/child-growth-standards',
        'source_title': 'WHO Child Growth Standards', 'source_version': 'Standar 2006; halaman ringkasan resmi',
        'reviewed_at': '2026-11-03', 'age_scope': 'Lahir sampai 60 bulan lengkap',
        'applicability': 'Gambaran kurva menurut umur dan jenis kelamin; bukan interpretasi pengukuran anak.',
        'text': 'WHO menyediakan kurva pertumbuhan menurut umur dan jenis kelamin untuk anak sampai 5 tahun. Ruang Tumbuh hanya memakai referensi ini setelah dataset dan perhitungan divalidasi.'},
    'measurement_position': {
        'source': 'https://cdn.who.int/media/docs/default-source/child-growth/child-growth-standards/indicators/instructions-en.pdf',
        'source_title': 'WHO Child Growth Standards: expanded tables technical notes',
        'source_version': 'PDF instruksi expanded tables; tidak mencantumkan edisi',
        'reviewed_at': '2026-11-03', 'age_scope': 'Lahir sampai 60 bulan lengkap',
        'applicability': 'Kurva panjang/tinggi-menurut-umur beralih dari panjang berbaring ke tinggi berdiri pada usia 2 tahun.',
        'text': 'Pada kurva panjang/tinggi-menurut-umur WHO, pengukuran beralih dari panjang berbaring ke tinggi berdiri saat usia 2 tahun. Catat posisi dan tanggal; aplikasi tidak menebak posisi atau mengubah nilainya.'},
}


def licensed_query(text):
    return bool(re.search(r'\b(who|z[ -]?score|persentil|kurva pertumbuhan)\b', text, re.IGNORECASE))


def answer(text):
    if re.search(r'\b(dosis|obat|normal|aman|diagnos|sesak|kejang)\w*', text, re.IGNORECASE):
        return None
    if re.search(r'\b(apa|beda|jelaskan|maksud)\b', text, re.IGNORECASE):
        key = 'measurement_position' if 'panjang' in text.lower() and 'tinggi' in text.lower() else 'growth_reference' if licensed_query(text) else None
        if key:
            item = REGISTRY[key]
            return (item['text'] + '\nBatas cakupan: ' + item['age_scope'] + '. ' + item['applicability'] + '\n'
                    + 'Ringkasan statis aplikasi; tautan sumber tidak dibuka ulang saat chat. WHO adalah sumber referensi, bukan penulis respons ini.\n'
                    + item['source_title'] + ' · ' + item['source_version'] + ' · ditinjau ' + item['reviewed_at'] + '\n'
                    + item['source'])
    return None
