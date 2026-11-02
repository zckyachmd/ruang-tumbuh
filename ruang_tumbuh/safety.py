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
    normalized = ' '.join(text.casefold().split())
    patterns = (r'\b(?:tidak|nggak|ga|gak|tak)\s+(?:berna[fp]as|sadar|merespons|merespon|responsif)\b',
                r'\b(?:sulit|susah|kesulitan)\s+(?:berna[fp]as|dibangunkan)\b', r'\bsesak(?:\s+na[fp]as)?\b',
                r'\bkejang\b', r'\bbibir(?:nya)?\b.{0,25}\b(?:biru|kebiruan)\b', r'\b(?:blue lips|not breathing|unconscious)\b')
    negation = r'(?:tidak|tak|nggak|enggak|ngga|ga|gak|bukan|belum)'
    negated_prefix = re.compile(r'\b' + negation + r'(?:\s+(?:lagi|sedang|ada|mengalami|tampak|terlihat)){0,2}\s*$')
    historical_concern = False
    residual = normalized
    # Scope negation and history to a clause so a current sign in the next clause
    # cannot be cancelled by an unrelated "tidak" or "kemarin" earlier in the text.
    clauses = re.split(r'[,;.!?\n]+|\b(?:tapi|tetapi|namun)\b|(?=\b(?:sekarang|saat ini)\b)', normalized)
    for clause in clauses:
        educational = bool(re.match(r'^\s*(?:apa (?:itu|arti|tanda)|jelaskan (?:arti|tanda)|bagaimana (?:cara )?mencatat)\b', clause))
        history = bool(re.search(r'\b(?:kemarin|dulu|minggu lalu|tahun lalu|riwayat)\b', clause)) and not bool(
            re.search(r'\b(?:sekarang|saat ini|sedang)\b', clause))
        for pattern in patterns:
            for match in re.finditer(pattern, clause):
                span = match.group()
                negated = bool(negated_prefix.search(clause[:match.start()]))
                if span.startswith('bibir') and re.search(
                        r'\b' + negation + r'(?:\s+(?:lagi|tampak|terlihat)){0,2}\s+(?:biru|kebiruan)\b', span):
                    negated = True
                if negated:
                    residual = residual.replace(span, ' ')
                    continue
                if history or educational:
                    historical_concern = True
                    continue
                return 'emergency'
    record_request = bool(re.search(r'\b(?:catat|simpan|ringkasan|riwayat|terakhir)\b', normalized))
    if historical_concern and not record_request:
        return 'health_boundary'
    if not re.search(r'\b(catat|simpan|ringkasan|riwayat|terakhir|data|akun|privasi|keamanan)\b', residual) and re.search(
            r'\b(tersedak|demam|sakit|dosis|obat|nafas(?:nya)?|napas(?:nya)?|bernapas|bernafas)\b|\b(?:bayi|anak)\b.{0,35}\b(?:normal|aman)\b', residual):
        return 'health_boundary'
    return None
