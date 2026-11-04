"""OpenID Connect single sign-on: identity providers and user identity links.

* sso_providers holds every IdP setting an admin configures in the UI. The
  client secret is stored ENCRYPTED (Fernet), never in plain text.
* users.password_hash becomes nullable so SSO-only accounts have no password.
* (sso_provider_id, sso_subject) uniquely identifies an external identity.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
CREATE TABLE sso_providers (
    id                        UUID PRIMARY KEY,
    slug                      TEXT NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{0,39}$'),
    display_name              TEXT NOT NULL,
    provider_type             TEXT NOT NULL DEFAULT 'generic'
                                CHECK (provider_type IN ('entra','okta','google','keycloak','generic')),
    enabled                   BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order                INTEGER NOT NULL DEFAULT 0,

    issuer                    TEXT NOT NULL,
    discovery_url             TEXT,
    authorization_endpoint    TEXT,
    token_endpoint            TEXT,
    jwks_uri                  TEXT,
    userinfo_endpoint         TEXT,
    end_session_endpoint      TEXT,

    client_id                 TEXT NOT NULL,
    client_secret_encrypted   TEXT,
    token_auth_method         TEXT NOT NULL DEFAULT 'client_secret_post'
                                CHECK (token_auth_method IN ('client_secret_post','client_secret_basic','none')),
    scopes                    TEXT NOT NULL DEFAULT 'openid email profile',
    extra_auth_params         JSONB NOT NULL DEFAULT '{}'::jsonb,
    use_pkce                  BOOLEAN NOT NULL DEFAULT TRUE,
    fetch_userinfo            BOOLEAN NOT NULL DEFAULT FALSE,
    rp_initiated_logout       BOOLEAN NOT NULL DEFAULT FALSE,

    email_claim               TEXT NOT NULL DEFAULT 'email',
    name_claim                TEXT NOT NULL DEFAULT 'name',
    groups_claim              TEXT NOT NULL DEFAULT 'groups',
    admin_groups              JSONB NOT NULL DEFAULT '[]'::jsonb,
    requester_groups          JSONB NOT NULL DEFAULT '[]'::jsonb,
    allowed_email_domains     JSONB NOT NULL DEFAULT '[]'::jsonb,

    auto_provision            BOOLEAN NOT NULL DEFAULT TRUE,
    default_role              TEXT NOT NULL DEFAULT 'requester' CHECK (default_role IN ('requester','admin')),
    sync_role_on_login        BOOLEAN NOT NULL DEFAULT TRUE,
    link_existing_by_email    BOOLEAN NOT NULL DEFAULT TRUE,
    clock_skew_seconds        INTEGER NOT NULL DEFAULT 120 CHECK (clock_skew_seconds BETWEEN 0 AND 600),

    last_tested_at            TIMESTAMPTZ,
    last_test_ok              BOOLEAN,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL;
ALTER TABLE users ADD COLUMN sso_provider_id UUID REFERENCES sso_providers(id) ON DELETE SET NULL;
ALTER TABLE users ADD COLUMN sso_subject TEXT;
ALTER TABLE users ADD COLUMN last_login_method TEXT;
CREATE UNIQUE INDEX uq_users_sso_identity ON users (sso_provider_id, sso_subject)
    WHERE sso_provider_id IS NOT NULL AND sso_subject IS NOT NULL;
"""

DOWNGRADE_SQL = r"""
DROP INDEX IF EXISTS uq_users_sso_identity;
ALTER TABLE users DROP COLUMN IF EXISTS last_login_method;
ALTER TABLE users DROP COLUMN IF EXISTS sso_subject;
ALTER TABLE users DROP COLUMN IF EXISTS sso_provider_id;
UPDATE users SET password_hash = '!' WHERE password_hash IS NULL;
ALTER TABLE users ALTER COLUMN password_hash SET NOT NULL;
DROP TABLE IF EXISTS sso_providers;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
