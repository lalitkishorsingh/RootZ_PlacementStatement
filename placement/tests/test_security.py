import hashlib
import io
import json
import time
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
import pyotp
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, IntegrityError, transaction
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from placement.models import (User, Student, Company, Drive, Offer, Application, Policy, ExceptionGrant,
                              Sanction, Review, Attendance, SignupRequest, Token, AuditEvent, AuditHead, COURSES)
from placement import audit, services, access
from placement.policy import evaluate, category, DEFAULT
from placement.auth_views import check_totp
from placement.imports import parse_upload, safe_cell, COLUMNS
from placement.forms import OfferForm, StudentForm

PASSWORD = 'A-student-test-password-784!'

class Fixtures(TestCase):
    @classmethod
    def setUpTestData(cls):
        Policy.objects.create(version='test-v1',config=DEFAULT,active=True)
        cls.company = Company.objects.create(name='Test Company')
        cls.other_company = Company.objects.create(name='Other Company')
        cls.admin = User.objects.create_user(username='admin',email='admin@example.com',password=PASSWORD,role='admin',approved=True,email_verified=True)
        cls.officer = User.objects.create_user(username='officer',email='officer@example.com',password=PASSWORD,role='officer',approved=True,email_verified=True)
        cls.coordinator = User.objects.create_user(username='coordinator',email='coordinator@example.com',password=PASSWORD,role='coordinator',courses=['MSC_DFIS'],approved=True,email_verified=True)
        cls.recruiter = User.objects.create_user(username='recruiter',email='recruiter@example.com',password=PASSWORD,role='recruiter',company=cls.company,approved=True,email_verified=True)
        cls.user = User.objects.create_user(username='student',email='student@example.com',password=PASSWORD,approved=True,email_verified=True)
        cls.other_user = User.objects.create_user(username='other',email='other@example.com',password=PASSWORD,approved=True,email_verified=True)
        cls.student = Student.objects.create(placement_id='NFSU-001',name='Test Student',email='student@example.com',mobile='9999999999',course='MSC_DFIS',batch='2026–28',registration='registered',eligibility='eligible',academic_score='8',user=cls.user)
        cls.other = Student.objects.create(placement_id='NFSU-002',name='Other Student',email='other@example.com',mobile='8888888888',course='MSC_CS',batch='2026–28',registration='registered',eligibility='eligible',user=cls.other_user)
        cls.drive = Drive.objects.create(company=cls.company,title='Analyst',offer_type='F',ctc='12',courses=[x for x,_ in COURSES],scheduled_at=timezone.now()+timedelta(days=3),closes_at=timezone.now()+timedelta(days=2))
        cls.other_drive = Drive.objects.create(company=cls.other_company,title='Other analyst',offer_type='IF',ctc='18',courses=[x for x,_ in COURSES],scheduled_at=timezone.now()+timedelta(days=4),closes_at=timezone.now()+timedelta(days=3))

    def login_as(self,user):
        if user.role in access.PRIVILEGED:
            User.objects.filter(pk=user.pk).update(mfa_enabled=True)
            user.refresh_from_db()
        self.client.force_login(user)
        session = self.client.session
        session.update({'started':time.time(),'last_activity':time.time(),'credential_version':user.credential_version,'mfa_verified':True,'recent_auth':time.time()})
        session.save()

    def offer(self, student=None, **kwargs):
        data = dict(student=student or self.student,company=self.company,offer_type='F',ctc='8',verified=True,
                    issued_at=timezone.now(),deadline=timezone.now()+timedelta(hours=24),submitted_by=self.officer)
        data.update(kwargs)
        return Offer.objects.create(**data)

