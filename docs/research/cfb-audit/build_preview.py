"""Embed the audited snapshot in the self-contained research preview."""
import base64
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
CACHE=Path('/tmp/deck-cfb-audit')
sample=json.loads((HERE/'sample-matchup.json').read_text())
market=json.loads((HERE/'market-audit.json').read_text())
assert market['sample_match_verified'], 'Do not attach an unverified market to a matchup.'
payload={'names':{'252':'BYU','2116':'UCF'},'variants':sample['variants'],'market':market,
         'logos':{tid:'data:image/webp;base64,'+base64.b64encode((CACHE/(name+'.webp')).read_bytes()).decode()
                  for tid,name in [('252','byu'),('2116','ucf')]}}
template=(HERE/'preview.template.html').read_text()
assert template.count('__DECK_AUDIT_DATA__')==1
fragment=template.replace('__DECK_AUDIT_DATA__',json.dumps(payload,separators=(',',':'),allow_nan=False).replace('<','\\u003c'))
assert len(fragment.encode())<1_000_000
(HERE/'byu-ucf-preview.html').write_text(fragment)
print('Built byu-ucf-preview.html:',len(fragment.encode()),'bytes')
