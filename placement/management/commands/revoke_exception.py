from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from placement.models import ExceptionGrant, Student, User
from placement import audit
from placement.auth_views import check_totp
import getpass

class Command(BaseCommand):
    help = 'Revoke a drive-specific exception with administrator password and fresh MFA.'
    def add_arguments(self,parser):
        parser.add_argument('exception_id',type=int); parser.add_argument('--admin',required=True); parser.add_argument('--reason',required=True)
    @transaction.atomic
    def handle(self,*args,**options):
        user=User.objects.select_for_update().filter(username=options['admin'],role='admin',is_active=True,approved=True,email_verified=True,mfa_enabled=True).first()
        if not user or not user.check_password(getpass.getpass('Administrator password: ')) or not check_totp(user,getpass.getpass('Fresh MFA code: ')):
            raise CommandError('Administrator authentication failed.')
        if len(options['reason'].strip())<10: raise CommandError('A detailed reason is required.')
        item=ExceptionGrant.objects.get(pk=options['exception_id'])
        Student.objects.select_for_update().get(pk=item.student_id)
        item.revoked=True; item.save(update_fields=['revoked'])
        audit.record(user,'policy.exception_revoke',item.pk,{'reason':options['reason']})
        self.stdout.write('Exception revoked.')