class PolicyTests(Fixtures):
    def test_exact_category_boundaries(self):
        for value,expected in [('5.99','C'),('6','B'),('9.99','B'),('10','A'),('15.99','A'),('16','A+'),('0',None),('NaN',None),('',None)]:
            with self.subTest(value=value): self.assertEqual(category(value),expected)

    def test_unplaced_allowed_and_explained(self):
        result = evaluate(self.student,self.drive)
        self.assertEqual(result.outcome,'allowed'); self.assertEqual(result.version,'test-v1')
        self.assertEqual(result.codes,['ELIGIBLE'])

    def test_registration_pending_and_company_criteria(self):
        self.student.registration='deregistered'
        self.assertIn('REGISTRATION',evaluate(self.student,self.drive).codes)
        self.student.registration='registered'; self.student.eligibility='pending'
        self.assertEqual(evaluate(self.student,self.drive).outcome,'manual_review')
        self.student.eligibility='eligible'; self.drive.min_score=Decimal('9')
        self.assertIn('SCORE',evaluate(self.student,self.drive).codes)
        self.student.academic_score=None
        self.assertEqual(evaluate(self.student,self.drive).outcome,'manual_review')
        self.drive.courses=['MSC_CS']
        self.assertIn('COURSE',evaluate(self.student,self.drive).codes)

    def test_b_switch_exact_multiplier(self):
        self.offer(offer_type='F',ctc='8')
        self.drive.offer_type='IF'; self.drive.ctc='11.99'
        self.assertIn('B_SWITCH',evaluate(self.student,self.drive).codes)
        self.drive.ctc='12'
        self.assertEqual(evaluate(self.student,self.drive).outcome,'allowed')

    def test_category_a_and_c_switches(self):
        offer = self.offer(ctc='10')
        self.drive.offer_type='IF'; self.drive.ctc='15.99'
        self.assertIn('A_SWITCH',evaluate(self.student,self.drive).codes)
        self.drive.ctc='16'; self.assertEqual(evaluate(self.student,self.drive).outcome,'allowed')
        offer.ctc='5'; offer.save(); self.drive.ctc='5.99'
        self.assertIn('C_SWITCH',evaluate(self.student,self.drive).codes)
        self.drive.ctc='6'; self.assertEqual(evaluate(self.student,self.drive).outcome,'allowed')

    def test_type_and_category_rules_both_apply(self):
        self.offer(ctc='8'); self.drive.ctc='18'
        self.assertIn('SAME_TYPE',evaluate(self.student,self.drive).codes)

    def test_internship_has_no_inferred_salary_category(self):
        self.offer(offer_type='I',ctc='',stipend='25000',stipend_period='month')
        self.assertEqual(evaluate(self.student,self.drive).outcome,'allowed')
        self.drive.offer_type='I'; self.drive.ctc=''
        self.assertIn('SAME_TYPE',evaluate(self.student,self.drive).codes)

    def test_aplus_and_combined_selections(self):
        item=self.offer(ctc='16',acceptance='declined')
        self.assertIn('APLUS_EXIT',evaluate(self.student,self.drive).codes)
        item.withdrawn=True; item.save()
        self.assertEqual(evaluate(self.student,self.drive).outcome,'allowed')
        item.withdrawn=False; item.offer_type='IF'; item.ctc='8'; item.company=self.other_company; item.save()
        self.assertIn('COMBINED_SELECTION',evaluate(self.student,self.drive).codes)

    def test_all_selections_evaluated(self):
        self.offer(offer_type='I',ctc='')
        self.offer(offer_type='F',ctc='16')
        self.assertIn('APLUS_EXIT',evaluate(self.student,self.other_drive).codes)

    def test_missing_compensation_or_policy_requires_review(self):
        self.drive.ctc=''
        self.assertEqual(evaluate(self.student,self.drive).outcome,'manual_review')
        self.drive.ctc='12'; Policy.objects.update(active=False)
        self.assertIn('NO_POLICY',evaluate(self.student,self.drive).codes)

    def test_scoped_expiring_exception_and_hard_blocks(self):
        self.student.eligibility='ineligible'; self.student.save()
        grant=ExceptionGrant.objects.create(student=self.student,drive=self.drive,reason='Verified emergency exemption',expires=timezone.now()+timedelta(hours=1),approved_by=self.admin)
        self.assertEqual(evaluate(self.student,self.drive).codes,['APPROVED_EXCEPTION'])
        self.assertEqual(evaluate(self.student,self.other_drive).outcome,'blocked')
        self.student.archived=True
        self.assertIn('ARCHIVED',evaluate(self.student,self.drive).codes)
        self.student.archived=False; grant.expires=timezone.now()-timedelta(seconds=1); grant.save()
        self.assertEqual(evaluate(self.student,self.drive).outcome,'blocked')

    def test_attendance_sanction_requires_review(self):
        review=Review.objects.create(student=self.student,kind='absence',details='Missed interview')
        self.assertEqual(evaluate(self.student,self.drive).outcome,'allowed')
        sanction=Sanction.objects.create(student=self.student,review=review,reason='Authorized exclusion')
        sanction.drives.add(self.drive)
        self.assertIn('ATTENDANCE_SANCTION',evaluate(self.student,self.drive).codes)

