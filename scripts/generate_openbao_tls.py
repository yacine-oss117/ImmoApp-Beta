from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _build_ca(now: datetime) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ImmoApp OpenBao CA")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=False,
                key_cert_sign=True,
                key_agreement=False,
                data_encipherment=False,
                content_commitment=False,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    return key, cert


def _build_server(
    now: datetime,
    *,
    ca_key: rsa.RSAPrivateKey,
    ca_cert: x509.Certificate,
    common_name: str,
    sans: list[str],
) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    san_ext = x509.SubjectAlternativeName([x509.DNSName(name) for name in sans])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(san_ext, critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                key_cert_sign=False,
                key_agreement=False,
                data_encipherment=False,
                content_commitment=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    return key, cert


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate OpenBao internal TLS certificates.")
    parser.add_argument(
        "--tls-dir",
        default=r"C:\ProgramData\ImmoApp\secrets\openbao\tls",
        help="Directory for ca.crt/ca.key/server.crt/server.key",
    )
    parser.add_argument(
        "--app-secrets-dir",
        default=r"C:\ProgramData\ImmoApp\secrets",
        help="Directory where openbao-ca.crt is copied for app trust",
    )
    parser.add_argument(
        "--common-name",
        default="openbao",
        help="Common Name for server certificate",
    )
    parser.add_argument(
        "--san",
        action="append",
        default=["openbao", "localhost"],
        help="Subject Alternative Name (DNS). Can be provided multiple times.",
    )
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    tls_dir = Path(args.tls_dir)
    secrets_dir = Path(args.app_secrets_dir)

    ca_key, ca_cert = _build_ca(now)
    server_key, server_cert = _build_server(
        now,
        ca_key=ca_key,
        ca_cert=ca_cert,
        common_name=args.common_name,
        sans=args.san,
    )

    _write(
        tls_dir / "ca.key",
        ca_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ),
    )
    _write(tls_dir / "ca.crt", ca_cert.public_bytes(serialization.Encoding.PEM))
    _write(
        tls_dir / "server.key",
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ),
    )
    _write(tls_dir / "server.crt", server_cert.public_bytes(serialization.Encoding.PEM))
    _write(secrets_dir / "openbao-ca.crt", (tls_dir / "ca.crt").read_bytes())

    print(f"OpenBao TLS assets generated in {tls_dir}")
    print(f"App CA trust copied to {(secrets_dir / 'openbao-ca.crt')}")


if __name__ == "__main__":
    main()
