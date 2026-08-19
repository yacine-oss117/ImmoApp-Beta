# TLC Setup (No Wave Run)

This project is configured to run TLA+ waves only when `TLA_TOOLS_JAR` is available.

## One-command setup

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_tla.ps1 -InstallJava
```

What it does:
- installs Temurin JDK 21 if Java is missing,
- downloads `tools/tla/tla2tools.jar`,
- sets user env vars:
  - `JAVA_HOME`
  - `TLA_TOOLS_JAR`

## Verify readiness (safe, no TLC model checking)

```powershell
python scripts/verify_tlc_ready.py
```

or

```bash
make tla-ready
```

## Important

This setup **does not run** `verify_tla_wave*` scripts.
Open a new terminal after setup so persisted env vars are picked up.
