# Optional Fonts

ImmoApp can load local `.ttf` or `.otf` files from this directory through
`app/ui/font_loader.py`, but font binaries are not required for the source
repository. When no local font assets are present, the desktop client uses the
platform font fallback chain (including Segoe UI on Windows).

`OFL.txt` is retained as the license notice for optional SIL Open Font License
assets used by packaging/development workflows.
