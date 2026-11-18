"""Advance the CMake project version before preparing a release."""

import argparse
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("impact", choices=("fix", "feature", "breaking", "stable"))
    parser.add_argument("--apply", action="store_true", help="Write the proposed version")
    args = parser.parse_args()

    cmake = Path(__file__).resolve().parents[1] / "CMakeLists.txt"
    source = cmake.read_bytes()
    match = re.search(rb"(?m)^project\(AltairEQ VERSION (\d+\.\d+\.\d+) ", source)
    if match is None:
        parser.error("AltairEQ project version not found in CMakeLists.txt")

    current = match[1].decode("ascii")
    major, minor, patch = map(int, current.split("."))
    if args.impact == "stable":
        if major != 0:
            parser.error("The project already has a stable version number")
        new = (1, 0, 0)
    elif args.impact == "breaking" and major > 0:
        new = (major + 1, 0, 0)
    elif args.impact in ("feature", "breaking"):
        new = (major, minor + 1, 0)
    else:
        new = (major, minor, patch + 1)

    proposed = ".".join(map(str, new))
    if args.apply:
        start, end = match.span(1)
        cmake.write_bytes(source[:start] + proposed.encode("ascii") + source[end:])
    print(f"{current} -> {proposed}")


if __name__ == "__main__":
    main()
