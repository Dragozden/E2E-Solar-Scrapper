"""Static audit tests; never inspect actual credentials."""
from scripts.security_audit import credential_warnings, listen_address, local_bind_warnings, local_secret_warnings


def test_localhost_short_ports_are_safe():
    assert listen_address("127.0.0.1:5432:5432") == "127.0.0.1"
    assert listen_address("127.0.0.1:8501:8501") == "127.0.0.1"


def test_public_bind_detection():
    config = {"services": {"postgres": {"ports": ["5432:5432"]}}}
    assert "Port exposed" in local_bind_warnings(config)[0]


def test_no_warning_for_loopback_only():
    config = {"services": {"postgres": {"ports": ["127.0.0.1:5432:5432"]}}}
    assert not local_bind_warnings(config)


def test_default_credentials_warn_without_echoing_secret():
    config = {"services": {"postgres": {"environment": {"POSTGRES_PASSWORD": "postgres"}},
                           "pgadmin": {"environment": {"PGADMIN_DEFAULT_PASSWORD": "admin"}}}}
    result = credential_warnings(config)
    assert len(result) == 2
    assert all("password" in value for value in result)


def test_local_secrets_warn_when_missing(tmp_path):
    assert "Missing" in local_secret_warnings(tmp_path)[0]


def test_local_secrets_match(tmp_path):
    (tmp_path / "docker").mkdir()
    (tmp_path / ".env").write_text("POSTGRES_PASSWORD=an-unpredictable-local-database-password-value\n")
    (tmp_path / "docker" / ".env").write_text(
        "POSTGRES_PASSWORD=an-unpredictable-local-database-password-value\n"
        "PGADMIN_DEFAULT_PASSWORD=separate-unpredictable-admin-password-value\n"
    )
    assert not local_secret_warnings(tmp_path)


def test_local_secrets_warn_on_mismatch(tmp_path):
    (tmp_path / "docker").mkdir()
    (tmp_path / ".env").write_text("POSTGRES_PASSWORD=one-long-unique-generated-password\n")
    (tmp_path / "docker" / ".env").write_text(
        "POSTGRES_PASSWORD=another-long-unique-generated-password\n"
        "PGADMIN_DEFAULT_PASSWORD=admin\n"
    )
    assert len(local_secret_warnings(tmp_path)) >= 2
