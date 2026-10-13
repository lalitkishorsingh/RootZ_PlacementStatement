import getpass
from django.contrib.auth.password_validation import validate_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from placement.models import User
from placement import audit

class Command(BaseCommand):
    help = 'Interactively bootstrap the first administrator; no default credentials.'
    @transaction.atomic
    def handle(self,*args,**options):
        if User.objects.filter(role='admin').exists(): raise CommandError('An administrator already exists. Use the invitation workflow.')
        username = input('Username: ').strip()
        from django.core.validators import validate_email
        email = input('Verified institutional email: ').strip().lower()
        validate_email(email)
        password = getpass.getpass('Password: ')
        validate_password(password,user=User(username=username,email=email))
        if password != getpass.getpass('Confirm password: '): raise CommandError('Passwords do not match.')
        user = User.objects.create_user(username=username,email=email,password=password,role='admin',approved=True,email_verified=True)
        audit.record(user,'account.bootstrap_admin')
        self.stdout.write('Administrator created. MFA enrollment is required at first login.')
