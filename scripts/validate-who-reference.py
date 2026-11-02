"""Numerical checks against official published SD columns; never publishes data."""

import json
import re
import os
import hashlib
import tempfile
from unittest.mock import patch
import sys
from pathlib import Path
from openpyxl import load_workbook

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from ruang_tumbuh import growth
from ruang_tumbuh.growth import lms_zscore, load_reference, compare, GrowthUnavailable, _load_table

directory=Path(sys.argv[1])
manifest=json.loads((Path(__file__).resolve().parent.parent/'docs/who-assets.json').read_text())
checks=0
for asset in manifest:
    workbook=load_workbook(directory/asset['filename'],read_only=True,data_only=True)
    try:
        iterator=iter(workbook.active.iter_rows(values_only=True))
        for _ in range(12):
            row=next(iterator)
            names=[str(value).strip() for value in row]
            if all(value in names for value in ('L','M','S')):
                break
        else:raise AssertionError('Unrecognized official workbook header')
        columns={name:index for index,name in enumerate(names)}
        expected={}
        for name,index in columns.items():
            normalized=name.lower().replace(' ','')
            match=re.fullmatch(r'sd([0-3])(neg|pos)?',normalized)
            if match:expected[index]=int(match[1])*(-1 if match[2]=='neg' else 1)
        if not {-3,-2,-1,0,1,2,3} <= set(expected.values()):
            raise AssertionError('Official SD fixtures not found')
        rows=list(iterator)
        for row in rows:
            if row[columns['M']] is None:continue
            params=[float(row[columns[key]]) for key in ('L','M','S')]
            for index,sd in expected.items():
                actual=lms_zscore(float(row[index]),*params,weight_based=asset['indicator'] in ('wfa','wfl','wfh'))
                if abs(actual-sd)>.015:
                    raise AssertionError('LMS disagrees with official SD column beyond rounding tolerance: '+asset['filename'])
                checks+=1
    finally:workbook.close()
# Exercise the production table parser and comparison boundaries without publishing values.
for asset in manifest:
    path=directory/asset['filename']
    stat=path.stat()
    data=_load_table(str(path),asset['sha256'],stat.st_mtime_ns,stat.st_ctime_ns,stat.st_size)
    axes = [value for value in (0,1,730,731,1856) if value in data] if asset['indicator'] not in ('wfl','wfh') else [min(data),sorted(data)[len(data)//2],max(data)]
    with patch('ruang_tumbuh.growth.load_reference',return_value=(asset,data)):
        for axis in axes:
            age = (100 if asset['indicator']=='wfl' else 800) if asset['indicator'] in ('wfl','wfh') else int(axis)
            position = 'recumbent' if age<=730 else 'standing'
            result=compare(asset['indicator'],asset['sex'],age,data[axis][1],position=position,length_cm=axis if asset['indicator'] in ('wfl','wfh') else None)
            assert abs(result['z_score'])<=.001
            checks+=1
        try:compare(asset['indicator'],asset['sex'],1857,1,position='standing')
        except GrowthUnavailable:pass
        else:raise AssertionError('Age boundary was not enforced')
record={'status':'validated','checks':checks,'asset_sha256':[item['sha256'] for item in manifest],
        'implementation_sha256':hashlib.sha256(Path(growth.__file__).read_bytes()).hexdigest(),
        'fixture_method':'official-SD-all-rows-v1',
        'method':'independent official published SD column versus LMS implementation, tolerance 0.015 z',
        'limitations':'position conversions/off-grid interpolation withheld; no clinical interpretation'}
fd,temporary=tempfile.mkstemp(dir=directory)
try:
    with os.fdopen(fd,'w') as output:output.write(json.dumps(record,indent=2)+'\n')
    os.replace(temporary,directory/'validation.json')
finally:Path(temporary).unlink(missing_ok=True)
os.environ['WHO_COMPARISON_ENABLED']='1'
os.environ['WHO_DATA_DIR']=str(directory)
for asset in manifest:
    load_reference(asset['indicator'],asset['sex'])
print('PASS numerical WHO reference checks:',checks,'across',len(manifest),'checksum-pinned official assets')
print('No workbook values or private clinical data were published. Validation cache is bound to the implementation/data; clinical claims remain out of scope.')
