#!/usr/bin/env python3
"""Package a Doubao export into a single zip and optionally remove unpacked artifacts."""

from __future__ import annotations

import argparse
import shutil
import tempfile
import zipfile
from pathlib import Path


def add_tree(zf: zipfile.ZipFile, root: Path, arcname: str) -> None:
    zf.write(root, arcname=arcname)
    for child in sorted(root.rglob("*")):
        if child.is_file():
            zf.write(child, arcname=f"{arcname}/{child.relative_to(root).as_posix()}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--md", required=True, help="Path to rendered Markdown file")
    parser.add_argument("--assets-dir", required=True, help="Path to assets directory")
    parser.add_argument("--output-dir", required=True, help="Directory for final zip delivery")
    parser.add_argument("--zip-name", required=True, help="Final zip filename")
    parser.add_argument(
        "--keep-unpacked",
        action="store_true",
        help="Keep the Markdown file and assets directory in the output location",
    )
    args = parser.parse_args()

    md_path = Path(args.md).resolve()
    assets_dir = Path(args.assets_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    zip_name = args.zip_name if args.zip_name.lower().endswith(".zip") else f"{args.zip_name}.zip"
    zip_path = output_dir / zip_name

    if not md_path.is_file():
        raise FileNotFoundError(f"Markdown file not found: {md_path}")
    if not assets_dir.is_dir():
        raise FileNotFoundError(f"Assets directory not found: {assets_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="doubao-export-") as tmpdir:
        tmpdir_path = Path(tmpdir)
        staged_md = tmpdir_path / md_path.name
        staged_assets = tmpdir_path / assets_dir.name
        shutil.copy2(md_path, staged_md)
        shutil.copytree(assets_dir, staged_assets)

        with zipfile.ZipFile(
            zip_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as zf:
            zf.write(staged_md, arcname=staged_md.name)
            add_tree(zf, staged_assets, staged_assets.name)

    if not args.keep_unpacked:
        if md_path.parent == output_dir:
            md_path.unlink(missing_ok=True)
        if assets_dir.parent == output_dir:
            shutil.rmtree(assets_dir, ignore_errors=True)

    print(zip_path)


if __name__ == "__main__":
    main()
