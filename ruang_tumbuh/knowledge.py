"""Small local source registry. Never sends licensed material/results to AI."""

import re

SOURCE = 'https://www.who.int/tools/child-growth-standards'
REGISTRY = {
    'growth_reference': {
        'source': SOURCE, 'reviewed_at': '2026-11-02', 'version': 'WHO Child Growth Standards overview',
        'text': 'Kurva pertumbuhan adalah referensi untuk membandingkan pengukuran menurut umur dan jenis kelamin. Catatan pengukuran tetap perlu dinilai bersama tenaga kesehatan; satu angka bukan diagnosis. Ruang Tumbuh hanya menampilkan perbandingan setelah dataset dan perhitungannya divalidasi.'},
    'measurement_position': {
        'source': 'https://cdn.who.int/media/docs/default-source/child-growth/child-growth-standards/indicators/instructions-en.pdf',
        'reviewed_at': '2026-11-02', 'version': 'WHO expanded-table instructions',
        'text': 'Panjang badan diukur berbaring, sedangkan tinggi badan diukur berdiri. Keduanya dicatat terpisah bersama posisi dan tanggal pengukuran. Saya tidak menebak posisi atau mengganti nilai pengukuranmu.'},
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
            return (item['text'] + '\nPenjelasan aplikasi; WHO adalah sumber referensi, bukan penulis respons ini.\n'
                    + item['source'] + '\nVersi: ' + item['version'] + ' · ditinjau ' + item['reviewed_at'])
    return None
