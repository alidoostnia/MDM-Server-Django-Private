# Django Admin Security Implementation

## Purpose and scope

This document maps the requested Django admin security requirements to the exact areas of the repository that were changed. The original request contains **16 numbered requirements** (despite later referring to 15 items), so all 16 are documented below.

The implementation is centered around a new Django application named `security_controls`, displayed as **Settings** in Django admin. Supporting changes are limited to authentication/session handling, the custom `Account` admin, file-upload validation, admin templates, configuration, migrations, and focused tests.

## Admin menus and access control

Three models are exposed through the `security_controls` application:

| Admin entry | Purpose | Access |
| --- | --- | --- |
| **Security policy** | Global password expiration, session timeout, failed-login threshold, lockout duration, and password-history depth | Active superusers only |
| **Active sessions** | Lists unexpired Django sessions and permits terminating them | Active superusers only |
| **Users' Activities** | Read-only authentication, password, session, and admin activity audit log | Active superusers only |

The menu registration, labels, ordering, and icons are configured in `config/base.py`. The admin implementations and superuser permission checks are in `security_controls/admin.py`.

## Requirement-by-requirement impact

### 1. View and remove every active session

Implemented by the `ActiveSession` proxy model and `ActiveSessionAdmin`:

- `security_controls/models.py`: `ActiveSession` proxies Django's `django.contrib.sessions.models.Session`; no second session table is created.
- `security_controls/admin.py`: the queryset includes every unexpired Django session, not only the current administrator's session.
- The list displays the session key, resolved username, login time, IP address, browser/user agent, and expiration time.
- The **Terminate selected sessions and sign out users** action deletes selected session records and clears the matching user's `active_session_key`.
- Normal single-object and bulk delete operations use the same termination logic.
- Terminating the administrator's current session also logs that administrator out.
- Every termination is recorded as `session_terminated` in Users' Activities.

This feature manages **Django database-backed sessions**. JWT access/refresh tokens used by the device API are not represented by Django's session table.

### 2. Disable autocomplete for usernames and passwords in admin

Implemented at the form, login-page, and admin-template levels:

- `devices/forms.py`: all custom username/password fields receive `autocomplete="off"`.
- `config/middleware.py`: the admin login page's username, password, CAPTCHA, and form elements receive `autocomplete="off"`.
- `templates/admin/base_site.html`: a Django admin-wide script applies the attribute to forms and inputs whose names contain `username` or `password`.
- `templates/admin/force_password_change.html`: the forced-change form itself has `autocomplete="off"`.

Browsers and password managers can choose to disregard this HTML hint; the application nevertheless emits the requested setting throughout Django admin.

### 3. Password complexity

Implemented with Django's password validation framework:

- `config/base.py`: `MinimumLengthValidator` is explicitly configured for at least 8 characters, and `devices.validators.ComplexityPasswordValidator` is registered.
- `devices/validators.py`: requires at least one ASCII letter, one digit, and one non-alphanumeric/special character.
- `devices/forms.py`: account creation, administrator-set passwords, and forced password changes all call Django's `validate_password()`.

The existing similarity, common-password, and numeric-password validators remain active in addition to the new complexity rules.

### 4. Successful-login security notice

Implemented in `devices/forms.py` by `AdminCaptchaAuthenticationForm`:

- After successful Django admin authentication, a success message displays the username, source IP, previous login time, and role/group information.
- The notice reminds the user that they are responsible for protecting sensitive information, limiting its use to authorized duties, and signing out after use.
- The successful login is also written to Users' Activities.

### 5. Only one active session per user

Implemented by `AdminSecurityMiddleware` in `config/middleware.py` and enabled in `config/base.py`:

- `devices/models.py` adds `Account.active_session_key`, which owns the single permitted Django session key.
- Before authentication, the admin form rejects a login when the account already points to an unexpired session.
- After authentication, the middleware claims the session slot inside a database transaction with `select_for_update()`. This closes the race where two logins pass the initial form check at nearly the same time.
- A second parallel session is logged out and redirected to admin login.
- Stale/expired referenced sessions are cleared during authentication.
- Normal logout and administrative session termination clear the account's session key.

The middleware control applies to cookie-based Django sessions. The device API's JWT tokens are a separate authentication mechanism.

### 6. Verify uploaded file content, not only its extension

Implemented in `storage/validators.py` and connected to both upload flows:

