"""Create local secrets once. Never overwrites an existing .env."""
import secrets
from pathlib import Path
from cryptography.fernet import Fernet

root = Path(__file__).resolve().parent.parent
path = root / '.env'
if path.exists():
    print('.env already exists; secrets preserved.')
else:
    data = '\n'.join([
        'APP_ENV=development', 'DJANGO_SECRET_KEY='+secrets.token_urlsafe(64),
        'DATA_KEYS=v1:'+Fernet.generate_key().decode(), 'AUDIT_KEY='+secrets.token_urlsafe(64),
        'LOOKUP_KEY='+secrets.token_urlsafe(64), 'BACKUP_KEY='+Fernet.generate_key().decode(),
        'ALLOWED_HOSTS=localhost,127.0.0.1,testserver', 'SITE_URL=http://127.0.0.1:8000', 'RETENTION_DAYS=0',
    ])+'\n'
    with path.open('x',encoding='utf-8') as output: output.write(data)
    print('Created .env with unique development secrets. Protect this file and back it up separately.')
