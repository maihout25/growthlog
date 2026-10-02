import os
import secrets
import tempfile
from pathlib import Path


def configure_hosting(app):
    """Keep local defaults; enable HTTPS settings only on the hosting server."""
    production = os.environ.get("GROWTHLOG_ENV", "local") == "production"
    data_directory = Path(os.environ.get("GROWTHLOG_DATA_DIR") or app.instance_path).resolve()
    hosts = [
        host.strip() for host in os.environ.get("GROWTHLOG_TRUSTED_HOSTS", "").split(",")
        if host.strip()
    ]
    if production and not hosts:
        raise RuntimeError("Set GROWTHLOG_TRUSTED_HOSTS to your website's hostname before hosting.")
    app.secret_key = load_secret_key(data_directory)
    app.config.update(
        DATABASE=data_directory / "growthlog.sqlite3",
        PRODUCTION=production,
        ALLOW_REGISTRATION=os.environ.get("GROWTHLOG_ALLOW_REGISTRATION", "1") == "1",
        ALLOW_SETUP=not production,
        SESSION_COOKIE_SECURE=production,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        TRUSTED_HOSTS=hosts or None,
    )
    if production:
        app.config.update(DEBUG=False, TESTING=False)


def load_secret_key(instance_path):
    """Keep signed login cookies valid when the local server restarts."""
    configured_key = os.environ.get("GROWTHLOG_SECRET_KEY")
    if configured_key:
        return configured_key
    directory = Path(instance_path)
    directory.mkdir(parents=True, exist_ok=True)
    key_path = directory / "secret_key"
    if not key_path.exists():
        # Publish a fully written file atomically, including when two processes start.
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                         prefix=".secret-", delete=False) as key_file:
            key_file.write(secrets.token_hex(32))
            temporary_path = Path(key_file.name)
        try:
            try:
                os.link(temporary_path, key_path)
            except FileExistsError:
                pass
        finally:
            temporary_path.unlink()
    key = key_path.read_text(encoding="utf-8").strip()
    if len(key) < 32:
        raise RuntimeError("The local secret_key file is incomplete. Restore it from a backup.")
    return key
