"""Download HTTP(S) URLs from scripts/manifest_file.yaml and name them by the 'file' key."""

import hashlib
import os
import re
import ssl
import sys
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

import yaml  # Requires: pip install pyyaml

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
CHUNK_SIZE = 64 * 1024
TIMEOUT_SECONDS = 30


def ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    ca_bundle = os.environ.get("SSL_CERT_FILE")
    if ca_bundle:
        context.load_verify_locations(cafile=ca_bundle)
    return context


def sanitize_filename(name: str) -> str:
    """Remove characters that are invalid in Windows/Linux/macOS filenames."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name.strip())
    return cleaned or "unnamed_file"


def load_manifest(manifest_path: Path) -> list[dict[str, str]]:
    """Parse YAML and return a list of {'file': ..., 'url': ...} entries."""
    raw_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    
    # Handle both top-level lists and lists nested under a key (e.g., 'files:' or 'documents:')
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

        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"Invalid HTTP(S) URL in entry #{index}: {url}")

        entries.append({"file": filename, "url": url})

    return entries


def robots_allows(
    url: str,
    cache: dict[str, RobotFileParser],
    context: ssl.SSLContext,
) -> bool:
    parsed = urlsplit(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin not in cache:
        parser = RobotFileParser()
        robots_url = urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))
        request = Request(robots_url, headers={"User-Agent": USER_AGENT})
        try:
            with urlopen(
                request, timeout=TIMEOUT_SECONDS, context=context
            ) as response:
                rules = response.read().decode("utf-8", errors="replace").splitlines()
        except (HTTPError, URLError, TimeoutError):
            rules = []
        parser.set_url(robots_url)
        parser.parse(rules)
        cache[origin] = parser
    return cache[origin].can_fetch(USER_AGENT, url)


def file_extension(url: str, content_type: str) -> str:
    if content_type == "application/pdf":
        return ".pdf"
    if content_type == "text/html":
        return ".html"
    suffix = Path(urlsplit(url).path).suffix.lower()
    if suffix and len(suffix) <= 10:
        return suffix
    return ".bin"


def download_file(
    entry: dict[str, str],
    output_dir: Path,
    robots_cache: dict[str, RobotFileParser],
    context: ssl.SSLContext,
) -> Path | None:
    url = entry["url"]
    target_name = entry["file"]
    temporary_path: Path | None = None

    try:
        if not robots_allows(url, robots_cache, context):
            print(f"Skipped (robots.txt disallows this user agent): {url}")
            return None

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/pdf,text/html,application/xhtml+xml,*/*;q=0.8",
        }
        request = Request(url, headers=headers)
        response = urlopen(request, timeout=TIMEOUT_SECONDS, context=context)

        # An RBI page may point to the actual PDF through an embedded link.
        if response.headers.get_content_type() == "text/html" and target_name.endswith(".pdf"):
            with response:
                html = response.read().decode("utf-8", errors="replace")
            match = re.search(r'href=["\']([^"\']+\.pdf)["\']', html, re.IGNORECASE)
            if not match:
                raise ValueError("No embedded PDF link found on the webpage.")
            pdf_url = urljoin(url, match.group(1))
            response = urlopen(
                Request(pdf_url, headers=headers),
                timeout=TIMEOUT_SECONDS,
                context=context,
            )

        with response:
            detected_ext = file_extension(url, response.headers.get_content_type())
            
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=output_dir, prefix=".download-", delete=False
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                digest = hashlib.sha256()
                size = 0
                while chunk := response.read(CHUNK_SIZE):
                    temporary_file.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)

        # Append detected extension only if the YAML 'file' value doesn't already have one
        if not Path(target_name).suffix:
            target_name = f"{target_name}{detected_ext}"

        destination = output_dir / target_name
        os.replace(temporary_path, destination)
        temporary_path = None
        print(f"Saved {url} -> {destination.name} ({size} bytes, SHA256 {digest.hexdigest()})")
        return destination
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
        print(f"Failed to download {url}: {error}")
        return None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    manifest_path = project_root / "scripts" / "manifest_file.yaml"
    output_dir = project_root / "data" / "source_files"

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
    try:
        context = ssl_context()
    except (OSError, ssl.SSLError) as error:
        print(f"Invalid SSL_CERT_FILE CA bundle: {error}", file=sys.stderr)
        return 1

    robots_cache: dict[str, RobotFileParser] = {}
    failed = False
    for entry in entries:
        if download_file(entry, output_dir, robots_cache, context) is None:
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
