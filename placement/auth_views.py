import hashlib
import logging
import secrets
import time
from datetime import timedelta
import pyotp
import base64
import io
import qrcode
import qrcode.image.svg
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.mail import send_mail
from django.db import transaction, IntegrityError
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from .forms import LoginForm, SignupForm, MFAForm, InviteForm, StrictFormMixin
from .models import User, SignupRequest, Student, Token, Throttle
from . import audit, access
from .crypto import email_digest, encrypt, decrypt

def throttled(request, namespace, identifier=''):
    # Hash identifiers; never log usernames, raw IPs, passwords or authenticator codes.
    parts = [request.META.get('REMOTE_ADDR','unknown')]
    if identifier: parts.append(identifier.lower())
    blocked = False
    with transaction.atomic():
        for part in parts:
            key = hashlib.sha256((namespace+':'+part).encode()).hexdigest()
            entry, _ = Throttle.objects.get_or_create(key=key)
            entry = Throttle.objects.select_for_update().get(pk=entry.pk)
            if timezone.now() - entry.window > timedelta(minutes=15):
                entry.count, entry.window = 0, timezone.now()
            entry.count += 1
            entry.save()
            blocked |= entry.count > 10
    if blocked: logging.getLogger('placement.security').warning('Authentication throttle triggered: %s', namespace)
    return blocked

def issue_token(user, purpose, hours=1):
    raw = secrets.token_urlsafe(32)
    Token.objects.filter(user=user,purpose=purpose,used=False).update(used=True)
    Token.objects.create(user=user,purpose=purpose,digest=hashlib.sha256(raw.encode()).hexdigest(),expires=timezone.now()+timedelta(hours=hours))
    route = 'reset' if purpose in {'reset','invite'} else 'token'
    try:
        send_mail('NFSU placement account action', f'Username: {user.username}\nOpen this single-use link within {hours} hour(s):\n{settings.SITE_URL}/{route}/{raw}/\nIf you did not request this, contact the Placement Cell.', settings.DEFAULT_FROM_EMAIL,[user.email])
    except Exception:
        logging.getLogger('placement.security').error('Account email delivery failed; use resend/recovery after SMTP is restored.')

def start_session(request, user):
    auth_login(request,user)
    request.session['started'] = request.session['last_activity'] = time.time()
    request.session['credential_version'] = user.credential_version
    request.session['mfa_verified'] = False
    request.session['recent_auth'] = time.time()

def login(request):
    form = LoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        if throttled(request,'login',form.cleaned_data['username']):
            form.add_error(None,'Too many attempts. Try again in 15 minutes.')
        else:
            user = authenticate(request,**form.cleaned_data)
            if user and user.email_verified and user.approved:
                start_session(request,user)
                audit.record(user,'auth.login')
                return redirect('mfa' if user.mfa_enabled or user.role in access.PRIVILEGED else 'dashboard')
            form.add_error(None,'Login unsuccessful. Check credentials and account approval.')
    return render(request,'form.html',{'form':form,'title':'Welcome back','subtitle':'Secure access to the NFSU placement workspace','auth_page':True,'submit':'Sign in'})

@require_POST
def logout(request):
    if request.user.is_authenticated: audit.record(request.user,'auth.logout')
    auth_logout(request)
    return redirect('login')

def signup(request):
    form = SignupForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        if throttled(request,'signup',form.cleaned_data['email']): form.add_error(None,'Too many attempts. Try later.')
        else:
            try:
                with transaction.atomic():
                    data = form.cleaned_data.copy()
                    user = User.objects.create_user(username=data.pop('username'),email=data.pop('email'),password=data.pop('password'))
                    SignupRequest.objects.create(user=user,**data)
                    audit.record(user,'account.signup')
                    transaction.on_commit(lambda: issue_token(user,'verify',24))
                messages.success(request,'Check your email for verification. Staff approval is required before login.')
                return redirect('login')
            except IntegrityError: form.add_error(None,'Account could not be created. Use account recovery or contact the Placement Cell.')
    return render(request,'form.html',{'form':form,'title':'Student registration','subtitle':'Verify your email, then await institutional approval.','auth_page':True,'submit':'Create account'})

