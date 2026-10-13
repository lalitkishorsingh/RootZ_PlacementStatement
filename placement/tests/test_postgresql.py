from unittest import skipUnless
from django.core.management import call_command
from django.db import connection, transaction, DatabaseError
from django.test import TestCase
from placement import audit

@skipUnless(connection.vendor=='postgresql','PostgreSQL permission checks require a PostgreSQL test database.')
class RuntimePrivileges(TestCase):
    def test_runtime_cannot_change_audit_events_or_drop_tables(self):
        import io
        with connection.cursor() as cursor:
            cursor.execute('CREATE ROLE placement_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE')
        call_command('grant_runtime',stdout=io.StringIO())
        event=audit.record(None,'permissions.test')
        with connection.cursor() as cursor: cursor.execute('SET LOCAL ROLE placement_app')
        try:
            for query in [f'UPDATE placement_auditevent SET action=\'tampered\' WHERE id={event.pk}',
                          'DELETE FROM placement_auditevent', 'TRUNCATE placement_auditevent',
                          'DROP TABLE placement_student']:
                with self.subTest(query=query):
                    with self.assertRaises(DatabaseError):
                        with transaction.atomic():
                            with connection.cursor() as cursor: cursor.execute(query)
            audit.record(None,'permissions.allowed_insert')
        finally:
            with connection.cursor() as cursor: cursor.execute('RESET ROLE')
        self.assertTrue(audit.verify())
