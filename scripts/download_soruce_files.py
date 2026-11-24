#!/usr/bin/env python3

import hashlib
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

try:
    yaml = __import__("yaml")
except ImportError:
    print("Please install pyyaml module: pip install pyyaml")
    sys.exit(1)

import requests

def calculate_sha(file_path):

    hash_for_instance=hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_for_instance.update(chunk)
    return hash_for_instance.hexdigest()

def parse_yaml_manifest(yaml_file_path):
    with open(yaml_file_path, 'r') as f:
        data = yaml.safe_load(f)

    if isinstance(data, dict):
        for key in data.keys():
            if key in data:
                items=data[key]
                if isinstance(items, list):
                    return [extract_url(item) for item in items]

def extract_url(entry):
    if isinstance(entry, str):
        return entry
    raise ValueError("Entry does not contain a 'url' field or is not a string.")

def download_file(url, output_dir="."):
    try:
        os.makedirs(output_dir, exist_ok=True)
        print(f"Downloading {url}...")
        response = requests.get(url, stream=True, timeout=10)
        response.raise_for_status()

        temp_path=os.path.join(output_dir, ".temp")
        with open(temp_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=4096):
                f.write(chunk)

        sha256=calculate_sha(temp_path)

        parsed=urlparse(url)
        extension=os.path.splitext(parsed.path)[1]
        if not extension or len(extension)>10:
            extension=".bin"

        file_name=f"{sha256}{extension}"
        final_path=os.path.join(output_dir, file_name)

        counter=1
        while os.path.exists(final_path):
            final_path=os.path.join(output_dir, f"{sha256}_{counter}{extension}")
            counter+=1

        os.rename(temp_path, final_path)
        print(f"Downloaded and saved to {final_path}")
        print(f"SHA256: {sha256}")
        print(f"File size: {os.path.getsize(final_path)} bytes")
        print(f"Saved as: {file_name}")
        return final_path

    except Exception as e:
        print(f"Error downloading {url}: {e}")
        temp_path=os.path.join(output_dir, ".temp")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return None
def main():
    if len(sys.argv) != 1:
        print("Usage: python scripts/download_soruce_files.py")
        sys.exit(1)

    project_root = Path(__file__).resolve().parent.parent
    manifest_path = project_root / "scripts" / "manifest_file.yaml"
    output_dir = project_root / "data" / "source_files"

    if not manifest_path.is_file():
        print(f"Manifest file {manifest_path} does not exist.")
        sys.exit(1)

    try:
        urls=parse_yaml_manifest(str(manifest_path))
        print(f"Found {len(urls)} URLs in the manifest.")
        if not urls:
            print("No URLs found in the manifest.")
            sys.exit(1)

        for url in urls:
            download_file(url, output_dir=output_dir)

    except Exception as e:
        print(f"Error processing manifest: {e}")
        sys.exit(1)
    print("Script completed successfully.")

if __name__ == "__main__":
    main()