"""Static audit tests; never inspect personal credentials."""
from scripts.security_audit import credential_warnings, listen_address, local_bind_warnings


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
