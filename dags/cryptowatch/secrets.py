"""Secret access. Local/CI: environment variable CW_SECRET_<NAME>. Cloud: Secret Manager (latest version)."""
from __future__ import annotations

import os


def get_secret(project: str, name: str) -> str:
    env = os.environ.get("CW_SECRET_" + name.upper().replace("-", "_"))
    if env:
        return env
    from google.cloud import secretmanager
    client = secretmanager.SecretManagerServiceClient()
    return client.access_secret_version(name=f"projects/{project}/secrets/{name}/versions/latest").payload.data.decode()
