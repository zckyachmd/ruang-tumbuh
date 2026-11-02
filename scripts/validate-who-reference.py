"""Numerical checks against official published SD columns; never publishes data."""

import json
import re
import os
import sys
from pathlib import Path
from openpyxl import load_workbook

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from ruang_tumbuh.growth import lms_zscore, load_reference, compare, GrowthUnavailable

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
# A temporary authorization fixture exercises the production loader and boundary logic.
# It is deleted immediately and is never a production approval record.
temporary = directory/'validation.json'
if temporary.exists():
    raise SystemExit('Refusing to overwrite an operator validation record')
temporary.write_text(json.dumps({'status':'approved','reviewer':'CI test authorization only',
    'independent_fixture_report':'official SD-column numerical suite', 'asset_sha256':[item['sha256'] for item in manifest]}))
os.environ['WHO_COMPARISON_ENABLED']='1'
os.environ['WHO_DATA_DIR']=str(directory)
try:
    for asset in manifest:
        entry,data=load_reference(asset['indicator'],asset['sex'])
        axes = [value for value in (0,1,730,731,1856) if value in data] if asset['indicator'] not in ('wfl','wfh') else [min(data),sorted(data)[len(data)//2],max(data)]
        for axis in axes:
            age = (100 if asset['indicator']=='wfl' else 800) if asset['indicator'] in ('wfl','wfh') else int(axis)
            position = 'recumbent' if age<=730 else 'standing'
            result=compare(asset['indicator'],asset['sex'],age,data[axis][1],position=position,length_cm=axis if asset['indicator'] in ('wfl','wfh') else None)
            assert abs(result['z_score'])<=.001
            checks+=1
        try:compare(asset['indicator'],asset['sex'],1857,1,position='standing')
        except GrowthUnavailable:pass
        else:raise AssertionError('Age boundary was not enforced')
finally:
    temporary.unlink()
    os.environ.pop('WHO_COMPARISON_ENABLED',None)
    os.environ.pop('WHO_DATA_DIR',None)
record={'status':'numeric_validated','checks':checks,'asset_sha256':[item['sha256'] for item in manifest],
        'method':'independent official published SD column versus LMS implementation, tolerance 0.015 z',
        'remaining':'position conversions/off-grid interpolation withheld; human review and display acceptance still required'}
(directory/'numerical-validation.json').write_text(json.dumps(record,indent=2)+'\n')
print('PASS numerical WHO reference checks:',checks,'across',len(manifest),'checksum-pinned official assets')
print('No workbook values, reference tables or private clinical data were published. Production remains disabled pending review.')
