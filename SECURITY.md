# Security

## Reporting a vulnerability

Please do not disclose security vulnerabilities through a public issue. Use a private GitHub security advisory for the repository, or contact the repository owner privately.

Include enough information to reproduce the issue, the affected component, and the expected security impact. Avoid attaching real customer data, credentials, private keys, or other sensitive material.

## Security model

ImmoApp includes tenant isolation, role-aware authorization, session controls, encrypted sensitive fields, audit trails, secret-management integration, and deployment hardening. The main design documentation is available in:

- `docs/architecture/AUTH_AND_SECURITY.md`
- `docs/architecture/ARCHITECTURE_INVARIANTS.md`
- `docs/architecture/STORAGE_AND_MEDIA.md`
- `docs/guides/OPENBAO_SETUP.md`

## Repository hygiene

Real `.env` files, local runtime state, production backups, database files, signing keys, tokens, and customer data must never be committed. Use the provided example environment files and local secret-management workflow instead.
