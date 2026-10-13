# NFSU Student Placement Management System

A placement management application for the National Forensic Sciences University, designed around the supplied 2026–27 placement requirements. Students, recruiters and Placement Cell staff use separate, scoped workflows. Verified selections retain their history, policy decisions explain their reasons, and accepted offers determine placement statistics.

The local database contains **synthetic demonstration data only**. This is a student project prepared for institutional evaluation, not an officially approved NFSU service. The provisional policy must be checked against the official guidelines before real student records are entered.

## Run on Windows

The workspace is already configured with a virtual environment, generated local secrets, migrations, and 25 synthetic students. Start the application from this folder:

```powershell
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --noreload
```

Open [the local placement portal](http://127.0.0.1:8000). Unique demonstration passwords are in `.local-demo-accounts.json`; this file is excluded from version control. Accounts are `placement.admin`, `placement.officer`, `dfis.coordinator`, `sentinel.recruiter`, and `demo.student`. Staff must enroll an authenticator on their first login. In your phone's authenticator, add an account by scanning the displayed QR code, or enter its setup key as a time-based (TOTP) account. Type the current six-digit code into the portal and click Verify code. The setup key is not the verification code. Menu pages unlock after verification. If password confirmation expires before enrollment, re-enter your password; no authenticator code is required until setup is complete.

For a fresh checkout:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe scripts/setup_local.py
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_demo
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --noreload
```

`seed_demo` refuses to run in production or in a database containing accounts. For an empty institutional database, use `bootstrap_admin` instead. There are no default production passwords. `scripts/start.ps1` provides a convenient development startup script.

Local email messages are captured in `.local-mail`. Signup requires a verification link followed by administrator approval against an independently maintained student record. An existing Placement ID does not grant ownership. Staff invitations include a username and a single-use password setup link. Recovery preserves MFA; an administrator can reset MFA only after independent identity verification and recent reauthentication.

SQLite supports a single-user local evaluation. PostgreSQL is required for production and for verifying concurrent policy enforcement. Django uses UTC storage and Asia/Kolkata display time.

## NFSU workflows

1. Administrators or officers create companies and drives. Staff create or import institutional student records across the five specified programmes.
2. Students register and verify their email. An administrator matches the Placement ID, programme and email to an institutional record and records the approval reason.
3. Coordinators verify registration, eligibility and academic scores within assigned programmes.
4. Students see policy decisions for available drives and submit allowed applications. Staff approve applications after another policy check.
5. Recruiters see only approved applicants for their company. They submit selections for Placement Cell verification. Students can also report off-campus offers for review.
6. Staff verify actual compensation and selection against current policy. Students accept or decline within the earlier of 24 hours or the company deadline.
7. Staff record attendance, PPO, joining and NOC updates. Absence cases require authorized review before a three-drive sanction is imposed.
8. Course, batch, company and switching-eligibility reports distinguish unique students, offer counts, annual CTC and internship stipends.

Profile corrections, joining updates and suspected violations enter review queues. Approval of a review records a decision; staff must apply any corresponding verified record change explicitly. All substantive changes are audited.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
$env:RUN_BROWSER_TESTS='1'
$env:BROWSER_CHANNEL='chrome'
.\.venv\Scripts\python.exe manage.py test placement.tests --verbosity 2
.\.venv\Scripts\python.exe -m pip_audit -r requirements.lock
```

Browser tests use installed Chrome on Windows. For Playwright Chromium, set `BROWSER_CHANNEL=chromium` and run `python -m playwright install chromium`. PostgreSQL tests need a **separate disposable database and a test user able to create databases and roles**; never run them with production data or production runtime credentials.

The GitHub Actions workflow supplies PostgreSQL and Chromium and runs the same tests, including concurrency and database privilege checks. See [verification evidence](docs/verification.md) for the completed local checks and remaining deployment checks.

## Technical handover

- [Architecture and permission matrix](docs/architecture.md)
- [Security design and policy assumptions](docs/security.md)
- [Institutional deployment and recovery](docs/operations.md)
- [Verification evidence and release conditions](docs/verification.md)
- [Official logo and website colour sources](docs/branding.md)

The current workspace is inside OneDrive. Keep this checkout limited to synthetic data; deploy institutional data on university-controlled infrastructure with protected secrets, encrypted disks and backups, and a configured retention policy.