- `storage/validators.py` defines the allowed extensions and their acceptable detected MIME families.
- Content is inspected using known file signatures/magic bytes for PDF, common images, ZIP-based formats, gzip, 7z, RAR, MP3, WAV, and MP4. Text, JSON, and XML receive content-aware inspection.
- The detected content must match both the filename extension and, when supplied, the declared MIME type.
- Unknown extensions are rejected because their contents cannot be reliably verified.
- `storage/forms.py` applies inspection to direct uploads through Django admin and rewinds the uploaded stream after reading it.
- `storage/views.py` checks the extension before creating a presigned upload. At upload completion, it retrieves up to the first 65,536 bytes from object storage, verifies the content, and rejects and removes mismatching objects and database records.
- `storage/admin.py` passes the verified content type to the asynchronous MinIO upload task.
- `storage/signals.py` avoids issuing a redundant storage deletion after an already-rejected object has been removed.

This is signature/content-family verification, not antivirus or malware scanning. ZIP-based formats (`docx`, `xlsx`, `pptx`, and `apk`) are verified as ZIP containers; their internal package schemas are not deeply validated.

### 7. Temporary lockout after unsuccessful login

Implemented with `LoginThrottle` and applied to admin and API login:

- `security_controls/models.py`: stores a case-insensitive username's failure count and `locked_until` time.
- The default lockout duration is 5 minutes.
- `devices/forms.py`: checks and increments the counter for invalid admin credentials. A valid CAPTCHA is handled separately and does not conceal credential lockout behavior.
- `devices/views.py`: applies the same policy to API password login and returns HTTP 429 while locked.
- A successful login resets the counter.
- Failures, lock activation, and attempts made during lockout are audited.

### 8. Password expiration and mandatory change before admin access

Implemented across the account model, middleware, form, view, and template:

- `devices/models.py`: adds `password_changed_at`, `must_change_password`, and optional per-user `password_expiration_days`.
- `Account.password_is_expired()` uses the per-user value when present and otherwise uses the global Security policy value.
- `config/middleware.py`: an authenticated user with an expired password (or `must_change_password=True`) is redirected away from all other admin pages.
- Only the forced password-change page and logout remain available until the password is changed.
- `security_controls/admin.py`: provides the protected forced-change view.
- `devices/forms.py`: requires the current password, confirmation, complexity validation, and password-history validation.
- `templates/admin/force_password_change.html`: renders the dedicated admin page.

### 9. Admin policy for expiration and forced periodic changes

Implemented in two places:

- **Settings > Security policy** contains the global password expiration period.
- **Accounts > Security policy** contains an optional expiration override for each user.
- The Account admin action **Force selected users to change password at next login** sets `must_change_password=True` for selected users.
- Each force action is audited as `force_password_change`.

### 10. Administrator-configurable session timeout

Implemented through:

- `SecurityPolicy.session_timeout_minutes` for the global default.
- `Account.session_timeout_minutes` for an optional per-user override.
- `AdminSecurityMiddleware`, which calls `request.session.set_expiry()` using the per-user override or the global value.

The configured value is in minutes and must be at least 1. It controls Django session age as refreshed by authenticated requests.

### 11. Force change when an administrator sets a password

Implemented in `devices/admin.py` and `devices/forms.py`:

- Newly created accounts are marked `must_change_password=True`.
- When an administrator changes another user's password, that user is marked for change at next login.
- If an administrator changes their own password through the Account admin form, the flag is not added solely because of that action.
- The operation is logged as `password_admin_set`, including whether it was a new account and whether change was forced.

### 12. Configurable unsuccessful-login threshold

Implemented as `SecurityPolicy.max_failed_login_attempts`:

- Editable by a superuser in **Settings > Security policy**.
- Defaults to 5 attempts and must be at least 1.
- Used by both Django admin login and API password login.

The lockout duration is also editable as `SecurityPolicy.lockout_minutes` and defaults to the requested 5 minutes.

### 13. Prevent reuse of previous passwords and store history securely

Implemented by `PasswordHistory` and services in `security_controls/services.py`:

- Previous passwords are stored only as Django-encoded password hashes, never as plaintext.
- Validation uses Django's `check_password()` against retained hashes.
- The user's current password is also rejected explicitly.
- A previous hash is retained whenever the password is changed through the implemented admin or forced-change paths.

Password-history enforcement covers the custom Django admin account-change and mandatory-change workflows. Any future password-changing endpoint must call `validate_password_history()` and `set_user_password()` (or retain the replaced hash) to participate in this policy.

### 14. Configurable password-history depth

Implemented as `SecurityPolicy.password_history_count`:

- Editable in **Settings > Security policy**.
- Defaults to 5 and must be at least 1.
- Validation reads the latest configured number of hashes.
- After a successful change, older records beyond the configured retention depth are deleted.

### 15. Users' Activities menu for login and password events

Implemented by `UserActivity` and its read-only admin:

- Menu name: **Users' Activities**.
- Events include successful login, failed login, blocked login, logout, password changed, password set by an administrator, forced password change, session termination, and general admin activity.
- Records can include actor, target user, attempted username, success status, IP, user agent, request path, structured details, and timestamp.
- The admin list supports event/status/date filters, search, and date navigation.
- Entries cannot be created, changed, or deleted through Django admin.

