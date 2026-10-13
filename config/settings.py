"""Fail closed in production; local development requires generated secrets too."""
import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')
PRODUCTION = os.getenv('APP_ENV') == 'production'
DEBUG = not PRODUCTION

def required(name):
    value = os.getenv(name)
    if not value:
        raise ImproperlyConfigured(f'{name} must be set; run scripts/setup_local.py for development')
    return value

SECRET_KEY = required('DJANGO_SECRET_KEY')
DATA_KEYS = required('DATA_KEYS')  # comma separated key-id:fernet-key, first is current
AUDIT_KEY = required('AUDIT_KEY')
LOOKUP_KEY = required('LOOKUP_KEY')
from cryptography.fernet import Fernet
try:
    pairs = [pair.split(':', 1) for pair in DATA_KEYS.split(',')]
    if len({pair[0] for pair in pairs}) != len(pairs): raise ValueError('Duplicate key version')
    for version,key in pairs:
        if not version or len(version)>20: raise ValueError('Invalid key version')
        Fernet(key.encode())
except (ValueError, TypeError) as exc:
    raise ImproperlyConfigured('DATA_KEYS requires unique version:fernet-key entries') from exc
if PRODUCTION and any(len(value)<50 for value in (SECRET_KEY,AUDIT_KEY,LOOKUP_KEY)):
    raise ImproperlyConfigured('Production signing and lookup secrets must be independently generated and at least 50 characters')
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver').split(',')
CSRF_TRUSTED_ORIGINS = [s for s in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if s]
INSTALLED_APPS = ['django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions',
                  'django.contrib.messages', 'django.contrib.staticfiles', 'placement']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware',
              'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware',
              'django.contrib.auth.middleware.AuthenticationMiddleware', 'placement.middleware.SessionGuard',
              'django.contrib.messages.middleware.MessageMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware',
              'placement.middleware.SecurityHeaders']
ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [BASE_DIR / 'templates'],
              'APP_DIRS': True, 'OPTIONS': {'context_processors': ['django.template.context_processors.request',
              'django.contrib.auth.context_processors.auth', 'django.contrib.messages.context_processors.messages',
              'placement.context_processors.security_state']}}]
if os.getenv('DB_HOST'):
    DATABASES = {'default': {'ENGINE': 'django.db.backends.postgresql', 'NAME': required('DB_NAME'),
                 'USER': required('DB_USER'), 'PASSWORD': required('DB_PASSWORD'), 'HOST': required('DB_HOST'),
                 'PORT': os.getenv('DB_PORT', '5432'), 'CONN_MAX_AGE': 60,
                 'OPTIONS': {'sslmode': os.getenv('DB_SSLMODE', 'require' if PRODUCTION else 'prefer')}}}
    if os.getenv('DB_SSLROOTCERT'):
        DATABASES['default']['OPTIONS']['sslrootcert'] = os.environ['DB_SSLROOTCERT']
    if PRODUCTION and DATABASES['default']['OPTIONS']['sslmode'] != 'verify-full':
        raise ImproperlyConfigured('Production PostgreSQL requires verify-full TLS and a trusted root certificate')
elif PRODUCTION:
    raise ImproperlyConfigured('Production requires PostgreSQL')
else:
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'dev.sqlite3'}}
AUTH_USER_MODEL = 'placement.User'
PASSWORD_HASHERS = ['django.contrib.auth.hashers.Argon2PasswordHasher']
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 12}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'}]
LANGUAGE_CODE = 'en-in'
TIME_ZONE = 'Asia/Kolkata'
USE_TZ = True
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = '/login/'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 8 * 3600
SESSION_IDLE_SECONDS = 1800
SESSION_ABSOLUTE_SECONDS = 8 * 3600
SESSION_COOKIE_SECURE = PRODUCTION
CSRF_COOKIE_SECURE = PRODUCTION
SESSION_COOKIE_NAME = '__Host-sessionid' if PRODUCTION else 'sessionid'
SECURE_SSL_REDIRECT = PRODUCTION
SECURE_HSTS_SECONDS = 31536000 if PRODUCTION else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = PRODUCTION
SECURE_HSTS_PRELOAD = PRODUCTION
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
# Set only when an operator confirms that the trusted proxy strips spoofed headers.
if os.getenv('TRUST_PROXY') == '1':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend' if PRODUCTION else 'django.core.mail.backends.filebased.EmailBackend'
EMAIL_FILE_PATH = BASE_DIR / '.local-mail'
EMAIL_HOST = os.getenv('EMAIL_HOST', '')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = True
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'placement@localhost')
SITE_URL = os.getenv('SITE_URL', 'http://127.0.0.1:8000').rstrip('/')
RETENTION_DAYS = int(os.getenv('RETENTION_DAYS', '0'))
if PRODUCTION and (not SITE_URL.startswith('https://') or not EMAIL_HOST):
    raise ImproperlyConfigured('Production requires HTTPS SITE_URL and SMTP EMAIL_HOST')
LOGGING = {'version': 1, 'disable_existing_loggers': False,
           'handlers': {'console': {'class': 'logging.StreamHandler'}},
           'loggers': {'placement.security': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False}}}
