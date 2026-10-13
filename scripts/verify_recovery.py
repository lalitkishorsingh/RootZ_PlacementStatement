"""Verify an isolated local recovery against the current encryption keys/checkpoint."""
import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
parser=argparse.ArgumentParser()
parser.add_argument('database')
parser.add_argument('--checkpoint')
args=parser.parse_args()
from django.conf import settings
path=Path(args.database).resolve()
if not path.is_file(): raise SystemExit('Recovered database does not exist.')
if settings.PRODUCTION: raise SystemExit('This helper is for isolated SQLite recovery only.')
settings.DATABASES['default']['NAME']=path
import django
django.setup()
from django.core.management import call_command
from placement.models import Student, Offer
call_command('check')
call_command('verify_audit',verify_checkpoint=args.checkpoint)
students=list(Student.objects.all())
offers=list(Offer.objects.all())
for student in students: assert isinstance(student.email,str)
for offer in offers: assert isinstance(offer.ctc,str)
print(f'Recovery verified: {len(students)} students and {len(offers)} offers; encrypted fields decrypted successfully.')
