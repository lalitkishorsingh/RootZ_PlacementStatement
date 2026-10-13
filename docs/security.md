# NFSU Placement Security Design

The primary application threats are unauthorized student changes, cross-student access, cross-course access, cross-company disclosure, forged requests, policy bypass, concurrent selections and unreliable imports or reports. Controls are backed by automated tests; they do not establish absolute security or institutional certification.

## Identity and authorization

Passwords use Argon2id and Django password validators with a minimum length of 12. Accounts require verified email and approval before login. Privileged staff enroll TOTP MFA before accessing operational pages. Codes are rate limited and accepted once per time step; MFA secrets and temporary enrollment secrets are encrypted at rest.

Server-side sessions use HttpOnly, SameSite=Lax cookies and CSRF tokens. Production cookies require HTTPS. Sessions rotate during login/MFA and expire after 30 minutes idle or eight hours absolute lifetime. Password resets and authorization changes increment the credential version to revoke existing sessions. Resetting a password does not remove MFA.

Authorization uses deny-by-default role, object, course, company and field checks. Forms explicitly reject extra fields, including attempts to submit verified placement status or account roles. Student signup never automatically binds an account to a Placement ID. Recruiters never receive other organizations' offer history or compensation.

The implementation follows [OWASP authorization guidance](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html) and [session guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html). Authentication throttling uses hashed account/IP identifiers, not plaintext identifiers in operational logs. Direct client IP is trusted; behind the proxy this conservatively limits the shared proxy IP. High-traffic institutional deployments should add per-client edge limits using a trusted proxy configuration.

## Confidentiality and input handling

Fernet authenticated encryption protects student contacts, account email, MFA secrets, compensation and import previews. Each ciphertext identifies its key version. Account email uniqueness/recovery uses a separate keyed HMAC index. Username and Placement ID remain searchable identifiers; do not use a confidential email address as a username.

Set `DATA_KEYS` to a comma-separated key ring, with the newest version first. Keep old keys while older records, sessions and backups require them. `LOOKUP_KEY` must remain stable unless email indexes are deliberately migrated. `AUDIT_KEY` must remain stable for existing history; changing it without a planned audit migration breaks verification. `BACKUP_KEY` is independent from application encryption keys.

Production requires HTTPS and PostgreSQL TLS with certificate/hostname verification. Encrypted disks, swap, snapshots and protected secret storage remain infrastructure responsibilities. CSV/XLSX exports are plaintext authorized downloads over HTTPS; recipients must store them according to university data-handling rules. Export access, fields, filters and row count are audited.

The ORM supplies parameterized queries. Templates escape student/recruiter content. CSP restricts scripts and resources to the application, prevents framing, and disallows plugins. Inputs have bounded formats and values. Imports have a 2 MB compressed size limit, a 10 MB XLSX expanded-size limit, one sheet, no formula cells, at most 500 records, exact column order and full revalidation at commit. Spreadsheet export cells with formula prefixes or leading control characters are neutralized.

## Audit integrity

Sensitive writes and their audit events commit in one transaction. Events include actor references, UTC timestamps, action, target, policy or status snapshots, reasons and relevant changed-field names. Raw passwords, MFA codes, tokens and confidential compensation/contact values are excluded from ordinary logs and audit snapshots.

Events have chained HMAC signatures. The production runtime role can insert/read events but cannot update, delete or truncate them; the migration owner remains separate. External checkpoints pin a previously observed event ID/digest. Protect these checkpoint files independently with write-once or separately administered storage; local files alone do not provide independent rollback protection.

An administrator with database-owner privileges or access to application signing keys can defeat some protections. A compromised application can append misleading events and read data it can decrypt. External immutable checkpoints, host controls, least-privilege secret access and independent monitoring are necessary for institutional operation.

## Provisional placement rules

| Category | Annual FTE CTC | Switching |
| --- | --- | --- |
| C | Below ₹6 LPA | Higher category required |
| B | ₹6 to below ₹10 LPA | New CTC at least 1.5 times existing CTC |
| A | ₹10 to below ₹16 LPA | A+ only |
| A+ | ₹16 LPA or more | Further participation ends |

Category and offer-type restrictions both apply. A previous I selection blocks another I opportunity; a previous F selection blocks another F opportunity. An IF selection blocks opportunities at another organization. Annual salary category rules are applied when both selections include FTE compensation; internship stipends receive no inferred category.

Verified selections impose restrictions immediately, including pending, declined and expired offers. Only an authorized withdrawal removes that selection from subsequent policy evaluation. All non-withdrawn selections are evaluated, not just the most recent or accepted offer. Missing eligibility, academic evidence or applicable compensation requires manual review; review does not automatically permit participation.

Policy versions configure category boundaries and the B multiplier. Offer-type rules and precedence are explicit code covered by tests; changing them requires reviewed code changes. An administrator can grant a reasoned, expiring exception for one student and one drive. Exceptions cannot bypass an archived record, a closed application period or missing policy configuration. Off-campus reports cannot use a campus-drive exception.

Absence produces a review case. An administrator can impose a sanction only when three future eligible drives are scheduled; those drive IDs are recorded explicitly. Emergency exceptions can approve a review without sanction or permit a specific affected drive. Final disciplinary decisions remain with the university authority.

The official NFSU guidelines must settle these provisional interpretations, including overlapping salary bands, switching precedence, whether decline/expiry ends restrictions, same-organization IF opportunities, off-campus handling and sanction ordering.
