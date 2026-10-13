import io
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from cryptography.fernet import Fernet, InvalidToken
from placement.models import AuditEvent, AuditHead
from placement import audit
from scripts.backup import create_snapshot, restore_snapshot

class OperationsTests(TestCase):
    def test_backup_restore_is_encrypted_authenticated_and_isolated(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with closing(sqlite3.connect(root/'dev.sqlite3')) as db:
                db.execute('CREATE TABLE evidence (value TEXT)'); db.execute("INSERT INTO evidence VALUES ('synthetic recovery evidence')")
                db.commit()
            key=Fernet.generate_key().decode()
            with patch('scripts.backup.ROOT',root),patch.dict('os.environ',{'BACKUP_KEY':key,'DB_HOST':''}):
                encrypted=create_snapshot()
                self.assertNotIn(b'synthetic recovery evidence',encrypted)
                restore_snapshot(encrypted,root/'restored.sqlite3')
                with closing(sqlite3.connect(root/'restored.sqlite3')) as db:
                    self.assertEqual(db.execute('SELECT value FROM evidence').fetchone()[0],'synthetic recovery evidence')
                with self.assertRaises(RuntimeError): restore_snapshot(encrypted,root/'restored.sqlite3')
                with self.assertRaises(InvalidToken): restore_snapshot(encrypted[:-5]+b'wrong',root/'bad.sqlite3')

    def test_external_checkpoint_detects_removed_history(self):
        event=audit.record(None,'checkpoint.test')
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'checkpoint.json')
            call_command('verify_audit',checkpoint=path,stdout=io.StringIO())
            AuditEvent.objects.filter(pk=event.pk).delete()
            AuditHead.objects.filter(pk=1).update(digest='0'*64)
            self.assertTrue(audit.verify())
            with self.assertRaises(CommandError): call_command('verify_audit',verify_checkpoint=path,stdout=io.StringIO())

    def test_retention_disabled_by_default(self):
        with self.assertRaises(CommandError):
            call_command('anonymize_student','anything',admin='admin',reason='Example retention deletion')
