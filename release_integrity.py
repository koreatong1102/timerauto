"""Release identity and complete-package verification (standard library only)."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
from pathlib import Path, PurePosixPath

MANIFEST = "release_manifest.json"


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_lock(path):
    return dict(line.strip().split("==", 1) for line in Path(path).read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#"))


def check_environment(root):
    root = Path(root)
    expected_python = (root / ".python-version").read_text().strip()
    errors = []
    if platform.python_version() != expected_python:
        errors.append(f"Python {platform.python_version()} != {expected_python}")
    if platform.architecture()[0] != "64bit":
        errors.append("64-bit Python required")
    for name, expected in read_lock(root / "requirements-release.lock").items():
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            actual = "missing"
        if actual != expected:
            errors.append(f"{name}: {actual} != {expected}")
    if errors:
        raise RuntimeError("Release environment mismatch:\n" + "\n".join(errors))


def create_manifest(source, package, version):
    source, package = Path(source).resolve(), Path(package).resolve()
    check_environment(source)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    files = {}
    for path in sorted(package.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(package).as_posix()
        # Mutable user data is deliberately not a release identity.
        if rel == MANIFEST or rel in {"config.json", "profile.json", "profile1.json", "as.json", "test.json", "latest.json"}:
            continue
        if rel.startswith(("image/", "logs/", "diagnostics/", "MatchLogArchive/", "SpectatorLogArchive/")):
            continue
        files[rel] = {"sha256": digest(path), "size": path.stat().st_size}
    if "timerauto.exe" not in files:
        raise ValueError("Missing timerauto.exe")
    sources = {p.name: digest(p) for p in sorted(source.glob("*.py"))}
    for name in ("timer_ui.qml", "cinematic_overlay.qml", "timer_controls.qml", "timerauto.spec", "requirements-release.lock"):
        sources[name] = digest(source / name)
    manifest = {"schema": 1, "version": version, "commit": commit,
                "python": platform.python_version(), "dependencies": read_lock(source / "requirements-release.lock"),
                "sources": sources, "files": files}
    (package / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    return manifest


def verify_package(package):
    package = Path(package).resolve()
    manifest = json.loads((package / MANIFEST).read_text(encoding="utf-8"))
    if manifest.get("schema") != 1 or not manifest.get("files"):
        raise ValueError("Invalid release manifest")
    errors = []
    for rel, expected in manifest["files"].items():
        parts = PurePosixPath(rel)
        if parts.is_absolute() or ".." in parts.parts or "\\" in rel or ":" in rel:
            raise ValueError("Unsafe manifest path")
        path = (package / rel).resolve()
        if not path.is_relative_to(package):
            raise ValueError("Manifest path escapes package")
        if not path.is_file():
            errors.append({"path": rel, "problem": "missing"})
        elif path.stat().st_size != expected["size"] or digest(path) != expected["sha256"]:
            errors.append({"path": rel, "problem": "changed"})
    return {"ok": not errors, "checked": len(manifest["files"]), "errors": errors,
            "version": manifest["version"], "commit": manifest["commit"], "python": manifest["python"]}


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    env = sub.add_parser("environment")
    env.add_argument("root")
    create = sub.add_parser("create")
    create.add_argument("source")
    create.add_argument("package")
    create.add_argument("version")
    verify = sub.add_parser("verify")
    verify.add_argument("package")
    args = parser.parse_args()
    if args.command == "environment":
        try:
            check_environment(args.root)
        except RuntimeError as exc:
            print(str(exc))
            return 1
    elif args.command == "create":
        create_manifest(args.source, args.package, args.version)
    else:
        result = verify_package(args.package)
        print(json.dumps(result, ensure_ascii=True))
        return 0 if result["ok"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
