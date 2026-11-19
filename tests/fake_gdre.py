"""File-backed GDRE stand-in; packs are JSON objects of resource path to bytes as text."""

import json
import os
import sys
from pathlib import Path


def main():
    assert sys.argv[1] == "--headless"
    action, source = sys.argv[2].split("=", 1)
    src = Path(source)
    options = dict(arg.split("=", 1) for arg in sys.argv[3:])
    out = Path(options["--output"])
    if action == "--extract":
        resource = options["--include"]
        pack = json.loads(src.read_text(encoding="utf-8"))
        if resource not in pack:
            sys.exit("Error: no files found that match includes")
        dst = out / resource.removeprefix("res://")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(pack[resource], encoding="utf-8", newline="\n")
    elif action in ("--compile", "--decompile"):
        assert options["--bytecode"] == "ebc36a7"
        if action == "--decompile" and (log := os.environ.get("FAKE_GDRE_DECOMPILES")):
            with open(log, "a", encoding="utf-8") as fh:
                print(src.name, file=fh)
        out.mkdir(parents=True, exist_ok=True)
        # GDScript compilation is insensitive to CRLF vs LF in the source.
        (out / src.with_suffix(".gdc" if action == "--compile" else ".gd").name).write_text(
            src.read_text(encoding="utf-8"), encoding="utf-8", newline="\n",
        )
    elif action == "--pck-patch":
        pack = json.loads(src.read_text(encoding="utf-8"))
        for arg in sys.argv[3:]:
            if arg.startswith("--patch-file="):
                script, resource = arg.removeprefix("--patch-file=").rsplit("=", 1)
                if resource != os.environ.get("FAKE_GDRE_DROP_RESOURCE"):
                    pack[resource] = Path(script).read_text(encoding="utf-8")
        out.write_text(json.dumps(pack), encoding="utf-8")
    else:
        sys.exit(f"Unexpected GDRE action: {action}")


if __name__ == "__main__":
    main()
