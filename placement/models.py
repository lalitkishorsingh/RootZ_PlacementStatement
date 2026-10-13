import uuid
from decimal import Decimal
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from .crypto import EncryptedTextField, email_digest

COURSES = [('MTECH_CS', 'M.Tech. Computer Science'), ('MTECH_AIDS', 'M.Tech. Artificial Intelligence and Data Science'),
           ('BTECH_MTECH_CS', 'B.Tech.–M.Tech. Computer Science and Engineering'),
           ('MSC_CS', 'M.Sc. Computer Science'), ('MSC_DFIS', 'M.Sc. Digital Forensics and Information Security')]
TYPES = [('I', 'Internship'), ('F', 'Full-time'), ('IF', 'Internship + PPO/FTE')]

class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'admin', 'Administrator'
        OFFICER = 'officer', 'Placement officer'
        COORDINATOR = 'coordinator', 'Course coordinator'
        RECRUITER = 'recruiter', 'Recruiter'
        STUDENT = 'student', 'Student'
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.STUDENT)
    email = EncryptedTextField()
    email_digest = models.CharField(max_length=64, unique=True)
    email_verified = models.BooleanField(default=False)
    approved = models.BooleanField(default=False)
    courses = models.JSONField(default=list, blank=True)
    company = models.ForeignKey('Company', null=True, blank=True, on_delete=models.PROTECT)
    mfa_secret = EncryptedTextField(blank=True)
    mfa_enabled = models.BooleanField(default=False)
    mfa_last_step = models.BigIntegerField(default=-1)
    credential_version = models.PositiveIntegerField(default=1)

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        self.email_digest = email_digest(self.email)
        if kwargs.get('update_fields') and 'email' in kwargs['update_fields']:
            kwargs['update_fields'] = set(kwargs['update_fields']) | {'email_digest'}
        super().save(*args, **kwargs)

class Company(models.Model):
    name = models.CharField(max_length=180, unique=True)
    website = models.URLField(blank=True)
    def __str__(self): return self.name

class Student(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    placement_id = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=180)
    email = EncryptedTextField()
    mobile = EncryptedTextField(blank=True)
    course = models.CharField(max_length=24, choices=COURSES)
    batch = models.CharField(max_length=20)
    registration = models.CharField(max_length=16, choices=[('registered','Registered'), ('deregistered','Deregistered'), ('not_registered','Not registered')], default='not_registered')
    eligibility = models.CharField(max_length=16, choices=[('eligible','Eligible'), ('ineligible','Ineligible'), ('pending','Pending verification')], default='pending')
    academic_score = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    user = models.OneToOneField(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='student')
    archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self): return f'{self.placement_id} · {self.name}'

class SignupRequest(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    placement_id = models.CharField(max_length=40)
    name = models.CharField(max_length=180)
    course = models.CharField(max_length=24, choices=COURSES)
    batch = models.CharField(max_length=20)
    mobile = EncryptedTextField(blank=True)

class Token(models.Model):
    digest = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    purpose = models.CharField(max_length=12)
    expires = models.DateTimeField()
    used = models.BooleanField(default=False)

class Throttle(models.Model):
    key = models.CharField(max_length=64, unique=True)
    count = models.PositiveIntegerField(default=0)
    window = models.DateTimeField(default=timezone.now)

class Policy(models.Model):
    version = models.CharField(max_length=40, unique=True)
    config = models.JSONField(default=dict)
    active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['active'], condition=models.Q(active=True), name='one_active_policy')]

class Drive(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    title = models.CharField(max_length=180)
    offer_type = models.CharField(max_length=2, choices=TYPES)
    ctc = EncryptedTextField(blank=True)
    stipend = EncryptedTextField(blank=True)
    stipend_period = models.CharField(max_length=12, choices=[('month','Monthly'), ('week','Weekly'), ('total','Total')], blank=True)
    courses = models.JSONField(default=list)
    min_score = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    scheduled_at = models.DateTimeField()
    closes_at = models.DateTimeField()
    open = models.BooleanField(default=True)
    def __str__(self): return f'{self.company.name} · {self.title}'

class Application(models.Model):
    student = models.ForeignKey(Student, on_delete=models.PROTECT)
    drive = models.ForeignKey(Drive, on_delete=models.PROTECT)
    status = models.CharField(max_length=16, choices=[('submitted','Submitted'), ('approved','Approved'), ('rejected','Rejected')], default='submitted')
    decision = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['student','drive'], name='one_application')]

