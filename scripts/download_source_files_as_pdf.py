"""Download PDFs from scripts/manifest_file.yaml with metadata tracking and skip logic."""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout, sync_playwright

CHUNK_SIZE = 64 * 1024
TIMEOUT_MS = 45_000
LOCKFILE_NAME = "manifest_lock.json"


def sanitize_filename(name: str) -> str:
    """Remove characters invalid in Windows/Linux/macOS filenames."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name.strip())
    return cleaned or "unnamed_file.pdf"


def load_manifest(manifest_path: Path) -> list[dict[str, str]]:
    """Parse YAML and return a list of {'file': ..., 'url': ...} entries."""
    raw_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))

    if isinstance(raw_data, dict):
        for val in raw_data.values():
            if isinstance(val, list):
                raw_data = val
                break

    if not isinstance(raw_data, list):
        raise ValueError("Manifest YAML must contain a list of entries.")

    entries = []
    for index, item in enumerate(raw_data, start=1):
        if not isinstance(item, dict) or "url" not in item or "file" not in item:
            raise ValueError(f"Entry #{index} must contain both 'file' and 'url' keys.")

        url = str(item["url"]).strip()
        filename = sanitize_filename(str(item["file"]))
        if not filename.lower().endswith(".pdf"):
            filename = f"{filename}.pdf"

        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"Invalid HTTP(S) URL in entry #{index}: {url}")

        entries.append({"file": filename, "url": url})

    return entries


def load_lockfile(lock_path: Path) -> dict[str, dict]:
    """Load existing metadata lockfile if present and valid."""
    if not lock_path.is_file():
        return {}
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_lockfile(lock_path: Path, metadata: dict[str, dict]) -> None:
    """Atomically write metadata lockfile to disk."""
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=lock_path.parent, prefix=".lock-", delete=False
    ) as tmp:
        tmp_path = Path(tmp.name)
        json.dump(metadata, tmp, indent=2, sort_keys=True)
        tmp.write("\n")
    os.replace(tmp_path, lock_path)


def file_sha256(path: Path) -> tuple[str, int]:
    """Compute SHA-256 hash and byte size of a saved file."""
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def is_valid_existing_pdf(
    destination: Path, url: str, recorded_meta: dict | None
) -> tuple[bool, str]:
    """Verify file exists on disk, is a valid PDF, and matches lockfile metadata."""
    if not destination.is_file():
        return False, "not on disk"

    if not recorded_meta:
        return False, "missing from lockfile"

    if recorded_meta.get("source_url") != url:
        return False, "source URL changed"

    try:
        with destination.open("rb") as f:
            if f.read(5) != b"%PDF-":
                return False, "corrupt PDF header"
        actual_sha256, actual_size = file_sha256(destination)
    except OSError:
        return False, "unreadable file"

    if actual_size == 0 or actual_sha256 != recorded_meta.get("sha256"):
        return False, "checksum mismatch"

    return True, "verified"


def download_rbi_pdf(
    page: Page,
    entry: dict[str, str],
    output_dir: Path,
    existing_meta: dict | None,
) -> dict | None:
    """Download PDF, validate it, and return updated metadata dict (or None on failure)."""
    url = entry["url"]
    target_name = entry["file"]
    destination = output_dir / target_name
    temporary_path: Path | None = None
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)

        pdf_link = page.locator(
            "a[href*='rbidocs.rbi.org.in'][href*='.pdf' i], "
            "a:has-text('PDF - Reserve Bank'):not(:has-text('Accessibility'))"
        ).first
        pdf_link.wait_for(state="visible", timeout=15_000)

        with tempfile.NamedTemporaryFile(
            mode="wb", dir=output_dir, prefix=".download-", delete=False
        ) as tmp:
            temporary_path = Path(tmp.name)

        try:
            with page.expect_download(timeout=20_000) as download_info:
                pdf_link.click()
            download = download_info.value
            download.save_as(temporary_path)
        except PlaywrightTimeout:
            href = pdf_link.get_attribute("href")
            if not href:
                raise ValueError("PDF link did not trigger a download and has no href.")
            pdf_url = page.evaluate("(h) => new URL(h, document.baseURI).href", href)
            api_response = page.context.request.get(pdf_url, timeout=TIMEOUT_MS)
            if not api_response.ok:
                raise ValueError(f"PDF request failed with HTTP {api_response.status}")
            temporary_path.write_bytes(api_response.body())

        with temporary_path.open("rb") as f:
            header = f.read(5)
        if header != b"%PDF-":
            raise ValueError(f"Downloaded file is not a valid PDF (starts with {header!r}).")

        sha256, size = file_sha256(temporary_path)

        # Check if remote document is identical to what we already had
        if (
            existing_meta
            and existing_meta.get("sha256") == sha256
            and destination.is_file()
        ):
            temporary_path.unlink(missing_ok=True)
            temporary_path = None
            updated_meta = {**existing_meta, "last_checked_at": now_iso}
            print(f"Unchanged -> {target_name} (SHA256 {sha256[:12]}...)")
            return updated_meta

        os.replace(temporary_path, destination)
        temporary_path = None
        print(f"Saved -> {target_name} ({size:,} bytes, SHA256 {sha256[:12]}...)")

        return {
            "file": target_name,
            "source_url": url,
            "sha256": sha256,
            "size_bytes": size,
            "downloaded_at": now_iso,
            "last_checked_at": now_iso,
        }

    except Exception as error:
        print(f"Failed [{target_name}]: {error}")
        return None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download PDFs listed in manifest_file.yaml.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download all files to check for remote updates even if already cached locally.",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    manifest_path = project_root / "scripts" / "manifest_file.yaml"
    output_dir = project_root / "data" / "source_files"
    lock_path = output_dir / LOCKFILE_NAME

    if not manifest_path.is_file():
        print(f"Manifest file not found: {manifest_path}", file=sys.stderr)
        return 1

    try:
        entries = load_manifest(manifest_path)
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as error:
        print(f"Could not read manifest: {error}", file=sys.stderr)
        return 1

    if not entries:
        print("Manifest contains no entries.", file=sys.stderr)
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = load_lockfile(lock_path)

    # Filter entries that actually need downloading
    to_download: list[dict[str, str]] = []
    for entry in entries:
        target_name = entry["file"]
        destination = output_dir / target_name
        recorded = metadata.get(target_name)

        if not args.force:
            valid, reason = is_valid_existing_pdf(destination, entry["url"], recorded)
            if valid:
                print(f"Skipped (already downloaded) -> {target_name}")
                continue
            elif destination.exists():
                print(f"Re-downloading {target_name} ({reason})...")

        to_download.append(entry)

    # Avoid launching Chromium at all if every file is already up to date
    if not to_download:
        print("All manifest files are already downloaded and verified.")
        return 0

    ignore_https = bool(os.environ.get("SSL_CERT_FILE"))
    failed = False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            accept_downloads=True,
            ignore_https_errors=ignore_https,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        for entry in to_download:
            target_name = entry["file"]
            result_meta = download_rbi_pdf(page, entry, output_dir, metadata.get(target_name))
            if result_meta is None:
                failed = True
            else:
                metadata[target_name] = result_meta
                # Save lockfile after each successful file so progress is never lost
                save_lockfile(lock_path, metadata)

        browser.close()

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
