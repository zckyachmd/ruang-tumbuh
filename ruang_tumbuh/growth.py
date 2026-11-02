"""Server-only WHO table loader and deterministic LMS calculation.

No reference data is distributed with the source. Production comparison remains
disabled until the independent validation record is installed by the operator.
"""

import hashlib
import json
import math
import os
from pathlib import Path
from functools import lru_cache


class GrowthUnavailable(ValueError):
    pass


def lms_zscore(value, l, m, s, *, weight_based=False):
    if not all(type(x) in (int, float) and math.isfinite(x) for x in (value, l, m, s)) or min(value, m, s) <= 0:
        raise ValueError('Invalid LMS input')
    try:
        log_ratio = math.log(value)-math.log(m)
        z = log_ratio/s if l == 0 else math.expm1(l*log_ratio)/(l*s)
    except (ValueError, OverflowError, ZeroDivisionError) as exc:
        raise ValueError('Measurement outside numerical comparison range') from exc
    if weight_based and abs(z) > 3:
        def at(sd):
            return m*math.exp(s*sd) if l == 0 else m*(1+l*s*sd)**(1/l)
        z = 3+(value-at(3))/(at(3)-at(2)) if z > 3 else -3+(value-at(-3))/(at(-2)-at(-3))
    if not math.isfinite(z):
        raise ValueError('Non-finite comparison')
    return z


def load_reference(indicator, sex):
    if os.getenv('WHO_COMPARISON_ENABLED') != '1':
        raise GrowthUnavailable('Perbandingan WHO belum diaktifkan; catatan mentah tetap tersedia.')
    if indicator not in ('wfa', 'lhfa', 'hcfa', 'wfl', 'wfh') or sex not in ('female', 'male'):
        raise GrowthUnavailable('Indikator atau jenis kelamin belum lengkap.')
    manifest = json.loads((Path(__file__).resolve().parent.parent/'docs/who-assets.json').read_text())
    entry = next(item for item in manifest if item['indicator'] == indicator and item['sex'] == sex)
    directory = Path(os.environ['WHO_DATA_DIR'])
    record = json.loads((directory/'validation.json').read_text())
    # An operator-supplied review is required, not a self-issued synthetic test pass.
    if record.get('status') != 'approved' or not record.get('reviewer') or not record.get('independent_fixture_report') or entry['sha256'] not in record.get('asset_sha256', []):
        raise GrowthUnavailable('Validasi independen dataset belum lengkap.')
    path = directory/entry['filename']
    stat = path.stat()
    data = _load_table(str(path), entry['sha256'], stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
    return entry, data


@lru_cache(maxsize=10)
def _load_table(filename, expected_sha256, _mtime, _ctime, _size):
    path = Path(filename)
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
        raise GrowthUnavailable('Checksum dataset tidak cocok.')
    from openpyxl import load_workbook
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        rows = iter(workbook.active.iter_rows(values_only=True))
        for _ in range(12):
            row = next(rows)
            columns = [str(value).strip() for value in row]
            if all(key in columns for key in ('L', 'M', 'S')):
                break
        else:
            raise GrowthUnavailable('Header dataset belum dikenali.')
        key = next((key for key in ('Day', 'Length', 'Height') if key in columns), None)
        if key is None:
            raise GrowthUnavailable('Sumbu dataset belum dikenali.')
        indexes = [columns.index(key), *(columns.index(name) for name in ('L', 'M', 'S'))]
        data = {float(row[indexes[0]]): tuple(float(row[index]) for index in indexes[1:]) for row in rows if row[indexes[0]] is not None}
        return data
    finally:
        workbook.close()


def compare(indicator, sex, age_days, value, *, position=None, length_cm=None):
    if type(age_days) is not int or not 0 <= age_days <= 1856:
        raise GrowthUnavailable('Umur di luar cakupan tabel yang dipilih.')
    if indicator in ('lhfa', 'wfl', 'wfh'):
        expected = 'recumbent' if age_days <= 730 else 'standing'
        if position != expected:
            # Do not silently convert caregiver facts until conversion fixtures pass review.
            raise GrowthUnavailable('Posisi pengukuran belum sesuai cakupan perbandingan ini.')
        if indicator != 'lhfa' and indicator != ('wfl' if expected == 'recumbent' else 'wfh'):
            raise GrowthUnavailable('Indikator tidak sesuai posisi pengukuran.')
    entry, data = load_reference(indicator, sex)
    axis = length_cm if indicator in ('wfl', 'wfh') else age_days
    if axis not in data:
        raise GrowthUnavailable('Titik pengukuran di luar tabel; tidak dilakukan extrapolation.')
    z = lms_zscore(value, *data[axis], weight_based=indicator in ('wfa', 'wfl', 'wfh'))
    ranges = {'wfa': (-6, 5), 'lhfa': (-6, 6), 'wfl': (-5, 5), 'wfh': (-5, 5)}
    flagged = indicator in ranges and not ranges[indicator][0] <= z <= ranges[indicator][1]
    return {'z_score': None if flagged else round(z, 3), 'review_flag': flagged, 'indicator': indicator,
            'source': entry['source'], 'asset_sha256': entry['sha256'], 'permission_id': '202611419',
            'notice': 'Perbandingan catatan, bukan diagnosis atau penilaian kesehatan. Tidak ada endorsement WHO.'}