class AuthorizationTests(Fixtures):
    def test_role_route_permission_matrix(self):
        routes={'accounts':{'admin'},'invite':{'admin'},'policy':{'admin'},'audit':{'admin'},
                'student_create':{'admin','officer','coordinator'},'export':{'admin','officer','coordinator'},
                'import':{'admin','officer','coordinator'},'reports':{'admin','officer','coordinator'},
                'company_create':{'admin','officer'},'drive_create':{'admin','officer'}}
        for user in (self.admin,self.officer,self.coordinator,self.recruiter,self.user):
            self.login_as(user)
            for route,roles in routes.items():
                with self.subTest(role=user.role,route=route):
                    self.assertEqual(self.client.get(reverse(route)).status_code,200 if user.role in roles else 403)

    def test_signup_rejects_role_injection(self):
        data={'username':'injected','email':'injected@example.com','password':PASSWORD,'name':'Injected account',
              'placement_id':'INJECTED','course':'MSC_DFIS','batch':'2026–28','role':'admin'}
        response=self.client.post(reverse('signup'),data)
        self.assertContains(response,'Unexpected fields')
        self.assertFalse(User.objects.filter(username='injected').exists())

    def test_student_cannot_access_another_record(self):
        self.login_as(self.user)
        self.assertEqual(self.client.get(reverse('student',args=[self.other.pk])).status_code,404)
        self.assertEqual(self.client.get(reverse('student_edit',args=[self.student.pk])).status_code,403)
        self.assertEqual(self.client.post(reverse('archive',args=[self.student.pk]),{'reason':'unauthorized archive'}).status_code,403)

    def test_student_cannot_use_staff_routes(self):
        self.login_as(self.user)
        for name in ['accounts','invite','policy','audit','export','import','company_create','drive_create','student_create','companies','reports']:
            with self.subTest(route=name): self.assertEqual(self.client.get(reverse(name)).status_code,403)

    def test_coordinator_is_course_scoped(self):
        self.login_as(self.coordinator)
        self.assertEqual(self.client.get(reverse('student',args=[self.other.pk])).status_code,404)
        response=self.client.get(reverse('students'))
        self.assertContains(response,'Test Student'); self.assertNotContains(response,'Other Student')
        payload={'placement_id':'NEW','name':'Unauthorized','email':'new@example.com','mobile':'','course':'MSC_CS','batch':'2026–28','registration':'registered','eligibility':'eligible','academic_score':'8'}
        response=self.client.post(reverse('student_create'),payload)
        self.assertEqual(response.status_code,200); self.assertFalse(Student.objects.filter(placement_id='NEW').exists())

    def test_recruiter_only_approved_applicants_and_own_offers(self):
        self.login_as(self.recruiter)
        self.assertEqual(self.client.get(reverse('student',args=[self.student.pk])).status_code,404)
        Application.objects.create(student=self.student,drive=self.drive,status='approved')
        foreign=self.offer(company=self.other_company,ctc='73.45')
        response=self.client.get(reverse('student',args=[self.student.pk]))
        self.assertEqual(response.status_code,200); self.assertNotContains(response,'73.45'); self.assertNotContains(response,self.other_company.name)
        self.assertEqual(self.client.post(reverse('offer_action',args=[foreign.pk]),{'action':'verify'}).status_code,404)
        self.assertFalse(access.drives(self.recruiter).filter(pk=self.other_drive.pk).exists())

    def test_student_cannot_verify_offer_or_change_other_offer(self):
        own=self.offer(verified=False)
        foreign=self.offer(student=self.other)
        self.login_as(self.user)
        self.assertEqual(self.client.post(reverse('offer_action',args=[own.pk]),{'action':'verify'}).status_code,403)
        self.assertEqual(self.client.post(reverse('offer_action',args=[foreign.pk]),{'action':'accepted'}).status_code,404)
        own.refresh_from_db(); self.assertFalse(own.verified)

    def test_server_rechecks_application_policy(self):
        self.login_as(self.user)
        self.offer(ctc='18')
        self.client.post(reverse('apply',args=[self.drive.pk]))
        self.assertFalse(Application.objects.filter(student=self.student,drive=self.drive).exists())

    def test_unexpected_offer_privilege_fields_rejected(self):
        form=OfferForm({'company':self.company.pk,'offer_type':'F','ctc':'12','issued_at':timezone.now().isoformat(),'off_campus':'on','verified':'true','acceptance':'accepted'})
        self.assertFalse(form.is_valid()); self.assertIn('Unexpected fields',str(form.errors))

    def test_anonymous_requests_redirect_and_post_only(self):
        self.assertEqual(self.client.get(reverse('students')).status_code,302)
        self.login_as(self.user)
        self.assertEqual(self.client.get(reverse('apply',args=[self.drive.pk])).status_code,405)
        self.assertEqual(self.client.get(reverse('logout')).status_code,405)

    def test_sensitive_exports_require_recent_auth(self):
        self.login_as(self.officer)
        session=self.client.session; session['recent_auth']=time.time()-600; session.save()
        self.assertRedirects(self.client.get(reverse('export')),reverse('reauth'),fetch_redirect_response=False)

    def test_csv_export_scope_formula_injection_and_audit(self):
        self.student.name='=HYPERLINK("evil")'; self.student.save()
        self.login_as(self.coordinator)
        response=self.client.post(reverse('export'),{'course':'','batch':'','sensitive':'on','format':'csv'})
        self.assertEqual(response.status_code,200)
        self.assertIn("'=HYPERLINK",response.content.decode()); self.assertNotIn('Other Student',response.content.decode())
        self.assertEqual(response['Cache-Control'],'no-store')
        self.assertTrue(AuditEvent.objects.filter(action='export.students').exists())

