# Single sign-on (OpenID Connect)

The planner supports SSO with any **OpenID Connect** identity provider, using the Authorization Code flow with PKCE.
Built-in presets cover **Microsoft Entra ID (Azure AD)**, **Okta**, **Google Workspace** and **Keycloak**.

All configuration is done in the app under **Admin → Single Sign-On**. No configuration files or restarts are
needed. The only server-side settings are two environment variables:

| Variable | Purpose |
|---|---|
| `ORP_ENCRYPTION_KEY` | Encrypts client secrets stored in the database. Set it once to a random value and keep it stable. |
| `ORP_FORCE_LOCAL_LOGIN` | Break-glass. `true` re-enables password sign-in for everyone (see [Lockout recovery](#lockout-recovery)). |

SAML is not supported. Every major enterprise IdP, including Entra ID, Okta, ADFS 2016+, Ping and Google, also
offers OpenID Connect.

---

## 1. Quick start

1. Sign in as an administrator with your local password.
2. Go to **Admin → Single Sign-On** and set the **Public application URL** to the HTTPS address users reach
   (for example `https://offsec-planner.example.com`). Save the policy.
3. Click **Add identity provider** and choose your provider. The form is pre-filled with the right claim
   settings and shows set-up help for that IdP.
4. Copy the **Redirect URI** shown at the top of the form and register it in your IdP. It looks like:
   `https://offsec-planner.example.com/api/auth/sso/<identifier>/callback`
5. Enter the **Issuer URL**, **Client ID** and **Client secret** from your IdP, plus the group mappings (below).
   Click **Save & test**.
6. Check that every connection test passes, then click **Enable provider**. The login page now shows the
   provider's button.
7. Sign in via SSO in a private browser window, as a member of your admin group and as a normal user.
8. Optionally, tighten the **Password sign-in** policy (see section 4).

New providers are saved **disabled**, so a half-finished configuration is never shown to users.

---

## 2. Provider set-up guides

### Microsoft Entra ID (Azure AD)

1. **Entra admin center → App registrations → New registration**
   - Name: `OffSec Resource Planner`
   - Supported account types: *Accounts in this organizational directory only*
   - Redirect URI: platform **Web**, value = the Redirect URI from the planner
2. Under **Overview**, copy the **Application (client) ID** and the **Directory (tenant) ID**.
3. **Certificates & secrets → New client secret**: copy the secret **Value** (not the ID). Note when it expires.
4. **Token configuration → Add groups claim**: choose *Security groups* and tick *ID token*.
   - Alternatively, define **App roles** (e.g. `OffSec.Admin`, `OffSec.Requester`) under *App roles*, assign them
     to groups in *Enterprise applications → Users and groups*, and set the planner's groups claim to `roles`.
5. In the planner (preset *Microsoft Entra ID*):
   - **Issuer URL:** `https://login.microsoftonline.com/<tenant-id>/v2.0` (use your tenant ID, not `common`)
   - **Client ID / secret:** from steps 2–3
   - **Email claim:** `email,preferred_username,upn` (the preset default)
   - **Admin groups:** the **Object ID** of your OffSec admin security group (or the app-role value)
   - **Allowed requester groups:** optional. Object IDs of the groups allowed to request bookings
   - **Allowed email domains:** optional, e.g. your corporate domain
   - Optionally add `domain_hint=<your-domain>` under *Advanced → Extra authorization parameters*
6. Optional: under *Enterprise applications → Properties*, set **Assignment required = Yes** so only assigned
   users and groups can sign in at all.

> **Group overage:** if a user belongs to more than 200 groups, Entra leaves the groups claim out of the token.
> Use **App roles** (step 4) in that case, or "Groups assigned to the application" in the groups claim options.

### Okta

1. **Applications → Create App Integration → OIDC – OpenID Connect → Web Application.**
2. Sign-in redirect URI = the planner's Redirect URI. Sign-out redirect URI = the planner's base URL.
3. **Assignments:** assign the groups that may use the planner.
4. **Security → API → Authorization Servers → default → Claims → Add claim** `groups`, included in the ID token,
   value type *Groups*, filter *Matches regex* `.*` (or a narrower filter).
5. Planner preset *Okta*: Issuer `https://<your-org>.okta.com/oauth2/default`, client ID and secret, and admin
   groups = Okta group names.

### Google Workspace

1. **Google Cloud console → APIs & Services → OAuth consent screen**: *Internal*.
2. **Credentials → Create credentials → OAuth client ID → Web application**, authorized redirect URI = the
   planner's Redirect URI.
3. Planner preset *Google Workspace*: Issuer `https://accounts.google.com`. Replace `hd=<your-domain.com>` under
   *Extra authorization parameters* with your domain **and** add the same domain to **Allowed email domains**.
   The `hd` parameter alone isn't a security control; the allowed-domain check is.
4. Google sends no group claims. Leave **Admin groups** empty, turn **off** *Update the role from IdP groups*, and
   promote administrators under **Admin → Users**.

### Keycloak

1. **Clients → Create client:** OpenID Connect, *Client authentication* ON, *Standard flow* ON.
2. **Valid redirect URIs** = the planner's Redirect URI.
3. Copy the secret from **Credentials**.
4. Planner preset *Keycloak*: Issuer `https://<host>/realms/<realm>`, groups claim `realm_access.roles` for realm
   roles. For groups, add a *Group Membership* mapper (token claim name `groups`, full path off) and use `groups`.

### Other OIDC providers

Use *Generic OpenID Connect*. Endpoints are discovered from `<issuer>/.well-known/openid-configuration`. If your
provider has no discovery document, fill in the endpoint overrides under *Advanced settings*.

---

## 3. Role mapping and provisioning

| Setting | Behaviour |
|---|---|
| **Groups / roles claim** | Name of the ID-token claim holding group or role values. Dotted paths address nested claims (`realm_access.roles`). Lists and space/comma-separated strings are both accepted. |
| **Admin groups** | A user with **any** of these values becomes an **Admin**. Matching is case-insensitive. |
| **Allowed requester groups** | If set, a user must be in one of these groups (or an admin group) to sign in at all. If empty, anyone the IdP authenticates may sign in as a requester. |
| **Allowed email domains** | If set, the user's email domain must match exactly. |
| **Role when no admin group matches** | Normally *Requester*. *Admin* is only allowed together with a group or domain restriction. |
| **Create accounts automatically** | On: first SSO sign-in creates the account. Off: an admin must first create the user under **Admin → Users** (tick *SSO only*, no password needed). |
| **Update the role at every sign-in** | On: the role follows IdP groups at each sign-in, and existing sessions are revoked when the role changes. Off: the role is set at first sign-in and then managed in the app. The **last active admin is never demoted** by a sync, so a mapping mistake can't remove all admins. |
| **Link existing accounts by email** | Lets existing local users (for example the initial admin) start using SSO. An account already linked to an SSO identity is **never** re-linked to a different one; that attempt fails with *identity conflict*, preventing account takeover. |
| **Sign out of the identity provider on logout** | After the planner logout, the browser is sent to the IdP's `end_session_endpoint` (single logout). |

Accounts are identified by the provider plus the token's `sub` claim, not by email. A user whose email changes in
the IdP keeps the same planner account.

---

## 4. Sign-in policy

Set under **Admin → Single Sign-On → Sign-in policy**.

| Password sign-in | Effect | Safeguard |
|---|---|---|
| **All users** (default) | Password and SSO both work | — |
| **Administrators only** (recommended once SSO works) | Requesters must use SSO. Local admin passwords remain as break-glass access via *Administrator password sign-in* on the login page. | Requires at least one enabled provider. The last enabled provider can't be disabled or deleted while this is set. |
| **Disabled – SSO only** | Nobody can sign in with a password | Can only be selected by an admin who is currently signed in **via SSO**, which proves admins can get in through SSO |

**Skip the sign-in page** sends users straight to the IdP when SSO is the only method and exactly one provider is
enabled. `/login?local=1` always shows the page.

SSO-only accounts (no password) can never sign in with a password, whatever the policy.

---

## 5. Lockout recovery

If SSO stops working (expired client secret, IdP outage, misconfiguration) and password sign-in is disabled:

1. Set `ORP_FORCE_LOCAL_LOGIN=true` in `.env` and restart the backend (`docker compose up -d backend`).
2. Open `/login?local=1` and sign in with a **local admin password**.
3. Fix the provider under **Admin → Single Sign-On** (for example, paste a new client secret) and use **Test**.
4. Remove `ORP_FORCE_LOCAL_LOGIN` and restart again.

The SSO screen shows a warning while the override is active. Keep at least one local admin account with a strong
password for this purpose.

---

## 6. Security design

- **Flow:** Authorization Code with PKCE (S256), `state` (CSRF) and `nonce` (replay). These, and the PKCE verifier,
  live in an **encrypted**, HttpOnly, 10-minute transaction cookie, so a callback only succeeds in the browser that
  started the login.
- **ID token validation:** the signature is verified against the provider's JWKS, refreshed automatically when keys
  rotate. Only asymmetric algorithms are accepted (RS/PS/ES 256–512); `none` and `HS*` are rejected. `iss`,
  `aud`, `exp`, `iat` (with configurable clock skew), `nonce`, and `azp` for multi-audience tokens are checked. An
  email the IdP flags as unverified (`email_verified=false`) is rejected.
- **Userinfo** (optional) is only merged when its `sub` matches the ID token.
- **Transport:** all IdP endpoints must be HTTPS (plain HTTP only for `localhost` outside production).
- **Secrets:** client secrets are encrypted at rest (Fernet / AES + HMAC, key from `ORP_ENCRYPTION_KEY`). The API
  is write-only for them: responses expose only `has_client_secret`. They are never written to the audit log.
- **No open redirects:** the post-login target must be a same-origin relative path.
- **Sessions:** SSO sign-in issues the same signed HttpOnly session cookie and CSRF token as password sign-in, so
  RBAC, CSRF and auditing are identical for both.
- **Audit:** provider create/update/enable/disable/delete/test, policy changes, every SSO sign-in (provider,
  subject, matched groups, role) and every failure (with a reason code, never tokens) are recorded in the
  immutable audit log.
- **Rate limiting:** login and callback endpoints are rate limited per IP.

### Error codes shown on the login page

`provider_unavailable`, `session_expired`, `state_mismatch`, `idp_error`, `token_exchange_failed`, `invalid_token`,
`email_missing`, `domain_not_allowed`, `group_not_allowed`, `not_provisioned`, `account_disabled`,
`identity_conflict`, `rate_limited`. The detailed cause of each failure is in **Admin → Audit Log** (action
`auth.sso_login_failed`).

### Troubleshooting

| Symptom | Likely cause |
|---|---|
| `token_exchange_failed` | Wrong or expired client secret, a redirect URI that doesn't match exactly, or the wrong client authentication method (try `client_secret_basic` vs `client_secret_post`) |
| `invalid_token` – issuer | Entra: the issuer must use your tenant ID with `/v2.0`, not `common` |
| `invalid_token` – audience | The Client ID doesn't match the app the token was issued for |
| `email_missing` | Add `email` to the scopes / token configuration, or adjust the email claim (Entra: `preferred_username`) |
| Everyone signs in as requester | The groups claim isn't in the ID token (check the token configuration), or admin groups use names where the IdP sends IDs (Entra sends Object IDs) |
| `identity_conflict` | That email is already linked to another SSO identity. Unlink it under **Admin → Users → Edit** if intended |
