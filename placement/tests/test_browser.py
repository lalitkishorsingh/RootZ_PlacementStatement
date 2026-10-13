import os
import time
from datetime import timedelta
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch
import pyotp
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connection
from django.utils import timezone
from placement.models import User, Student, Company, Drive, Offer, Application, Policy, AuditHead, SignupRequest, COURSES
from placement.policy import DEFAULT

@skipUnless(os.getenv('RUN_BROWSER_TESTS')=='1','Set RUN_BROWSER_TESTS=1 to run real browser workflows.')
class BrowserWorkflows(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Playwright's synchronous API owns a loop on this test thread. This override
        # is limited to the browser test harness, never application/deployment settings.
        cls.async_guard = patch.dict(os.environ,{'DJANGO_ALLOW_ASYNC_UNSAFE':'true'})
        cls.async_guard.start()
        from playwright.sync_api import sync_playwright
        cls.playwright=sync_playwright().start()
        cls.browser=cls.playwright.chromium.launch(channel=os.getenv('BROWSER_CHANNEL','chrome'),headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.playwright.stop()
        cls.async_guard.stop()
        super().tearDownClass()

    def setUp(self):
        AuditHead.objects.get_or_create(pk=1)
        Policy.objects.create(version='browser-provisional',config=DEFAULT,active=True)
        self.company=Company.objects.create(name='Browser Test Forensics')
        self.password='Browser-test-password-649!'
        self.secret=pyotp.random_base32()
        self.users={}
        for role in ('admin','officer','coordinator','recruiter','student'):
            self.users[role]=User.objects.create_user(username=role,email=role+'@example.com',password=self.password,
                role=role,approved=True,email_verified=True,courses=['MSC_DFIS'] if role=='coordinator' else [],
                company=self.company if role=='recruiter' else None,mfa_enabled=role in {'admin','officer','coordinator'},
                mfa_secret=self.secret if role in {'admin','officer','coordinator'} else '')
        self.student=Student.objects.create(placement_id='BROWSER-001',name='Browser Student',email='student@example.com',mobile='9999999999',
            course='MSC_DFIS',batch='2026–28',registration='registered',eligibility='eligible',academic_score='8',user=self.users['student'])
        self.drive=Drive.objects.create(company=self.company,title='Forensics Analyst',offer_type='F',ctc='12',courses=['MSC_DFIS'],
            scheduled_at=timezone.now()+timedelta(days=7),closes_at=timezone.now()+timedelta(days=5))
        self.context=self.browser.new_context(viewport={'width':1440,'height':1000})
        self.page=self.context.new_page()
        self.errors=[]
        self.page.on('pageerror',lambda error:self.errors.append(str(error)))

    def tearDown(self):
        self.context.close()

    def signin(self,role):
        self.page.goto(self.live_server_url+'/login/')
        self.page.get_by_label('Username').fill(role)
        self.page.get_by_label('Password').fill(self.password)
        self.page.get_by_role('button',name='Sign in').click()
        if role in {'admin','officer','coordinator'}:
            self.page.get_by_label('Authenticator code').fill(pyotp.TOTP(self.secret).now())
            self.page.get_by_role('button',name='Verify code').click()
        self.page.wait_for_url(self.live_server_url+'/')

    def signout(self):
        self.page.get_by_role('button',name='Sign out').click()

    def test_student_application_recruiter_submission_officer_verification_student_acceptance(self):
        self.signin('student')
        self.page.goto(self.live_server_url+'/drives/')
        self.page.get_by_role('button',name='Apply to drive').click()
        self.assertEqual(Application.objects.get(student=self.student).status,'submitted')
        self.signout(); self.signin('officer')
        self.page.goto(self.live_server_url+'/applications/')
        self.page.get_by_role('button',name='Approve').click()
        self.assertEqual(Application.objects.get(student=self.student).status,'approved')
        self.signout(); self.signin('recruiter')
        self.page.goto(self.live_server_url+f'/students/{self.student.pk}/offers/new/')
        self.page.get_by_label('Company:',exact=True).select_option(str(self.company.pk))
        self.page.get_by_label('Drive').select_option(str(self.drive.pk))
        self.page.get_by_label('Offer type').select_option('F')
        self.page.get_by_label('Annual CTC').fill('12')
        self.page.get_by_role('button',name='Save changes').click()
        self.page.wait_for_url('**/offers/')
        self.assertFalse(Offer.objects.get(student=self.student).verified)
        # Fresh officer login needs a fresh TOTP step. Use the next valid step after the previous one.
        User.objects.filter(username='officer').update(mfa_last_step=-1)
        self.signout(); self.signin('officer')
        self.page.goto(self.live_server_url+'/offers/')
        self.page.get_by_role('button',name='Verify selection').click()
        self.assertTrue(Offer.objects.get(student=self.student).verified)
        self.signout(); self.signin('student')
        self.page.goto(self.live_server_url+'/offers/')
        self.page.get_by_role('button',name='Accept').click()
        self.assertEqual(Offer.objects.get(student=self.student).acceptance,'accepted')
        self.assertFalse(self.errors)

    def test_coordinator_record_update_and_recruiter_scope(self):
        self.signin('coordinator')
        self.page.goto(self.live_server_url+f'/students/{self.student.pk}/edit/')
        self.page.get_by_label('Academic score').fill('8.75')
        self.page.get_by_role('button',name='Save changes').click()
        self.student.refresh_from_db(); self.assertEqual(str(self.student.academic_score),'8.75')
        self.signout(); self.signin('recruiter')
        response=self.page.goto(self.live_server_url+f'/students/{self.student.pk}/')
        self.assertEqual(response.status,404)

    def test_admin_approval_and_dashboard_desktop_mobile(self):
        unlinked=Student.objects.create(placement_id='APPROVAL-001',name='Pending Student',email='pending@example.com',course='MSC_DFIS',batch='2026–28')
        pending=User.objects.create_user(username='pending',email='pending@example.com',password=self.password,email_verified=True)
        SignupRequest.objects.create(user=pending,placement_id='APPROVAL-001',name='Pending Student',course='MSC_DFIS',batch='2026–28')
        self.signin('admin')
        self.page.goto(self.live_server_url+f'/accounts/{pending.pk}/approve/')
        self.page.get_by_label('Student').select_option(str(unlinked.pk))
        self.page.get_by_label('Reason').fill('Matched independently against institutional records')
        self.page.get_by_role('button',name='Save changes').click()
        pending.refresh_from_db(); self.assertTrue(pending.approved)
        self.page.goto(self.live_server_url+'/')
        output=Path('artifacts'); output.mkdir(exist_ok=True)
        self.page.screenshot(path=str(output/'dashboard-desktop.png'),full_page=True)
        self.page.set_viewport_size({'width':390,'height':844})
        self.page.screenshot(path=str(output/'dashboard-mobile.png'),full_page=True)
        overflow=self.page.evaluate('document.documentElement.scrollWidth > window.innerWidth')
        self.assertFalse(overflow)
        self.page.keyboard.press('Tab')
        self.assertEqual(self.page.locator(':focus').count(),1)
        self.assertFalse(self.errors)
        self.page.goto(self.live_server_url+'/drives/')
        self.page.screenshot(path=str(output/'drives-mobile.png'),full_page=True)
        self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
        self.page.set_viewport_size({'width':1440,'height':1000})
        self.page.screenshot(path=str(output/'drives-desktop.png'),full_page=True)

    def test_signup_validation_and_empty_states(self):
        self.page.goto(self.live_server_url+'/signup/')
        self.page.get_by_label('Username').fill('browser.signup')
        self.page.get_by_label('Email').fill('browser.signup@example.com')
        self.page.get_by_label('Password').fill(self.password)
        self.page.get_by_label('Name:',exact=True).fill('Synthetic Signup')
        self.page.get_by_label('Placement id').fill('SIGNUP-001')
        self.page.get_by_label('Course').select_option('MSC_DFIS')
        self.page.get_by_label('Batch').fill('2026–28')
        self.page.get_by_role('button',name='Create account').click()
        self.page.wait_for_url('**/login/')
        self.assertFalse(User.objects.get(username='browser.signup').approved)
        self.signin('student')
        self.page.goto(self.live_server_url+'/offers/')
        self.assertTrue(self.page.get_by_text('No offers yet.',exact=False).is_visible())

    def test_every_visible_navigation_link_for_every_role(self):
        for role in ('admin','officer','coordinator','recruiter','student'):
            self.signin(role)
            links=self.page.locator('nav[aria-label="Main navigation"] a').evaluate_all('(anchors) => anchors.map(a => ({href:a.getAttribute("href"),label:a.textContent}))')
            self.assertTrue(links)
            for link in links:
                with self.subTest(role=role,link=link['label']):
                    response=self.page.goto(self.live_server_url+link['href'])
                    self.assertEqual(response.status,200)
                    self.assertEqual(self.page.url,self.live_server_url+link['href'])
            self.signout()
        self.assertFalse(self.errors)

    def test_first_login_setup_qr_and_password_only_reconfirmation(self):
        User.objects.filter(username='admin').update(mfa_enabled=False,mfa_secret='')
        self.page.goto(self.live_server_url+'/login/')
        self.page.get_by_label('Username').fill('admin')
        self.page.get_by_label('Password').fill(self.password)
        self.page.get_by_role('button',name='Sign in').click()
        self.page.wait_for_url('**/mfa/')
        self.assertEqual(self.page.locator('nav[aria-label="Main navigation"]').count(),0)
        image=self.page.locator('.mfa-qr')
        self.assertTrue(image.is_visible())
        self.assertTrue(image.evaluate('(image) => image.complete && image.naturalWidth > 0'))
        self.page.goto(self.live_server_url+'/reauth/')
        self.assertEqual(self.page.locator('#id_code').count(),0)
        self.page.get_by_label('Password').fill(self.password)
        self.page.get_by_role('button',name='Verify identity').click()
        self.page.wait_for_url('**/mfa/')
