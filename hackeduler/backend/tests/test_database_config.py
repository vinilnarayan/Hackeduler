"""Database connection settings for RDS: URL built from parts, TLS options, special characters in the password."""
from sqlalchemy.engine import make_url

from app.config import Settings


def _s(**kw):
    return Settings(_env_file=None, **kw)


def test_full_url_is_used_when_no_host_is_given():
    s = _s(database_url="postgresql+psycopg://u:p@localhost:5432/x")
    assert s.effective_database_url == "postgresql+psycopg://u:p@localhost:5432/x"


def test_url_is_built_from_parts_with_tls_verification():
    s = _s(db_host="mydb.abc123.ap-south-1.rds.amazonaws.com", db_user="hackeduler", db_password="p", db_name="hackeduler")
    u = make_url(s.effective_database_url)
    assert u.host.endswith(".rds.amazonaws.com") and u.port == 5432 and u.database == "hackeduler"
    assert u.query["sslmode"] == "verify-full" and u.query["sslrootcert"] == "/certs/rds-global-bundle.pem"
    assert u.query["connect_timeout"] == "10"


def test_password_with_special_characters_survives():
    pw = "a/b@c:d?e#f%g&h=i j+k'\"\\"
    s = _s(db_host="h.example", db_password=pw)
    assert make_url(s.effective_database_url).password == pw


def test_sslmode_require_has_no_root_cert_and_disable_is_honoured():
    assert "sslrootcert" not in make_url(_s(db_host="h", db_sslmode="require").effective_database_url).query
    assert make_url(_s(db_host="h", db_sslmode="disable").effective_database_url).query["sslmode"] == "disable"


def test_host_wins_over_the_default_localhost_url():
    s = _s(db_host="rds.example", database_url="postgresql+psycopg://postgres:postgres@localhost:5432/hackeduler")
    assert make_url(s.effective_database_url).host == "rds.example"
