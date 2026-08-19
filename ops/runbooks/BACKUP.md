# Offline Work Backup (External Drive)

Use this guide to move the app between PCs without internet.

## What to Copy

1) Repo (code + configs):
- `C:\path\to\immoapp`

2) Runtime data (optional, for Docker volumes/caches):
- `C:\ProgramData\ImmoApp\`

If you only want code, copy just the repo.

## Backup Commands (CMD)

Replace `X:` with your external drive letter.

```cmd
robocopy C:\path\to\immoapp X:\backups\immoapp /MIR /XD .git .venv venv env __pycache__ .mypy_cache .ruff_cache .pytest_cache
robocopy C:\ProgramData\ImmoApp X:\ImmoApp /MIR
```

Notes:
- `/MIR` mirrors the folder (keeps in sync).
- The repo excludes caches/venvs to keep it clean.

## Restore on Another PC

```cmd
robocopy X:\backups\immoapp C:\path\to\immoapp /MIR
robocopy X:\ImmoApp C:\ProgramData\ImmoApp /MIR
```

## Recreate the Two Venvs (Recommended)

This keeps server and client dependencies separate.

```cmd
py -3.14 -m venv C:\ProgramData\ImmoApp\venvs\immoapp-server-py314
py -3.14 -m venv C:\ProgramData\ImmoApp\venvs\immoapp-client-py314

C:\ProgramData\ImmoApp\venvs\immoapp-server-py314\Scripts\python.exe -m pip install -r requirements\server.txt
C:\ProgramData\ImmoApp\venvs\immoapp-client-py314\Scripts\python.exe -m pip install -r requirements\client.txt
```

## Start Stack

```cmd
cd C:\path\to\immoapp
docker compose --project-directory . -f deployment/compose/compose.yml -f deployment/compose/compose.windows.yml up -d
```

## Clean-Slate Option (DB Reset)

If you want a fresh empty database on the new PC:
```cmd
docker compose --project-directory . -f deployment/compose/compose.yml -f deployment/compose/compose.windows.yml down
rmdir /S /Q C:\ProgramData\ImmoApp\data\pgdata
```