def token(request, raw):
    item = get_object_or_404(Token,digest=hashlib.sha256(raw.encode()).hexdigest(),purpose='verify',used=False,expires__gt=timezone.now())
    if request.method=='POST':
        with transaction.atomic():
            item = Token.objects.select_for_update().get(pk=item.pk)
            if item.used or item.expires <= timezone.now(): raise PermissionDenied
            item.used = True
            item.save(update_fields=['used'])
            item.user.email_verified = True
            item.user.save(update_fields=['email_verified'])
            audit.record(item.user,'account.email_verified')
        messages.success(request,'Email verified. Your registration awaits Placement Cell approval.')
        return redirect('login')
    return render(request,'confirm.html',{'title':'Verify email address','description':'Confirm ownership of your registered email address.','submit':'Verify email','auth_page':True})

class EmailForm(StrictFormMixin,forms.Form):
    email = forms.EmailField()

def forgot(request):
    form = EmailForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        if not throttled(request,'reset',form.cleaned_data['email']):
            user = User.objects.filter(email_digest=email_digest(form.cleaned_data['email']),approved=True,email_verified=True,is_active=True).first()
            if user:
                issue_token(user,'reset')
                audit.record(user,'account.reset_requested')
        messages.success(request,'If an eligible account exists, a recovery email has been sent.')
        return redirect('login')
    return render(request,'form.html',{'form':form,'title':'Account recovery','auth_page':True,'submit':'Send recovery link'})

def resend(request):
    form = EmailForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        if not throttled(request,'resend',form.cleaned_data['email']):
            user = User.objects.filter(email_digest=email_digest(form.cleaned_data['email']),email_verified=False,is_active=True).first()
            if user:
                issue_token(user,'verify' if user.role=='student' else 'invite',24)
                audit.record(user,'account.verification_resent')
        messages.success(request,'If an unverified account exists, a new email has been sent.')
        return redirect('login')
    return render(request,'form.html',{'form':form,'title':'Resend verification','auth_page':True,'submit':'Send verification link'})

class PasswordForm(StrictFormMixin,forms.Form):
    password = forms.CharField(widget=forms.PasswordInput,min_length=12)
    def __init__(self,*args,user=None,**kwargs):
        self.user=user
        super().__init__(*args,**kwargs)
    def clean_password(self):
        validate_password(self.cleaned_data['password'],user=self.user)
        return self.cleaned_data['password']

def reset(request, raw):
    item = get_object_or_404(Token,digest=hashlib.sha256(raw.encode()).hexdigest(),purpose__in=['reset','invite'],used=False,expires__gt=timezone.now())
    form = PasswordForm(request.POST or None,user=item.user)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            item = Token.objects.select_for_update().get(pk=item.pk)
            if item.used or item.expires<=timezone.now(): raise PermissionDenied
            user = User.objects.select_for_update().get(pk=item.user_id)
            user.set_password(form.cleaned_data['password'])
            user.credential_version += 1
            if item.purpose=='invite': user.email_verified = True
            user.save()
            item.used = True
            item.save()
            audit.record(user,'account.password_reset')
        messages.success(request,'Password set. Sign in using your username: '+user.username)
        return redirect('login')
    return render(request,'form.html',{'form':form,'title':'Set your password','auth_page':True,'submit':'Save password'})

def check_totp(user, code):
    # Lock caller's user row; require a fresh step to prevent code replay.
    totp = pyotp.TOTP(user.mfa_secret)
    step = int(time.time())//30
    for candidate in (step-1,step,step+1):
        if candidate > user.mfa_last_step and secrets.compare_digest(totp.at(candidate*30),code):
            user.mfa_last_step = candidate
            user.save(update_fields=['mfa_last_step'])
            return True
    return False