class Offer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name='offers')
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    drive = models.ForeignKey(Drive, null=True, blank=True, on_delete=models.PROTECT)
    offer_type = models.CharField(max_length=2, choices=TYPES)
    ctc = EncryptedTextField(blank=True)
    stipend = EncryptedTextField(blank=True)
    stipend_period = models.CharField(max_length=12, blank=True, choices=[('month','Monthly'), ('week','Weekly'), ('total','Total')])
    verified = models.BooleanField(default=False)
    withdrawn = models.BooleanField(default=False)
    acceptance = models.CharField(max_length=12, default='pending', choices=[('pending','Pending'), ('accepted','Accepted'), ('declined','Declined'), ('expired','Expired')])
    ppo = models.CharField(max_length=12, default='na', choices=[('na','Not applicable'), ('pending','Pending'), ('offered','Offered'), ('accepted','Accepted'), ('declined','Declined')])
    joining = models.CharField(max_length=12, default='pending', choices=[('pending','Pending'), ('joined','Joined'), ('not_joined','Not joined')])
    noc = models.CharField(max_length=12, default='na', choices=[('na','Not applicable'), ('pending','Pending'), ('issued','Issued'), ('denied','Denied')])
    issued_at = models.DateTimeField()
    company_deadline = models.DateTimeField(null=True, blank=True)
    deadline = models.DateTimeField()
    submitted_by = models.ForeignKey(User, on_delete=models.PROTECT)
    decision = models.JSONField(default=dict)
    off_campus = models.BooleanField(default=False)
    remarks = models.TextField(blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['student','drive'], condition=models.Q(drive__isnull=False), name='one_drive_offer')]

class Attendance(models.Model):
    student = models.ForeignKey(Student, on_delete=models.PROTECT)
    drive = models.ForeignKey(Drive, on_delete=models.PROTECT)
    activity = models.CharField(max_length=80)
    present = models.BooleanField(default=True)
    recorded_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['student','drive','activity'], name='one_attendance')]

class Review(models.Model):
    student = models.ForeignKey(Student, on_delete=models.PROTECT)
    kind = models.CharField(max_length=20, choices=[('absence','Absence'), ('correction','Profile correction'), ('policy','Policy conflict'), ('joining','Joining / NOC update')])
    details = models.TextField()
    status = models.CharField(max_length=12, choices=[('pending','Pending'), ('approved','Approved'), ('rejected','Rejected')], default='pending')
    resolution = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class Sanction(models.Model):
    student = models.ForeignKey(Student, on_delete=models.PROTECT)
    review = models.OneToOneField(Review, on_delete=models.PROTECT)
    drives = models.ManyToManyField(Drive)
    active = models.BooleanField(default=True)
    reason = models.TextField()

class ExceptionGrant(models.Model):
    student = models.ForeignKey(Student, on_delete=models.PROTECT)
    drive = models.ForeignKey(Drive, on_delete=models.PROTECT)
    reason = models.TextField()
    expires = models.DateTimeField()
    approved_by = models.ForeignKey(User, on_delete=models.PROTECT)
    revoked = models.BooleanField(default=False)

class AuditHead(models.Model):
    id = models.PositiveIntegerField(primary_key=True, default=1)
    digest = models.CharField(max_length=64, default='0'*64)

class AuditEvent(models.Model):
    occurred_at = models.DateTimeField(default=timezone.now)
    actor_id_ref = models.CharField(max_length=40)
    action = models.CharField(max_length=80)
    target = models.CharField(max_length=160)
    details = models.JSONField(default=dict)
    previous = models.CharField(max_length=64)
    digest = models.CharField(max_length=64)

class ImportBatch(models.Model):
    owner = models.ForeignKey(User, on_delete=models.PROTECT)
    payload = EncryptedTextField()
    created_at = models.DateTimeField(auto_now_add=True)
    committed = models.BooleanField(default=False)