class WorkflowTests(Fixtures):
    def test_off_campus_offer_can_be_verified_without_a_drive(self):
        item=services.submit_offer(self.user,self.student,{
            'company':self.company,'drive':None,'offer_type':'F','ctc':'12',
            'issued_at':timezone.now(),'company_deadline':None,'off_campus':True,
        })
        services.verify_offer(self.officer,item)
        item.refresh_from_db()
        self.assertTrue(item.verified)
        self.assertIsNone(item.drive_id)
        self.assertEqual(item.decision['outcome'],'allowed')
        self.assertTrue(AuditEvent.objects.filter(action='offer.verify',target=str(item.pk)).exists())

    def test_company_batch_and_switching_reports_are_scoped(self):
        from placement.reporting import institutional_report
        self.offer(ctc='10',acceptance='accepted')
        self.offer(student=self.other,ctc='50',acceptance='accepted')
        data=institutional_report(self.coordinator)
        self.assertEqual(data['cohorts'][0]['total'],1)
        self.assertEqual(data['company_rows'][0]['highest'],Decimal('10'))
        self.assertEqual(data['company_rows'][0]['placed'],1)
        self.assertEqual(data['eligibility_rows'][0]['blocked'],1)
        self.assertEqual(len(data['eligibility_rows'][1]['allowed']),1)

    def test_application_uniqueness_and_revalidation(self):
        item=services.apply(self.user,self.drive)
        with self.assertRaises(IntegrityError):
            with transaction.atomic(): services.apply(self.user,self.drive)
        self.offer(ctc='18')
        with self.assertRaises(ValidationError): services.approve_application(self.officer,item,True)

    def test_recruiter_submission_requires_approved_application(self):
        data={'company':self.company,'drive':self.drive,'offer_type':'F','ctc':'12','stipend':'','stipend_period':'','issued_at':timezone.now(),'company_deadline':None,'off_campus':False,'remarks':''}
        with self.assertRaises(PermissionDenied): services.submit_offer(self.recruiter,self.student,data)
        Application.objects.create(student=self.student,drive=self.drive,status='approved')
        item=services.submit_offer(self.recruiter,self.student,data)
        self.assertFalse(item.verified)
        services.verify_offer(self.officer,item); item.refresh_from_db(); self.assertTrue(item.verified)

    def test_actual_offer_ctc_is_evaluated_not_advertised_ctc(self):
        self.offer(ctc='8')
        self.drive.offer_type='IF'; self.drive.ctc='18'; self.drive.save()
        Application.objects.create(student=self.student,drive=self.drive,status='approved')
        item=self.offer(offer_type='IF',ctc='9',verified=False,drive=self.drive)
        with self.assertRaises(ValidationError): services.verify_offer(self.officer,item)

    def test_acceptance_deadline_earliest_and_late_response(self):
        issued=timezone.now()-timedelta(hours=2)
        item=services.submit_offer(self.user,self.student,{'company':self.company,'drive':None,'offer_type':'F','ctc':'12','issued_at':issued,'company_deadline':issued+timedelta(hours=1),'off_campus':True})
        self.assertEqual(item.deadline,issued+timedelta(hours=1))
        item.verified=True; item.save()
        self.assertFalse(services.respond_offer(self.user,item,'accepted'))
        item.refresh_from_db(); self.assertEqual(item.acceptance,'expired')

    def test_offer_response_terminal_and_audited(self):
        item=self.offer()
        self.assertTrue(services.respond_offer(self.user,item,'accepted'))
        with self.assertRaises(ValidationError): services.respond_offer(self.user,item,'declined')
        self.assertTrue(AuditEvent.objects.filter(action='offer.respond').exists())

    def test_reports_count_unique_students_and_keep_stipends_separate(self):
        self.offer(ctc='10',acceptance='accepted')
        self.offer(ctc='20',offer_type='IF',acceptance='accepted')
        self.offer(ctc='100',acceptance='declined')
        self.offer(ctc='',offer_type='I',stipend='99999',acceptance='accepted')
        self.offer(student=self.other,ctc='50',acceptance='accepted',withdrawn=True)
        report=services.report(self.officer)
        self.assertEqual(report['placed'],1); self.assertEqual(report['offers'],4)
        self.assertEqual(report['highest'],Decimal('20')); self.assertEqual(report['average'],Decimal('15')); self.assertEqual(report['median'],Decimal('15'))
        self.assertEqual(report['combined'],1)

    def test_student_signup_not_automatically_linked(self):
        response=self.client.post(reverse('signup'),{'username':'claimant','email':'claimant@example.com','password':PASSWORD,
             'name':'Claimant','placement_id':self.student.placement_id,'course':'MSC_DFIS','batch':'2026–28','mobile':''})
        self.assertEqual(response.status_code,302)
        user=User.objects.get(username='claimant'); self.assertFalse(user.approved); self.assertFalse(user.email_verified)
        self.student.refresh_from_db(); self.assertEqual(self.student.user_id,self.user.pk)

    def test_staff_cannot_link_mismatched_email(self):
        self.student.user=None; self.student.save()
        claimant=User.objects.create_user(username='claimant',email='claimant@example.com',password=PASSWORD,email_verified=True)
        SignupRequest.objects.create(user=claimant,placement_id=self.student.placement_id,name='Claimant',course='MSC_DFIS',batch='2026–28')
        self.login_as(self.admin)
        response=self.client.post(reverse('approve_signup',args=[claimant.pk]),{'student':str(self.student.pk),'reason':'Independently checked identity'})
        self.assertEqual(response.status_code,200); claimant.refresh_from_db(); self.assertFalse(claimant.approved)

    def test_absence_sanction_requires_three_eligible_drives(self):
        review=Review.objects.create(student=self.student,kind='absence',details='Missed interview')
        with self.assertRaises(ValidationError): services.resolve_review(self.admin,review,'sanction','Authorized absence sanction')
        Drive.objects.create(company=self.company,title='Third drive',offer_type='I',courses=['MSC_DFIS'],scheduled_at=timezone.now()+timedelta(days=10),closes_at=timezone.now()+timedelta(days=9))
        services.resolve_review(self.admin,review,'sanction','Authorized absence sanction')
        self.assertEqual(Sanction.objects.get(review=review).drives.count(),3)

