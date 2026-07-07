# TimerAuto optimized source package

This package is a cleaned source/build package. It removes local runtime junk from the shared zip and adds safer build switches.

## What changed

- Build output no longer includes local `config.json` / `profile.json` by default.
- Player portraits under `image/players` are excluded by default from release builds.
- OCR/Torch packaging can be skipped with `-NoOcr` for a much lighter build.
- App runtime logs are pruned automatically, keeping the latest 50 `timerauto_*.log` files.
- Release cleanup removes common local folders/files such as logs, caches, `.git`, `.vscode`, `.codex`, and `.agents`.
- `.gitignore` now covers additional local/scratch files.

## Build examples

Clean general release:

```powershell
.\build_release.ps1 -Version 1.0.0
```

Light release without OCR/Torch:

```powershell
.\build_release.ps1 -Version 1.0.0 -NoOcr
```

RFC/private pack with your config and player images:

```powershell
.\build_release.ps1 -Version 1.0.0 -IncludeUserConfig -IncludePlayerImages
```

## Notes

- `-NoOcr` makes OCR features unavailable unless the user has the dependencies installed separately; the app should fail gracefully when OCR is requested.
- GitHub Actions uses the clean defaults unless you edit the workflow command.
