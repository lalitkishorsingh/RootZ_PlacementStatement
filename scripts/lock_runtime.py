"""Pin the runtime dependency versions resolved and scanned in this workspace."""
import json
from pathlib import Path
root=Path(__file__).resolve().parent.parent
report=json.loads((root/'artifacts-dependency-audit.json').read_text())
if any(item['vulns'] for item in report['dependencies']): raise RuntimeError('Resolve vulnerabilities before locking dependencies.')
lines=['# Runtime versions verified by pip-audit; refresh deliberately and re-run the tests.']
lines += [f"{item['name']}=={item['version']}" for item in sorted(report['dependencies'],key=lambda x:x['name'])]
(root/'requirements.lock').write_text('\n'.join(lines)+'\n')
