# Security and local hardening — E2E Solar

_This repository is a local development/demo stack, not a production deployment. Stage 9.2 adds a non-invasive audit and recovery groundwork without rotating live credentials._

## Read-only preflight

```powershell
uv run --frozen python scripts/security_audit.py
```

The command checks:

- Whether published Docker Compose ports bind only to loopback;
- Whether development-default PostgreSQL or pgAdmin passwords remain in the Compose file;
- Whether `.env`, database dumps or `backups/` files are accidentally tracked in Git;
- Whether Git and Docker ignore rules exclude `backups/`.

It **does not print password values**, execute SQL, restart services, or change Docker files. To turn every warning into a nonzero exit status, run `uv run --frozen python scripts/security_audit.py --strict` (not appropriate for the current default-password development stack).

## Known limitations to resolve before hosting publicly

1. `docker/docker-compose.yml` currently defines example values for `POSTGRES_PASSWORD` and `PGADMIN_DEFAULT_PASSWORD`. Loopback port binding helps protect the local setup but does not make such passwords suitable for any public service.
2. `dashboard/.env` contains the randomly generated read-only PostgreSQL password. Keep this file local and never copy it into Git, CI artifacts, Docker build contexts, or screenshots.
3. `docker-compose.override.yml` mounts secrets from the root `.env` into Airflow; webhook URLs are secrets too. Docker inspect and host accounts with Docker privileges can see runtime environment variables. Restrict host access accordingly.
4. The local Airflow uses SQLite and the simple auth manager. Streamlit is not designed here as an authenticated, publicly accessible service. Avoid routing those ports to the internet.
5. Current `pg_dump` archives are **not encrypted**. Keep backup directories on encrypted media or move them into protected backup storage.
6. Internal Airflow watchdog alerts cannot detect a complete host or Airflow shutdown. Use independent uptime monitoring if availability matters.

## Password rotation — do this as a separate change

**First complete `create` + `verify` in [backups.md](backups.md).** Do not merely change the `POSTGRES_PASSWORD` environment variable and recreate the existing database container: the official PostgreSQL image uses it to initialize a new cluster, not to rotate the password in an existing data volume.

A safe rotation plan includes:

1. Record which roles connect (scraper/Airflow admin connection and the dedicated `solar_dashboard` reader).
2. Choose strong unique credentials, store them in untracked files or a secret manager, and avoid pasting them into PowerShell history or Git.
3. Change the actual database role password using an authenticated PostgreSQL administration session (e.g. `psql`'s `\password` interactive command), then update the matching local application and Compose configuration **in a coordinated maintenance window**.
4. Recreate only affected containers without deleting any named volumes, then verify scraper, dbt, Streamlit and watchdog connections.
5. Rotate pgAdmin and webhook credentials separately. Use an authenticated reverse proxy or a separately hosted environment for any demo that must be reached publicly.

The current package deliberately does **not** change or rotate any passwords, for safety. Do not expose development services with their present example passwords.

## Operational references

- [Database backup and isolated restore](backups.md)
- [Release checklist](release_checklist.md)
- [Development runbook](development.md)
