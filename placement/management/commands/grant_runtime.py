from django.core.management.base import BaseCommand, CommandError
from django.db import connection

class Command(BaseCommand):
    help = 'Migration-owner only: constrain placement_app privileges after migrations.'
    def handle(self,*args,**options):
        if connection.vendor!='postgresql': raise CommandError('PostgreSQL is required.')
        with connection.cursor() as cursor:
            cursor.execute('GRANT USAGE ON SCHEMA public TO placement_app')
            cursor.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO placement_app')
            cursor.execute('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO placement_app')
            cursor.execute('REVOKE UPDATE, DELETE, TRUNCATE ON placement_auditevent FROM placement_app')
            cursor.execute('REVOKE INSERT, DELETE, TRUNCATE ON placement_audithead FROM placement_app')
            cursor.execute('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON django_migrations FROM placement_app')
        self.stdout.write('Runtime role restricted; audit events are append-only.')
