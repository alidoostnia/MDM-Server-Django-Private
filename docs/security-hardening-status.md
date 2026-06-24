# Security Hardening Implementation Status

**Project:** MDM Server (Django)  
**Review date:** 2026-06-22  
**Scope:** Django Admin authentication, session handling, cookies, and HTTP response headers

## 1. Executive summary

This document records the security requirements reviewed during the current
hardening work, the changes implemented in the repository, the items that were
intentionally not implemented, and the limitations of the supplied checklist.

The following controls are now present in the code:

- `autocomplete="off"` on the Django Admin username and password fields.
- A 15-minute sliding idle timeout for Django session-based authentication.
- Secure production defaults for HTTPS redirection, HSTS, session cookies, and
  CSRF cookies.
- A project middleware that adds CSP, referrer, MIME-sniffing, framing, legacy
  XSS, and cache-related response headers.
- Regression tests for the login field attributes and security header
  middleware.

Forced password replacement after an administrator assigns a password has not
been implemented. The design was discussed, but no account field, redirect,
API, migration, or access restriction was added.

## 2. Status matrix

| Requirement | Status | Implementation or reason |
|---|---|---|
| Disable autocomplete on Admin login username and password | Implemented | The widgets in `AdminCaptchaAuthenticationForm` set `autocomplete` to `off`. |
| Re-authenticate after inactivity | Implemented for Django sessions | Session expiry is sliding and defaults to 900 seconds. It applies to Django Admin/session authentication, not JWT clients. |
| Force a user to replace an administrator-assigned password on first login | Not implemented | Django Admin has a password-change page, but Django does not track whether a password was assigned by an administrator. A model flag and enforcement flow are still required. |
| `Access-Control-Allow-Origin` | Intentionally absent | No browser cross-origin use case is defined. Omitting the header prevents browser-based cross-origin access by default. An exact trusted origin should be configured only when such a client is introduced. |
| `Content-Security-Policy` | Implemented, with limitations | A CSP matching the supplied checklist is emitted. It still allows inline code and contains a deprecated directive; see Section 6. |
| `Strict-Transport-Security` | Implemented in production | Defaults to 63,072,000 seconds with `includeSubDomains` and `preload` when `DEBUG=False`. It is disabled by default in debug mode. |
| `Referrer-Policy: no-referrer` | Implemented | Set both in Django settings and response middleware. |
| `X-Content-Type-Options: nosniff` | Implemented | Enabled through Django and explicitly emitted by the project middleware. |
| `X-Frame-Options` | Implemented | Set to `DENY`. CSP also uses `frame-ancestors 'none'`. |
| `X-XSS-Protection: 1; mode=block` | Implemented only for checklist compatibility | This header is obsolete in modern browsers. |
| Checklist `Cache-Control` value | Implemented, but not ideal | The exact legacy-style directives are emitted globally. They do not include `no-store`; see Section 6. |
| `Pragma: no-cache` | Implemented only for legacy compatibility | `Pragma` is an HTTP/1.0 mechanism. |
| `Expires: 0` | Implemented only for checklist compatibility | A valid date in the past is more standards-compliant. |

## 3. Implemented authentication controls

### 3.1 Login autocomplete attributes

`devices/forms.py` updates both inherited authentication widgets:

```python
self.fields["username"].widget.attrs["autocomplete"] = "off"
self.fields["password"].widget.attrs["autocomplete"] = "off"
```

This satisfies the HTML attribute requirement. Browsers and password managers
may deliberately ignore `autocomplete="off"` on credential fields, so this
attribute must not be treated as a credential-protection control by itself.

Coverage is provided by `devices/test_forms.py`.

### 3.2 Fifteen-minute session inactivity timeout

`config/base.py` contains:

```python
SESSION_COOKIE_AGE = env.int("SESSION_IDLE_TIMEOUT", default=15 * 60)
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
```

For an authenticated Django session, each request renews the expiry time. If no
request is made for 15 minutes, the next protected request requires
authentication again. The duration can be changed with
`SESSION_IDLE_TIMEOUT`, expressed in seconds.

This does **not** implement an inactivity timeout for JWT clients. The REST API
uses Simple JWT and has independent access and refresh token lifetimes. A true
JWT idle timeout would require server-side last-activity tracking or an
equivalent revocation policy.

## 4. Implemented cookie and transport controls

The following base settings are explicit:

- Session cookies are `HttpOnly` and `SameSite=Strict`.
- CSRF cookies are `HttpOnly` and `SameSite=Strict`.

`config/production.py` provides environment-aware production defaults:

