from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest import skipUnless
from django.db import connection, close_old_connections
from django.test import TransactionTestCase
from django.utils import timezone
from django.core.exceptions import ValidationError
from placement.models import Student, User, Company, Drive, Offer, Application, Policy, AuditHead
from placement.policy import DEFAULT
from placement.services import verify_offer
from placement.audit import verify

@skipUnless(connection.vendor=='postgresql','PostgreSQL row locking required; SQLite cannot verify this guarantee.')
class ConcurrencyTests(TransactionTestCase):
    def test_simultaneous_selections_cannot_bypass_restrictions(self):
        AuditHead.objects.get_or_create(pk=1)
        Policy.objects.create(version='concurrency',config=DEFAULT,active=True)
        actor=User.objects.create_user(username='officer',email='officer@example.com',role='officer')
        student=Student.objects.create(placement_id='CONCURRENT',name='Concurrency Test',email='test@example.com',course='MSC_DFIS',batch='2026–28',registration='registered',eligibility='eligible')
        offers=[]
        for index in range(2):
            company=Company.objects.create(name=f'Company {index}')
            drive=Drive.objects.create(company=company,title='Full-time',offer_type='F',ctc='12',courses=['MSC_DFIS'],scheduled_at=timezone.now()+timedelta(days=2),closes_at=timezone.now()+timedelta(days=1))
            Application.objects.create(student=student,drive=drive,status='approved')
            offers.append(Offer.objects.create(student=student,company=company,drive=drive,offer_type='F',ctc='12',issued_at=timezone.now(),deadline=timezone.now()+timedelta(hours=24),submitted_by=actor))
        def worker(pk):
            close_old_connections()
            try:
                verify_offer(User.objects.get(pk=actor.pk),Offer.objects.get(pk=pk))
                return 'verified'
            except ValidationError: return 'blocked'
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool: outcomes=list(pool.map(worker,[o.pk for o in offers]))
        self.assertCountEqual(outcomes,['verified','blocked'])
        self.assertEqual(Offer.objects.filter(verified=True).count(),1)
        self.assertTrue(verify())
