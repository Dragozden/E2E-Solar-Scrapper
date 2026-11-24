# Security and local hardening — E2E Solar

_Stage 9.3: local development credentials stored outside Git and rotated only after a verified PostgreSQL backup._

## Read-only security preflight

```powershell
uv run --frozen python scripts/security_audit.py
uv run --frozen python scripts/security_audit.py --strict
```

The audit checks localhost-only published ports, plaintext example passwords in the Compose source, whether local PostgreSQL credentials agree between root `.env` and `docker/.env`, missing/default/short local secrets, accidentally tracked secret or dump files, and ignore rules. It never prints password values, connects to the DB, or changes services.

## Local credential management

- Compose now references `${POSTGRES_PASSWORD:?…}` and `${PGADMIN_DEFAULT_PASSWORD:?…}` instead of putting example passwords in a public YAML file.
- The **root `.env`** provides PostgreSQL access to the Windows scraper, dbt, and the Airflow container.
- The **`docker/.env`** file supplies only secret substitutions for Docker Compose when invoked in `docker/`.
- The **`dashboard/.env`** remains a separate SELECT-only database identity; rotation of PostgreSQL admin credentials does not change its password.
- All three files are ignored by Git and Docker build contexts. Shell environment variables take precedence over Compose `.env`; unset conflicting `POSTGRES_PASSWORD` / `PGADMIN_DEFAULT_PASSWORD` shell overrides before running Compose.

Existing populated installations **must not** use `init`. Follow [Credential rotation](credential_rotation.md), including verifying a fresh backup and checking restored data first. The `rotate` command performs `ALTER ROLE`, validates a new PostgreSQL login and synchronizes the two local files with best-effort rollback on error. It does **not** restart services automatically, and a power failure between SQL and filesystem updates may require manual reconciliation.

The official PostgreSQL image does **not** rotate existing role passwords if `POSTGRES_PASSWORD` alone changes. The script issues the actual authenticated SQL update.

## Additional limitations before public deployment

1. **Airflow** currently runs with SQLite and its simple authentication manager; this is appropriate for a controlled local environment, not public access.
2. **Streamlit** remains an unauthenticated local service. Its read-only role reduces database permissions, but does not provide application-level access control.
3. Docker host/daemon administrators can view container environment variables. Running multiple services as Docker containers is not a secret isolation boundary.
4. pgAdmin has its **own application account database**. The `PGADMIN_DEFAULT_PASSWORD` variable configures the initial admin account, and changing it does not necessarily rotate an existing login if pgAdmin state is reused. Verify the new login manually; preserve/export server registrations before intentionally resetting pgAdmin state.
5. Backups are not encrypted by the backup script. Protect off-machine copies using encrypted storage, and treat manifest hashes as integrity checks, **not** encryption or a secure signature.
6. The Airflow watchdog does not detect that the entire host is offline; independent uptime monitoring remains a later improvement.
7. This package does not rotate webhook secrets or the `solar_dashboard` role password. Handle either of those in a distinct controlled change.

## Further reading

- [Credential rotation](credential_rotation.md)
- [Verified PostgreSQL backup and restore](backups.md)
- [Release checklist](release_checklist.md)
