import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from placement import audit
from placement.models import AuditEvent, AuditHead

class Command(BaseCommand):
    help = 'Verify audit chain; write or verify an externally stored signed checkpoint.'
    def add_arguments(self,parser):
        parser.add_argument('--checkpoint')
        parser.add_argument('--verify-checkpoint')
    def handle(self,*args,**options):
        if not audit.verify(): raise CommandError('Audit integrity verification failed.')
        if options['verify_checkpoint']:
            item = json.loads(Path(options['verify_checkpoint']).read_text())
            event = AuditEvent.objects.filter(pk=item['id']).first()
            if not event or event.digest!=item['digest']: raise CommandError('External checkpoint does not match database history.')
        if options['checkpoint']:
            last = AuditEvent.objects.order_by('-id').first()
            if not last: raise CommandError('No events to checkpoint.')
            path = Path(options['checkpoint'])
            path.write_text(json.dumps({'id':last.pk,'digest':last.digest,'occurred_at':last.occurred_at.isoformat()}),encoding='utf-8')
        self.stdout.write('Audit integrity verified.')
