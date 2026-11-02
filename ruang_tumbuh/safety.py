"""Conservative routing, not clinical diagnosis or a validated triage service."""

import re

SOURCE = 'https://www.royalfree.nhs.uk/patients-and-visitors/patient-information-leaflets/signs-and-symptoms-of-an-unwell-baby'

EMERGENCY_MESSAGE = ('Jika keluhan ini sedang terjadi—anak sulit/tidak bernapas, bibir tampak biru, kejang, '
    'tidak merespons, atau sulit dibangunkan—segera cari pertolongan medis darurat setempat. '
    'Jangan menunggu balasan bot. Saya tidak dapat menilai kondisi anak dari chat. '
    'Jika ini riwayat yang sudah berlalu, tetap sampaikan kekhawatiranmu kepada tenaga kesehatan.\n'
    'Rujukan tanda bahaya: ' + SOURCE)

HEALTH_MESSAGE = ('Aku paham ini bisa membuat khawatir. Aku belum bisa menilai penyebab atau memastikan anak aman dari chat maupun catatan. '
    'Hubungi tenaga kesehatan untuk penilaian. Jika saat ini anak sulit bernapas, tampak biru, tidak merespons, atau sulit dibangunkan, cari pertolongan darurat segera. '
    'Aku bisa membantu merangkum catatan yang sudah ada untuk dibawa saat konsultasi.\nSumber tanda bahaya: ' + SOURCE)


def route(text):
    normalized = text.casefold()
    normalized = re.sub(r'\b(tidak|nggak|ga|gak)\s+(?:ada\s+|mengalami\s+)?kejang\b', '', normalized)
    patterns = (r'\b(?:tidak|nggak|ga|gak|tak)\s+(?:berna[fp]as|sadar|merespons|merespon|responsif)\b',
                r'\b(?:sulit|susah|kesulitan)\s+(?:berna[fp]as|dibangunkan)\b', r'\bsesak(?:\s+na[fp]as)?\b',
                r'\bkejang\b', r'\bbibir(?:nya)?\b.{0,25}\b(?:biru|kebiruan)\b', r'\b(?:blue lips|not breathing|unconscious)\b')
    if any(re.search(pattern, normalized) for pattern in patterns):
        return 'emergency'
    if not re.search(r'\b(catat|simpan|ringkasan|riwayat|terakhir|data|akun|privasi|keamanan)\b', normalized) and re.search(
            r'\b(tersedak|demam|sakit|dosis|obat|nafas(?:nya)?|napas(?:nya)?|bernapas|bernafas)\b|\b(?:bayi|anak)\b.{0,35}\b(?:normal|aman)\b', normalized):
        return 'health_boundary'
    return None
