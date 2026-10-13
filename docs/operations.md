# NFSU Placement Deployment and Recovery

Use university-controlled hosting for institutional data. The deployment supplies Django, PostgreSQL, an HTTPS proxy and a deadline/audit scheduler. Production secrets, DNS, SMTP, storage encryption, certificate management, retention rules and external monitoring must be configured by the university operator.

## Production configuration

1. Install Docker Engine/Compose on the deployment host. Use a maintained host OS and an encrypted disk for Docker volumes, snapshots and swap.
2. Generate independent production secrets. Use `.env.example` as a variable list, never its placeholder values. Store secrets outside this source checkout with restrictive permissions or inject them from a secret manager. Do not copy development secrets or demonstration accounts into production.
3. Set `APP_ENV=production`, the real HTTPS `SITE_URL`, `PUBLIC_HOST`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, SMTP settings and separate migration-owner/runtime database passwords. `DB_USER=placement_app` is fixed by the supplied deployment.
4. Supply a protected PostgreSQL TLS directory containing `server.crt`, `server.key` and `ca.crt`. The server certificate must have `db` in its subject alternative names for the Compose hostname. The server key must be owned by the PostgreSQL container user (UID/GID 70 for the supplied Alpine image) with mode 0600. Client containers receive only `ca.crt`. Set `DB_SSLMODE=verify-full` and `DB_SSLROOTCERT=/run/postgres-tls/ca.crt`. A valid internal CA certificate and hostname verification are required; disabling TLS is rejected in production.
5. Set `POSTGRES_TLS_DIR` to that protected absolute directory. Set `TRUST_PROXY=1` only for the supplied Caddy proxy or an equivalent proxy that strips spoofed forwarding headers. The web/database ports are not published directly.
6. Review and pin approved container-image digests for deployment. `requirements.lock` pins the scanned Python runtime. Build and run `docker compose up --build -d` using protected environment configuration.
7. Run `docker compose run --rm migrate python manage.py check --deploy` and inspect service health/logs. Run `docker compose run --rm migrate python manage.py bootstrap_admin`. The first administrator must enroll MFA.
8. Publish an official-policy-validated configuration through the administrator portal. Import independently verified institutional records. Test account approval, email delivery, recruiter scope, export authorization and acceptance deadlines using controlled pilot records before wider rollout.

`migrate` owns schema changes and grants restricted privileges to `placement_app`. The web and scheduler use the runtime role. Audit events deny UPDATE, DELETE and TRUNCATE. Runtime cannot modify migration history or create/drop schema objects. Do not give the web container the owner password.

The database network is internal. Only Caddy publishes HTTP/HTTPS; it redirects public HTTP to HTTPS and serves collected static assets. Web and scheduler run without root, with a read-only filesystem, no added capabilities, and a temporary `/tmp` mount. The database client uses verified TLS across the internal network.

## Local and PostgreSQL verification

Development can use the generated SQLite database. To test PostgreSQL, supply `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` and `DB_SSLMODE` for a disposable database. The test user must have CREATEDB and CREATEROLE, while the production runtime role must not. The PostgreSQL tests check simultaneous conflicting selections and rejection of audit modification/drop operations.

Do not point test or demonstration commands at a production database. The CI workflow provisions an isolated PostgreSQL service for these checks. A CI pass is still required because this Windows workspace has neither PostgreSQL nor Docker installed.

## Backups and recovery

`scripts/backup.py` captures a consistent SQLite snapshot or PostgreSQL custom-format dump in memory and writes only authenticated encrypted data. It requires an externally configured `BACKUP_KEY`; `pg_dump` and `pg_restore` are needed for PostgreSQL. Dumps exclude ownership and ACLs, so privileges must be reapplied after recovery.

```powershell
.\.venv\Scripts\python.exe scripts/backup.py create backups/placement-20261013.enc
.\.venv\Scripts\python.exe manage.py verify_audit --checkpoint artifacts/audit-checkpoint.json
.\.venv\Scripts\python.exe scripts/backup.py restore backups/placement-20261013.enc --target artifacts/restored-placement.sqlite3
.\.venv\Scripts\python.exe scripts/verify_recovery.py artifacts/restored-placement.sqlite3 --checkpoint artifacts/audit-checkpoint.json
```

For PostgreSQL, `--target` names a separately created empty database. Use a restore operator with schema creation rights, not the restricted runtime role. Restoration refuses a populated database and uses a single transaction. Supply the same key ring and stable audit/lookup keys when verifying recovered data. Do not promote a restored database until audit verification, migration checks, representative reporting and user workflows pass.

Run daily encrypted backups from a dedicated operator environment and replicate them to encrypted university-controlled storage. Keep encryption keys in independently backed-up protected storage. Copy signed audit checkpoints to independently administered immutable storage. Schedule regular restore exercises and record recovery time and restored event/record counts. The provided backup utility buffers the snapshot in memory; large institutional deployments need a reviewed streaming/envelope-encryption backup process.

## Monitoring and incident response

The Compose scheduler expires offers and verifies the audit chain every minute. Request-time deadline checks remain authoritative even when scheduling is delayed. Offer expiration also prunes expired tokens, imports and old throttle counters. Monitor `/health/` through HTTPS and alert on unhealthy services, scheduler failures, repeated authentication throttles, email delivery errors, audit-integrity failures and failed backups.

`placement.security` emits redacted security warnings/errors. Configure the university's log collector and alert destinations; the application does not send external incident messages by default. Protect audit logs and avoid enabling proxy access logs containing verification/reset URLs.

On suspected compromise, restrict public access, preserve external checkpoints/logs, revoke sessions through credential versions, isolate the affected host/database and investigate against a verified backup. Key rotation must preserve access to retained backups and audit history.

For contact/compensation key rotation, stop web/scheduler processes, prepend a new key version to `DATA_KEYS`, retain old versions, then run `manage.py rotate_data_keys --maintenance-confirmed`. Clear active sessions and restart only after a restore/read check. Do not casually rotate `LOOKUP_KEY` or `AUDIT_KEY`; their index/history migrations need separate planning.

## Retention and authorized cleanup

`RETENTION_DAYS=0` disables permanent anonymization. Ordinary staff workflows archive rather than delete. The university must approve a retention period before the operator enables anonymization.

```powershell
.\.venv\Scripts\python.exe manage.py anonymize_student NFSU-ID --admin placement.admin --reason "Approved institutional retention request"
```

This command requires an active approved administrator, password, fresh MFA, an archived record and elapsed retention. It anonymizes contact/name/account data, removes registration claims and tokens, and clears review details and offer remarks while retaining aggregate outcomes and audit references. Audit reasons may contain personal information and remain governed by a separate institutional audit-retention policy. Existing downloads, email captures and retained backups require their own cleanup schedule.

`manage.py revoke_exception ID --admin USERNAME --reason "..."` provides an authenticated operator workflow for revoking drive exceptions. Account MFA recovery is available in the administrator portal and requires independent identity evidence and an audited reason.
