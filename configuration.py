import os
import secrets
import tempfile
from pathlib import Path


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
