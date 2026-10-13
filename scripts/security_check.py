"""Run Django's production configuration checks without connecting to production."""
import os
from pathlib import Path
import subprocess
import sys
from dotenv import load_dotenv

root=Path(__file__).resolve().parent.parent
load_dotenv(root/'.env')
env=os.environ.copy()
env.update(APP_ENV='production',SITE_URL='https://placement.example.edu',ALLOWED_HOSTS='placement.example.edu',
           CSRF_TRUSTED_ORIGINS='https://placement.example.edu',EMAIL_HOST='smtp.example.edu',
           DB_HOST='127.0.0.1',DB_NAME='configuration_check_only',DB_USER='configuration_check_only',
           DB_PASSWORD='configuration_check_only',DB_SSLMODE='verify-full')
result=subprocess.run([sys.executable,'manage.py','check','--deploy','--fail-level','WARNING'],cwd=root,env=env)
raise SystemExit(result.returncode)
