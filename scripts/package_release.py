"""Build a complete plugin ZIP from an explicit source allowlist and hash assets."""

from __future__ import annotations

import argparse
import hashlib
import re
import tomllib
import zipfile
from pathlib import Path

SOURCE_DIRECTORIES = (
    ".agents", ".codex-plugin", ".github", "docs", "scripts", "skills", "src", "tests"
)
SOURCE_FILES = (
    ".gitignore", ".mcp.json", "CHANGELOG.md", "LICENSE", "README.md",
    "pyproject.toml", "uv.lock", "关联OpenList.cmd",
    "artifacts/openlist-mcp-smoke.json", "artifacts/openlist-multimount-smoke.json",
)
REQUIRED_FILES = (
    ".agents/plugins/marketplace.json", ".codex-plugin/plugin.json", ".mcp.json",
    "pyproject.toml", "uv.lock", "README.md", "LICENSE", "关联OpenList.cmd",
    "scripts/start-browser-link.ps1", "skills/openlist/SKILL.md",
    "src/openlist_codex/server.py", "src/openlist_codex/browser_link.py",
    "src/openlist_codex/browser_session.py",
)
IGNORED_DIRECTORIES = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache",
    ".mypy_cache", ".cache", "dist", "build", "node_modules", "tmp", "temp",
    "browser-profile", "browser-profiles", "downloads",
}
SENSITIVE_FILES = {
    "credentials.json", "session.json", "browser-session.json",
    "openlist-token.txt", "openlist-password.txt", "token.txt", "password.txt",
}


def include_source(path: Path) -> bool:
    for part in path.parts:
        lower = part.lower()
        if lower in IGNORED_DIRECTORIES or lower.endswith(".egg-info"):
            return False
        if lower.startswith(("browser-profile-", "pytest-", "tmp_")):
            return False
    name = path.name.lower()
    return not (
        name in SENSITIVE_FILES
        or name == ".env"
        or name.startswith(".env.")
        or name.endswith((".pyc", ".pyo", ".tmp", ".dpapi", ".pem", ".key", ".p12"))
    )


def collect_sources(root: Path) -> list[Path]:
    sources = {Path(name) for name in SOURCE_FILES if (root / name).is_file()}
    for directory in SOURCE_DIRECTORIES:
        base = root / directory
        if base.is_symlink():
            raise ValueError(f"Source directory must not be a symlink: {directory}")
        if not base.is_dir():
            continue
        for source in base.rglob("*"):
            relative = source.relative_to(root)
            if not include_source(relative):
                continue
            if source.is_symlink():
                raise ValueError(f"Source path must not be a symlink: {relative}")
            if source.is_file():
                sources.add(relative)
    missing = set(map(Path, REQUIRED_FILES)) - sources
    if missing:
        raise ValueError("Missing required plugin files: " + ", ".join(map(str, sorted(missing))))
    return sorted(sources, key=lambda value: value.as_posix())


def package_release(root: Path, output: Path) -> tuple[Path, int]:
    root = root.resolve()
    output = output.resolve()
    with (root / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]
    version = project["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+[A-Za-z0-9.+-]*", version):
        raise ValueError("Project version cannot be used in a release filename")
    package_name = re.sub(r"[-_.]+", "_", project["name"])
    archive_root = f"openlist-codex-plugin-{version}"
    archive_path = output / f"{archive_root}.zip"
    sources = collect_sources(root)
    output.mkdir(parents=True, exist_ok=True)
    sdist = output / f"{package_name}-{version}.tar.gz"
    wheels = list(output.glob(f"{package_name}-{version}-*.whl"))
    if not sdist.is_file() or len(wheels) != 1:
        raise ValueError("Build exactly one wheel and a source distribution first: uv build --out-dir dist")
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in sources:
            source = root / relative
            if source.is_symlink() or not source.resolve().is_relative_to(root):
                raise ValueError(f"Source escaped project directory: {relative}")
            archive.write(source, f"{archive_root}/{relative.as_posix()}")
    with zipfile.ZipFile(archive_path) as archive:
        broken = archive.testzip()
        if broken:
            raise ValueError(f"ZIP integrity check failed: {broken}")
        actual = set(archive.namelist())
        expected = {f"{archive_root}/{relative.as_posix()}" for relative in sources}
        if actual != expected or len(archive.infolist()) != len(expected):
            raise ValueError("ZIP content verification failed")
    assets = sorted([archive_path, sdist, wheels[0]], key=lambda value: value.name)
    hashes = []
    for asset in assets:
        with asset.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        hashes.append(f"{digest}  {asset.name}\n")
    (output / "SHA256SUMS").write_text("".join(hashes), encoding="utf-8")
    return archive_path, len(sources)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    archive, count = package_release(args.project, args.output or args.project / "dist")
    print(f"Created {archive.name}: {count} verified source files; SHA256SUMS written.")


if __name__ == "__main__":
    main()