### 16. Record administrator-level activities

Implemented in `AdminSecurityMiddleware`:

- Authenticated requests under the Django admin URL are recorded as `admin_activity`.
- The audit details include HTTP method, response status, and resolved Django view name.
- Login, logout, forced password changes, and session termination have dedicated event types rather than being represented only as generic activity.
- The login, logout, and forced-change endpoints are excluded from duplicate generic entries.

The audit captures request-level admin activity. It does not currently calculate model-field before/after diffs; Django's built-in `LogEntry` can continue to provide model change descriptions alongside this security audit.

## Database changes

### `devices/migrations/0008_account_security_fields.py`

Adds these columns to the existing custom `Account` table:

- `active_session_key`
- `must_change_password`
- `password_changed_at`
- `password_expiration_days`
- `session_timeout_minutes`

### `security_controls/migrations/0001_initial.py`

Creates:

- `SecurityPolicy`
- `LoginThrottle`
- `PasswordHistory`
- `UserActivity`
- migration state for the `ActiveSession` proxy model

The global policy is a singleton with primary key `1`. It is created automatically with defaults on first use if it does not already exist.

## Files affected

| File | Effect |
| --- | --- |
| `config/base.py` | Registers the app and middleware, configures password validators, and adds admin menu entries/icons/order |
| `config/middleware.py` | Enforces one session, session timeout, expired-password redirect, login-page autocomplete, and admin audit logging |
| `devices/models.py` | Adds account security state and password-expiration calculation |
| `devices/forms.py` | Secures admin authentication and all supported password-setting workflows |
| `devices/validators.py` | Adds the password-complexity validator |
| `devices/admin.py` | Adds account security fields, secure password handling, force-change action, and audit events |
| `devices/views.py` | Adds throttling and login auditing to API password authentication |
| `devices/migrations/0008_account_security_fields.py` | Migrates the Account database schema |
| `security_controls/models.py` | Defines policies, history, throttling, activity records, and active-session proxy |
| `security_controls/services.py` | Implements password-history validation, retention, and secure password update |
| `security_controls/admin.py` | Creates Settings, Active sessions, Users' Activities, and forced-change admin UI |
| `security_controls/apps.py` | Configures the app label shown as Settings |
| `security_controls/migrations/0001_initial.py` | Creates the security-control database schema |
| `templates/admin/base_site.html` | Disables autocomplete across username/password admin controls |
| `templates/admin/force_password_change.html` | Provides the mandatory password-change page |
| `storage/validators.py` | Implements extension, signature, content, and MIME matching |
| `storage/forms.py` | Applies content verification to Django admin uploads |
| `storage/views.py` | Applies verification to presigned/object-storage uploads |
| `storage/admin.py` | Sends the verified MIME type to the upload task |
| `storage/signals.py` | Prevents duplicate deletion during rejected-upload cleanup |

## Test coverage

Focused tests were added or extended in:

- `security_controls/tests.py`: complexity, password history, expiration override, password preservation, forced change, five-minute lockout, parallel-session rejection, expiration redirect, timeout, active-session visibility, and admin activity.
- `storage/test_validators.py`: accepted PDF signature, renamed-content rejection, and unsupported-extension rejection.
- `storage/tests.py`: completion-time object inspection and cleanup behavior.
- `devices/test_forms.py`: username/password autocomplete attributes.

The affected focused suite previously completed with **38 passing tests**. Django's system check reported only the repository's pre-existing `policies.Policy.actions` warning, and migration drift checking reported no pending model changes. These results describe the code-level verification; the migrations must also be applied to the target PostgreSQL database before the new admin features are available.

## Deployment and verification

For the local Docker stack, use the repository's local compose file and environment file:

```bash
docker compose --env-file .env.local -f docker-compose.local.yml up -d --build
docker compose --env-file .env.local -f docker-compose.local.yml exec django python manage.py migrate
docker compose --env-file .env.local -f docker-compose.local.yml exec django python manage.py check
docker compose --env-file .env.local -f docker-compose.local.yml exec django python manage.py showmigrations devices security_controls
```

Expected applied migrations include:

- `devices.0008_account_security_fields`
- `security_controls.0001_initial`

Useful runtime checks:

1. Sign in as a superuser and confirm **Settings**, **Active sessions**, and **Users' Activities** appear.
2. Open Security policy, save the desired values, and confirm there is only one policy record.
3. Sign in from one browser, then attempt the same account from a private window or another browser; the second login must be rejected.
4. Terminate the first session through Active sessions and confirm that login becomes possible again.
5. Set another user's password and confirm their next admin request is redirected to the password-change page.
6. Upload a valid supported file, then try a renamed file whose bytes do not match its extension; the second upload must be rejected.
7. Confirm the corresponding events appear read-only in Users' Activities.

