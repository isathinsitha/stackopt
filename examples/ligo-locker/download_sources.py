"""Download the public LIGO source files and verify their recorded SHA-256 hashes."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="New directory for public source files")
    args = parser.parse_args()
    manifest = json.loads(Path(__file__).with_name("sources.json").read_text(encoding="utf-8"))
    args.destination.mkdir(parents=True)
    for source in manifest["files"]:
        with urlopen(source["url"], timeout=60) as response:
            data = response.read()
        if sha256(data).hexdigest() != source["sha256"]:
            raise ValueError(f"Source hash changed for {source['filename']}")
        (args.destination / source["filename"]).write_bytes(data)
        print(source["filename"])


if __name__ == "__main__":
    main()
