#!/usr/bin/env python3
"""Apply the Crusader local co-op v0.4.2 HD-profile build marker.

The HD upscaling profiles are implemented as runtime OpenGL shader selections,
so this patch deliberately does not touch gameplay, AI, camera, input or save
logic. It only makes the executable identify the new build in its log.
"""
from pathlib import Path
import sys


def replace_exact(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: v042_post_patch.py <scummvm-source-root>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    coop = root / "engines/ultima/ultima8/world/actors/cru_coop_mover_process.cpp"
    if not coop.is_file():
        raise SystemExit(f"missing patched source file: {coop}")

    replace_exact(
        coop,
        'debug("Crusader co-op: Player 2 created as actor %u", playerTwo->getObjId());',
        'debug("Crusader co-op v0.4.2: Player 2 created as actor %u", playerTwo->getObjId());',
        "v0.4.2 runtime identification",
    )

    marker = root / ".crusader-coop-v042"
    marker.write_text(
        "Crusader: No Remorse local co-op v0.4.2\n"
        "HD profiles: OpenGL shader presets selected at runtime; gameplay code remains v0.4.1.\n",
        encoding="utf-8",
        newline="\n",
    )

    patched = coop.read_text(encoding="utf-8")
    if "Crusader co-op v0.4.2: Player 2 created as actor %u" not in patched:
        raise SystemExit("post-patch verification failed")

    print("Applied Crusader co-op v0.4.2 HD-profile build marker")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
