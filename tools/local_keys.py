"""Generate local-only service keys for service-to-service tokens.

    python tools/local_keys.py            # creates infrastructure/local/secrets/ (git-ignored)

Each calling service gets an EC P-256 key pair: the private key stays with the service,
Identity gets the public key (SERVICE_PUBLIC_KEYS). Existing keys are kept. Never use these
files outside local development; the secret store for shared environments is still TBD.
"""

from __future__ import annotations

from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

SECRETS = Path(__file__).resolve().parents[1] / "infrastructure" / "local" / "secrets"
CALLERS = ["reference"]


def main() -> None:
    SECRETS.mkdir(parents=True, exist_ok=True)
    for name in CALLERS:
        private_path, public_path = SECRETS / f"{name}_service.pem", SECRETS / f"{name}_service.pub"
        if private_path.exists() and public_path.exists():
            print(f"kept    {private_path.name}")
            continue
        key = ec.generate_private_key(ec.SECP256R1())
        private_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                   serialization.NoEncryption()))
        public_path.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,
                                                              serialization.PublicFormat.SubjectPublicKeyInfo))
        print(f"created {private_path.name}, {public_path.name}")


if __name__ == "__main__":
    main()
