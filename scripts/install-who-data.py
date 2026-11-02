"""Install licensed assets on the server only; verify exact manifest checksums."""
import argparse
import hashlib
import json
import os
import tempfile
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('directory', type=Path)
args = parser.parse_args()
args.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
manifest = json.loads((Path(__file__).resolve().parent.parent/'docs/who-assets.json').read_text())
for entry in manifest:
    request = urllib.request.Request(entry['url'], headers={'User-Agent': 'RuangTumbuh/1.0 licensed-server-install'})
    with urllib.request.urlopen(request, timeout=30) as response:
        content = response.read(2_000_001)
    if len(content) > 2_000_000 or hashlib.sha256(content).hexdigest() != entry['sha256']:
        raise SystemExit('Checksum mismatch for '+entry['filename']+'; no replacement installed')
    descriptor, temporary = tempfile.mkstemp(dir=args.directory)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(content)
        os.replace(temporary, args.directory/entry['filename'])
    finally:
        Path(temporary).unlink(missing_ok=True)
    print('Verified:', entry['filename'])
print('Assets installed. Comparison stays disabled until independent validation is approved.')
