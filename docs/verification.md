# NFSU Placement Verification Evidence

Local verification on 13 October 2026 used Windows, Python 3.14.8, Django 5.2.18, SQLite, and installed Chrome. The application is ready for local synthetic-data evaluation. Institutional release depends on the PostgreSQL and infrastructure checks below.

## Completed checks

| Check | Observed result |
| --- | --- |
| Automated suite with real browser tests enabled | 66 tests run; 64 passed; 2 PostgreSQL-specific tests skipped |
| Django system checks | No issues |
| Production configuration security check | `check --deploy --fail-level WARNING` passed using isolated configuration values; no connection to production |
| Migration drift | `makemigrations --check --dry-run` found no changes |
| Runtime dependency audit | 19 resolved runtime packages; no known vulnerabilities reported by pip-audit |
| Audit-chain verification | Passed for the local demonstration database |
| Encrypted backup and isolated recovery | Restored 25 synthetic student records and 7 offers; audit checkpoint matched and encrypted fields decrypted |
| Tampered snapshot and populated restore target | Rejected by automated recovery tests |
| Desktop and mobile browser rendering | Reviewed at 1440×1000 and 390×844; no page-width overflow; keyboard focus check passed |

The dependency result is recorded in `artifacts-dependency-audit.json`; `requirements.lock` pins those resolved runtime versions. A clean dependency scan indicates no known findings in that scan, not the absence of application vulnerabilities.

## Functional and attack scenarios

The suite verifies every role against the sensitive route permission matrix; student record/offer isolation; coordinator course scope; recruiter company scope; prevention of automatic Placement ID claiming; approval against matching institutional email; unexpected-role/verified-field rejection; CSRF protection; escaped stored content; parameterized search; bounded/formula-free imports; atomic import revalidation; and formula-safe exports.

Policy tests cover the ₹6/₹10/₹16 boundaries, exact 1.5× switching, offer-type precedence, internship treatment, A+ exit, combined selections, multiple previous offers, missing evidence, exceptions, archival hard blocks and attendance sanctions. Workflow tests cover repeated applications, current policy checks at approval, actual offer CTC at verification, verified acceptance, expired deadlines, accepted unique-student counts and separate stipend/FTE reporting.

Identity tests cover Argon2 storage, privileged MFA gating, one-time authenticator codes, optional enrollment reauthentication, login throttling, unverified/unapproved login rejection, single-use verification/reset links, session idle/absolute expiry, credential revocation, cookie flags and MFA preservation on recovery. Audit tests demonstrate tamper detection and rollback of a sensitive change when audit writing fails.

Six real-browser workflows cover administrator account approval, coordinator editing, student registration/empty states, first-login QR enrollment/password reconfirmation, every visible navigation link for all five roles, and the complete student application → officer approval → recruiter offer submission → officer verification → student acceptance sequence. Screenshots are generated under `artifacts/` and contain synthetic test records only. Before required MFA is complete, inaccessible operational menus are hidden and the page explains how to unlock the workspace. Reauthentication requests a six-digit code only after MFA enrollment.

## PostgreSQL and institutional release conditions

Two tests explicitly skip on SQLite: simultaneous conflicting selections under PostgreSQL row locking, and runtime database rejection of audit modification/deletion/truncation and schema dropping. The supplied GitHub Actions workflow provisions PostgreSQL to run these checks; that workflow has not been executed from this local workspace.

Docker Compose was prepared but could not be built or launched here because Docker is not installed. PostgreSQL TLS, production SMTP, public HTTPS certificates, disk encryption, PostgreSQL backup/restore, immutable external checkpoint storage and alert delivery have not been exercised locally. The SQLite recovery result does not prove PostgreSQL recovery.

Before institutional release, require:

1. A passing PostgreSQL CI run, followed by a production-like Compose build/deployment and runtime-permission verification.
2. University approval of the official placement-policy interpretations and the student/recruiter permission matrix.
3. Verified TLS on both browser and database connections, separate owner/runtime credentials, protected encryption keys, encrypted disks and backups, and functioning SMTP.
4. A PostgreSQL restoration exercise with measured recovery time, audit verification and representative placement reports.
5. Approved retention/anonymization rules, independently protected audit checkpoints, monitored scheduled jobs and tested incident alerts.
6. Independent security review and resolution of exploitable high/critical findings before processing real student data.

No public deployment, official NFSU approval or independent penetration-test certification is claimed.
