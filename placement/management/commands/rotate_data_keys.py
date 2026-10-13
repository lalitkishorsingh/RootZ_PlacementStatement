from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from placement.crypto import EncryptedTextField
from placement.models import User, Student, Offer, Drive, SignupRequest, ImportBatch
from placement import audit

class Command(BaseCommand):
    help = 'Re-encrypt contact, compensation and MFA fields using the first configured DATA_KEYS version.'
    def add_arguments(self,parser): parser.add_argument('--maintenance-confirmed',action='store_true')
    @transaction.atomic
    def handle(self,*args,**options):
        if not options['maintenance_confirmed']: raise CommandError('Stop web/scheduler processes and pass --maintenance-confirmed. Keep old keys until backup retention expires.')
        count=0
        for model in (User,Student,Offer,Drive,SignupRequest,ImportBatch):
            fields=[f.name for f in model._meta.fields if isinstance(f,EncryptedTextField)]
            for item in model.objects.select_for_update().iterator():
                item.save(update_fields=fields)
                count+=1
        audit.record(None,'operations.data_key_rotation',details={'records':count})
        self.stdout.write(f'{count} records re-encrypted. Clear active sessions before restarting; old enrollment secrets may still use old keys.')
