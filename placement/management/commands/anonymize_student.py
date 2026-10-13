import getpass
from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from placement.auth_views import check_totp
from placement.models import User, Student, SignupRequest, Review, Token, Offer
from placement import audit

class Command(BaseCommand):
    help = 'Anonymize an archived student only under a configured institutional retention policy.'
    def add_arguments(self,parser):
        parser.add_argument('placement_id')
        parser.add_argument('--admin',required=True)
        parser.add_argument('--reason',required=True)
    @transaction.atomic
    def handle(self,*args,**options):
        if settings.RETENTION_DAYS<=0: raise CommandError('Institutional retention period is not configured; permanent anonymization is disabled.')
        user = User.objects.select_for_update().filter(username=options['admin'],role='admin',approved=True,is_active=True,email_verified=True,mfa_enabled=True).first()
        if not user or not user.check_password(getpass.getpass('Administrator password: ')) or not check_totp(user,getpass.getpass('Fresh MFA code: ')):
            raise CommandError('Administrator authentication failed.')
        student = Student.objects.select_for_update().get(placement_id=options['placement_id'])
        if not student.archived_at or student.archived_at>timezone.now()-timedelta(days=settings.RETENTION_DAYS):
            raise CommandError('Archive retention period has not elapsed.')
        if len(options['reason'].strip())<10: raise CommandError('A detailed reason is required.')
        if student.user_id:
            account = User.objects.get(pk=student.user_id)
            account.email = f'anonymized-{account.pk}@invalid.example'; account.username = f'anonymized-{account.pk}'
            account.first_name=account.last_name=account.mfa_secret=''; account.mfa_enabled=False
            account.is_active=False; account.set_unusable_password(); account.credential_version+=1; account.save()
            SignupRequest.objects.filter(user=account).delete(); Token.objects.filter(user=account).delete()
        student.name='Anonymized student'; student.email=''; student.mobile=''; student.user=None
        student.placement_id='ANON-'+str(student.pk); student.save()
        Review.objects.filter(student=student).update(details='Anonymized under retention policy.',resolution='Anonymized.')
        Offer.objects.filter(student=student).update(remarks='')
        audit.record(user,'student.anonymize',student.pk,{'reason':options['reason']})
        self.stdout.write('Student anonymized; aggregate outcomes and audit references preserved. External exports/backups require separate retention handling.')
