import json
import secrets
from pathlib import Path
from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from placement.models import User, Student, Company, Drive, Offer, Application, Policy, COURSES
from placement.policy import DEFAULT
from placement import audit

class Command(BaseCommand):
    help = 'Create synthetic NFSU demonstration records and unique local passwords.'
    @transaction.atomic
    def handle(self, *args, **options):
        if settings.PRODUCTION: raise CommandError('Synthetic accounts cannot be seeded in production.')
        if User.objects.exists(): raise CommandError('Seed only an empty local database; existing accounts preserved.')
        Policy.objects.create(version='2026-27-provisional-v1',active=True,config=DEFAULT)
        company = Company.objects.create(name='Sentinel Forensics (synthetic)',website='https://example.com')
        other = Company.objects.create(name='Aster Security (synthetic)')
        accounts = []
        for username, role, courses, org in [('placement.admin','admin',[],None),('placement.officer','officer',[],None),
                      ('dfis.coordinator','coordinator',['MSC_DFIS'],None),('sentinel.recruiter','recruiter',[],company),
                      ('demo.student','student',[],None)]:
            password = secrets.token_urlsafe(18)
            user = User.objects.create_user(username=username,email=username+'@example.com',password=password,
                role=role,courses=courses,company=org,approved=True,email_verified=True)
            accounts.append({'username':username,'password':password,'role':role})
        for index in range(1,26):
            course = COURSES[(index-1)%5][0]
            student = Student.objects.create(placement_id=f'NFSU-DEMO-{index:03}',name=f'Synthetic Student {index:02}',
                email='demo.student@example.com' if index==5 else f'student{index}@example.com',mobile=f'900000{index:04}',
                course=course,batch='2026–28',registration='registered',eligibility='eligible' if index%7 else 'pending',academic_score='8.20',
                user=User.objects.get(username='demo.student') if index==5 else None)
            if index in {2,3,7,9,12,18,21}:
                offer = Offer.objects.create(student=student,company=other,offer_type='F',ctc=str(6+index/2),verified=True,
                    acceptance='accepted',issued_at=timezone.now()-timedelta(days=3),deadline=timezone.now()-timedelta(days=2),
                    submitted_by=User.objects.get(username='placement.officer'),joining='joined' if index%2 else 'pending',off_campus=True)
                audit.record(User.objects.get(username='placement.officer'),'demo.offer',offer.pk)
        drive = Drive.objects.create(company=company,title='Digital Forensics Analyst',offer_type='F',ctc='12.00',
            courses=[c for c,_ in COURSES],min_score='7.00',scheduled_at=timezone.now()+timedelta(days=7),closes_at=timezone.now()+timedelta(days=5))
        Drive.objects.create(company=other,title='Security Research Internship',offer_type='I',stipend='25000',stipend_period='month',
            courses=[c for c,_ in COURSES],scheduled_at=timezone.now()+timedelta(days=10),closes_at=timezone.now()+timedelta(days=8))
        applicant = Student.objects.get(placement_id='NFSU-DEMO-001')
        Application.objects.create(student=applicant,drive=drive,status='approved')
        audit.record(User.objects.get(username='placement.admin'),'demo.seed',details={'synthetic':True,'students':25})
        path = settings.BASE_DIR / '.local-demo-accounts.json'
        path.write_text(json.dumps(accounts,indent=2),encoding='utf-8')
        self.stdout.write(self.style.SUCCESS('Synthetic records created. Local credentials: .local-demo-accounts.json (not committed). Staff must enroll MFA.'))