@login_required
def mfa(request):
    enrolling = not request.user.mfa_enabled
    if enrolling and not recent(request): return redirect('reauth')
    if enrolling and not request.session.get('enrollment_secret'):
        request.session['enrollment_secret'] = encrypt(pyotp.random_base32())
    form = MFAForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        if throttled(request,'mfa',str(request.user.pk)): form.add_error(None,'Too many attempts. Try later.')
        else:
            with transaction.atomic():
                user = User.objects.select_for_update().get(pk=request.user.pk)
                if enrolling and user.mfa_enabled:
                    request.session.pop('enrollment_secret',None)
                    messages.info(request,'Authenticator setup was completed in another session. Enter a code from that authenticator.')
                    return redirect('mfa')
                if enrolling: user.mfa_secret = decrypt(request.session['enrollment_secret'])
                if check_totp(user,form.cleaned_data['code']):
                    user.mfa_enabled = True
                    user.save(update_fields=['mfa_secret','mfa_enabled'])
                    request.session.pop('enrollment_secret',None)
                    request.session.cycle_key()
                    request.session['mfa_verified'] = True
                    request.session['recent_auth'] = time.time()
                    audit.record(user,'auth.mfa_enroll' if enrolling else 'auth.mfa_verify')
                    return redirect('dashboard')
                form.add_error('code','Code not accepted. Use the latest six-digit code, check your phone uses automatic time, and wait for a new code if this one was already used.')
    secret = decrypt(request.session['enrollment_secret']) if enrolling else ''
    uri = pyotp.TOTP(secret).provisioning_uri(request.user.username,issuer_name='NFSU Placement') if enrolling else ''
    qr_image = ''
    if enrolling:
        output = io.BytesIO()
        qrcode.make(uri,image_factory=qrcode.image.svg.SvgPathImage).save(output)
        qr_image = 'data:image/svg+xml;base64,' + base64.b64encode(output.getvalue()).decode()
    return render(request,'mfa.html',{'form':form,'title':'Set up authenticator' if enrolling else 'Two-step verification',
                                    'secret':secret,'qr_image':qr_image,'enrolling':enrolling})

def recent(request):
    if time.time()-request.session.get('recent_auth',0)>300: return False
    return True

@login_required
def reauth(request):
    class Form(LoginForm):
        code = forms.RegexField(r'^\d{6}$',required=False,label='Authenticator code',help_text='Enter the current six-digit code from your NFSU Placement authenticator account.',
                               widget=forms.TextInput(attrs={'autocomplete':'one-time-code','inputmode':'numeric'}))
    form = Form(request.POST or None,initial={'username':request.user.username})
    form.fields['username'].disabled = True
    if not request.user.mfa_enabled:
        form.fields.pop('code')
    else:
        form.fields['code'].required = True
    if request.method=='POST' and form.is_valid():
        if not throttled(request,'reauth',str(request.user.pk)):
            with transaction.atomic():
                user = User.objects.select_for_update().get(pk=request.user.pk)
                if (form.cleaned_data['username']==user.username and user.check_password(form.cleaned_data['password']) and
                    (not user.mfa_enabled or check_totp(user,form.cleaned_data.get('code','')))):
                    request.session['recent_auth'] = time.time()
                    request.session['mfa_verified'] = user.mfa_enabled
                    request.session.cycle_key()
                    audit.record(user,'auth.reauthenticate')
                    return redirect('dashboard')
        form.add_error(None,'Verification unsuccessful.')
    subtitle = 'Enter your password and a fresh six-digit authenticator code to continue.' if request.user.mfa_enabled else 'Enter your password to continue. No authenticator code is needed until setup is complete.'
    return render(request,'form.html',{'form':form,'title':'Confirm your identity','subtitle':subtitle,'submit':'Verify identity'})

@login_required
def invite(request):
    access.require_admin(request.user)
    if not recent(request): return redirect('reauth')
    form = InviteForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                data = form.cleaned_data.copy()
                data['email'] = data['email'].lower()
                user = User(username='account-'+secrets.token_hex(6),approved=True,**data)
                user.set_unusable_password()
                user.save()
                audit.record(request.user,'account.invite',user.pk,{'role':user.role,'courses':user.courses,'company_id':user.company_id})
                transaction.on_commit(lambda: issue_token(user,'invite',24))
            messages.success(request,'Invitation sent.')
            return redirect('accounts')
        except IntegrityError: form.add_error('email','An account already exists.')
    return render(request,'form.html',{'form':form,'title':'Invite staff or recruiter','submit':'Send invitation'})
