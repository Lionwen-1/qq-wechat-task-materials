"""Build the portable skill + program bundle without local bindings or data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

from bridge import ROOT, VERSION

SKILL_FILES = ("SKILL.md", "LICENSE", "agents/openai.yaml", "references/cli-and-mcp.md", "references/materials.md",
               "scripts/chat_materials.py", "runtime.example.json")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT.parents[1] / "outputs/chat-task-bridge")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(ROOT / "package_release.py"), "--output", str(args.output)],
                   env={**os.environ, "PYTHONIOENCODING": "utf-8"}, check=True)
    with zipfile.ZipFile(args.output / ("chat-task-bridge-" + VERSION + ".zip")) as source:
        contents = {name: source.read(name) for name in source.namelist()}
    for name in SKILL_FILES:
        contents["qq-wechat-task-materials/" + name] = (args.skill / name).read_bytes()
    manifest = {"version": VERSION, "skill": "qq-wechat-task-materials",
                "files": {n: hashlib.sha256(b).hexdigest() for n, b in sorted(contents.items())}}
    contents["bundle-manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    path = args.output / ("qq-wechat-task-materials-" + VERSION + ".zip")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, body in sorted(contents.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 30, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, body, compresslevel=9)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    checksum = args.output / (path.stem + ".sha256")
    checksum.write_text(digest + "  " + path.name + "\n", encoding="utf-8")
    print(json.dumps({"version": VERSION, "path": str(path), "bytes": path.stat().st_size,
                      "files": len(contents), "sha256": digest}, ensure_ascii=False))


if __name__ == "__main__":
    main()