class IntegrityTests(Fixtures):
    def test_encrypted_storage_and_email_lookup(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT email, mobile FROM placement_student WHERE placement_id=%s',[self.student.placement_id])
            email,mobile=cursor.fetchone()
            self.assertNotIn('student@example.com',email); self.assertNotIn('9999999999',mobile)
            cursor.execute('SELECT email FROM placement_user WHERE username=%s',['student'])
            self.assertNotIn('student@example.com',cursor.fetchone()[0])
        self.student.refresh_from_db(); self.assertEqual(self.student.email,'student@example.com')
        item=self.offer(ctc='13.37'); item.refresh_from_db(); self.assertEqual(item.ctc,'13.37')

    def test_unique_email_and_placement_id(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic(): User.objects.create_user(username='duplicate',email='STUDENT@example.com',password=PASSWORD)
        form=StudentForm({'placement_id':self.student.placement_id,'name':'Duplicate','email':'duplicate@example.com','course':'MSC_DFIS','batch':'2026–28','registration':'registered','eligibility':'eligible'})
        self.assertFalse(form.is_valid())

    def test_audit_tampering_detected(self):
        event=audit.record(self.user,'test',self.student.pk,{'x':1})
        self.assertTrue(audit.verify())
        AuditEvent.objects.filter(pk=event.pk).update(details={'x':2})
        self.assertFalse(audit.verify())

    def test_sensitive_change_rolls_back_if_audit_fails(self):
        with patch('placement.services.audit.record',side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError): services.apply(self.user,self.drive)
        self.assertFalse(Application.objects.exists())

    def test_xss_output_escaped_and_security_headers(self):
        self.student.name='<script>alert(1)</script>'; self.student.save()
        self.login_as(self.officer)
        response=self.client.get(reverse('student',args=[self.student.pk]))
        self.assertContains(response,'&lt;script&gt;'); self.assertNotContains(response,'<script>alert(1)</script>')
        self.assertIn("object-src 'none'",response['Content-Security-Policy']); self.assertEqual(response['X-Frame-Options'],'DENY')

    def test_csrf_blocks_forged_request(self):
        client=Client(enforce_csrf_checks=True)
        response=client.post(reverse('login'),{'username':'student','password':PASSWORD})
        self.assertEqual(response.status_code,403)

    def test_sql_injection_search_does_not_expand_results(self):
        self.login_as(self.user)
        response=self.client.get(reverse('students'),{'q':"' OR 1=1 --"})
        self.assertNotContains(response,'Other Student'); self.assertEqual(Student.objects.count(),2)

    def test_import_duplicate_formula_scope_and_safe_cells(self):
        header=','.join(COLUMNS)
        row='NEW,New Student,new@example.com,9999999999,MSC_DFIS,2026–28,registered,eligible,8'
        upload=SimpleUploadedFile('students.csv',(header+'\n'+row+'\n'+row).encode())
        rows,errors=parse_upload(upload,self.officer)
        self.assertEqual(len(rows),1); self.assertTrue(errors)
        for cell in ['=1+1',' +CMD','\t@SUM(1)','-1','\n=1']:
            self.assertTrue(safe_cell(cell).startswith("'"))
        from openpyxl import Workbook
        workbook=Workbook(); sheet=workbook.active; sheet.append(COLUMNS); sheet.append(['=1+1','Name','x@example.com','','MSC_DFIS','2026–28','registered','eligible','8'])
        stream=io.BytesIO(); workbook.save(stream)
        with self.assertRaises(ValidationError): parse_upload(SimpleUploadedFile('formula.xlsx',stream.getvalue()),self.officer)

    def test_import_atomic_revalidation(self):
        from placement.models import ImportBatch
        row={'placement_id':'NEW','name':'New Student','email':'new@example.com','mobile':'','course':'MSC_DFIS','batch':'2026–28','registration':'registered','eligibility':'eligible','academic_score':'8'}
        item=ImportBatch.objects.create(owner=self.officer,payload=json.dumps([row,row]))
        self.login_as(self.officer)
        self.client.post(reverse('import_preview',args=[item.pk]))
        self.assertFalse(Student.objects.filter(placement_id='NEW').exists())

class AuthenticationTests(Fixtures):
    def test_setup_explains_gate_and_hides_inaccessible_navigation(self):
        self.client.post(reverse('login'),{'username':'admin','password':PASSWORD})
        response=self.client.get(reverse('mfa'))
        self.assertContains(response,'Finish this step to open your workspace')
        self.assertContains(response,'data:image/svg+xml;base64,')
        self.assertContains(response,'time-based')
        self.assertNotContains(response,'aria-label="Main navigation"')
        self.assertEqual(response['Cache-Control'],'no-store')

    def test_reauth_before_enrollment_does_not_request_code(self):
        self.client.post(reverse('login'),{'username':'admin','password':PASSWORD})
        response=self.client.get(reverse('reauth'))
        self.assertNotContains(response,'name="code"')
        response=self.client.post(reverse('reauth'),{'username':'admin','password':PASSWORD})
        self.assertRedirects(response,reverse('dashboard'),fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse('dashboard')),reverse('mfa'),fetch_redirect_response=False)

    def test_reauth_after_enrollment_requires_authenticator_code(self):
        self.admin.mfa_enabled=True; self.admin.mfa_secret=pyotp.random_base32(); self.admin.save()
        self.login_as(self.admin)
        response=self.client.post(reverse('reauth'),{'username':'admin','password':PASSWORD})
        self.assertContains(response,'This field is required')
        response=self.client.post(reverse('reauth'),{'username':'admin','password':PASSWORD,'code':pyotp.TOTP(self.admin.mfa_secret).now()})
        self.assertEqual(response.status_code,302)

    def test_optional_mfa_enrollment_requires_recent_password_auth(self):
        self.login_as(self.user)
        session=self.client.session; session['recent_auth']=time.time()-600; session.save()
        self.assertRedirects(self.client.get(reverse('mfa')),reverse('reauth'),fetch_redirect_response=False)

    def test_unverified_or_unapproved_accounts_cannot_login(self):
        self.user.email_verified=False; self.user.save()
        response=self.client.post(reverse('login'),{'username':'student','password':PASSWORD})
        self.assertContains(response,'Login unsuccessful')
        self.user.email_verified=True; self.user.approved=False; self.user.save()
        response=self.client.post(reverse('login'),{'username':'student','password':PASSWORD})
        self.assertContains(response,'Login unsuccessful')

    def test_argon2_and_privileged_mfa_gate(self):
        self.assertTrue(self.admin.password.startswith('argon2$'))
        response=self.client.post(reverse('login'),{'username':'admin','password':PASSWORD})
        self.assertRedirects(response,reverse('mfa'),fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse('students')),reverse('mfa'),fetch_redirect_response=False)

    def test_mfa_enrollment_and_replay_protection(self):
        self.client.post(reverse('login'),{'username':'admin','password':PASSWORD})
        self.client.get(reverse('mfa'))
        from placement.crypto import decrypt
        secret=decrypt(self.client.session['enrollment_secret']); code=pyotp.TOTP(secret).now()
        self.assertEqual(self.client.post(reverse('mfa'),{'code':code}).status_code,302)
        self.admin.refresh_from_db(); self.assertTrue(self.admin.mfa_enabled)
        self.assertFalse(check_totp(self.admin,code))

    def test_login_throttling(self):
        for _ in range(11): self.client.post(reverse('login'),{'username':'student','password':'invalid'})
        response=self.client.post(reverse('login'),{'username':'student','password':PASSWORD})
        self.assertContains(response,'Too many attempts')

    def test_idle_absolute_and_credential_revocation(self):
        for key,value in [('last_activity',time.time()-1900),('started',time.time()-30000),('credential_version',99)]:
            with self.subTest(key=key):
                self.login_as(self.user)
                session=self.client.session; session[key]=value; session.save()
                self.assertRedirects(self.client.get(reverse('students')),reverse('login'),fetch_redirect_response=False)

    def test_single_use_email_token(self):
        raw='test-verification-token'
        item=Token.objects.create(user=self.user,digest=hashlib.sha256(raw.encode()).hexdigest(),purpose='verify',expires=timezone.now()+timedelta(hours=1))
        url=reverse('token',args=[raw])
        self.assertEqual(self.client.get(url).status_code,200)
        item.refresh_from_db(); self.assertFalse(item.used)
        self.assertEqual(self.client.post(url).status_code,302)
        self.assertEqual(self.client.post(url).status_code,404)

    def test_password_reset_revokes_sessions_preserves_mfa(self):
        self.user.mfa_enabled=True; self.user.mfa_secret=pyotp.random_base32(); self.user.save()
        raw='reset-token'; Token.objects.create(user=self.user,digest=hashlib.sha256(raw.encode()).hexdigest(),purpose='reset',expires=timezone.now()+timedelta(hours=1))
        version=self.user.credential_version
        response=self.client.post(reverse('reset',args=[raw]),{'password':'Another-strong-test-password-739!'})
        self.assertEqual(response.status_code,302)
        self.user.refresh_from_db(); self.assertEqual(self.user.credential_version,version+1); self.assertTrue(self.user.mfa_enabled)
        self.assertEqual(self.client.post(reverse('reset',args=[raw]),{'password':PASSWORD}).status_code,404)

    @override_settings(APP_ENV='production',SESSION_COOKIE_SECURE=True,CSRF_COOKIE_SECURE=True)
    def test_secure_session_cookie_flags(self):
        self.login_as(self.user)
        response=self.client.get(reverse('dashboard'))
        cookie=response.cookies.get('sessionid')
        self.assertTrue(cookie['httponly']); self.assertTrue(cookie['secure']); self.assertEqual(cookie['samesite'],'Lax')