- `DEBUG=False` unless explicitly overridden.
- `SESSION_COOKIE_SECURE=True` when debug mode is off.
- `CSRF_COOKIE_SECURE=True` when debug mode is off.
- `SECURE_SSL_REDIRECT=True` when debug mode is off.
- HSTS is enabled for 63,072,000 seconds when debug mode is off.
- HSTS includes subdomains and requests preload eligibility.

The settings remain configurable through environment variables to support an
HTTP-only local development environment. Production must not set
`DJANGO_DEBUG=True`, and Traefik must continue forwarding the original protocol
because Django relies on `SECURE_PROXY_SSL_HEADER`.

HSTS preload is a long-lived operational commitment. Before submitting a
domain to a browser preload list, all affected HTTPS hosts must be confirmed to
support HTTPS permanently.

## 5. Implemented HTTP response headers

`config.middleware.SecurityHeadersMiddleware` currently emits these headers on
responses passing through Django:

```text
Content-Security-Policy: default-src 'self' 'unsafe-inline'; frame-ancestors 'none'; frame-src 'self'; form-action 'self'; upgrade-insecure-requests; block-all-mixed-content
Referrer-Policy: no-referrer
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Cache-Control: must-revalidate, pre-check=0, post-check=0, max-age=0, s-maxage=0
Pragma: no-cache
Expires: 0
```

These headers apply only to responses processed by this Django middleware.
Responses generated directly by Traefik, an object store, a CDN, or another
service require separate configuration at that service.

No `Access-Control-Allow-Origin` header is emitted. This is intentional because
the repository does not define a trusted browser origin requiring CORS.

## 6. Deprecated, redundant, or weak checklist items

### 6.1 `X-XSS-Protection`

This browser XSS filter header is obsolete and ignored by modern browsers. CSP
is the replacement. It remains in the implementation solely to satisfy the
provided checklist and support legacy clients.

### 6.2 CSP `unsafe-inline`

Allowing `'unsafe-inline'` weakens CSP protection against injected scripts and
styles. It is currently necessary for compatibility with the existing Admin,
Jazzmin, Swagger, and dynamically injected CAPTCHA markup. A stronger future
implementation should remove it and use per-response nonces or hashes.

### 6.3 CSP `block-all-mixed-content`

`block-all-mixed-content` is deprecated and is redundant when
`upgrade-insecure-requests` is present. It remains only because it was included
in the supplied checklist.

### 6.4 Duplicate frame protection

`frame-ancestors 'none'` is the modern framing control. `X-Frame-Options: DENY`
is redundant for modern browsers but remains useful for older clients.

### 6.5 Cache directives

`pre-check` and `post-check` are obsolete Internet Explorer extensions.
`Pragma` is retained for HTTP/1.0 compatibility. `Expires: 0` is commonly
understood but is not a valid HTTP date.

More importantly, the current checklist value omits `no-store`, so it is not
the clearest policy for highly sensitive responses. A modern value would be:

```text
Cache-Control: no-store, no-cache, private, max-age=0, must-revalidate
```

The current middleware also applies the cache policy globally. A future change
should apply strict no-store behavior to authentication, Admin, and sensitive
API responses while allowing safe static/public assets to be cached.

## 7. Not implemented: mandatory first-login password change

Django Admin provides a standard password-change form, but it does not natively
record whether the current password was assigned by an administrator.
Therefore, reusing the page alone cannot enforce this requirement.

The proposed implementation remains pending:

1. Add a `must_change_password` field to `Account` with a safe migration policy
   for existing accounts.
2. Set the flag when an administrator creates an account or resets its
   password.
3. Allow login but redirect Admin users to Django's standard password-change
   page.
4. Block access to other protected Admin pages while the flag is set.
5. Clear the flag only after a successful user-initiated password change.
6. Add a separate authenticated password-change flow for JWT/API users and
   prevent normal API access until the change is completed.
7. Add tests for account creation, administrator reset, enforced restriction,
   password validation, and restriction removal.

This work was not started because the user requested an architectural review
before implementation, and the implementation was not subsequently approved.

## 8. Verification status

The modified Python modules pass Python syntax compilation and Git whitespace
validation. Automated Django tests could not be executed in the current host
environment because the Django package is not installed there.

The repository includes these relevant regression tests:

- `devices/test_forms.py`: verifies `autocomplete="off"` on both login fields.
- `config/test_middleware.py`: verifies the security and cache header values.

Before release, run the full test suite inside the project container or a
virtual environment containing `requirements.txt`, then inspect actual HTTPS
responses through Traefik. Runtime verification is necessary because a reverse
proxy can add, replace, or remove response headers.

Suggested checks include:

```bash
python manage.py test --settings=config.test
python manage.py check --deploy --settings=config.production
curl -I https://web.example.com/admin/login/
```

The deployment check must use the real production environment variables and a
real deployment hostname.
