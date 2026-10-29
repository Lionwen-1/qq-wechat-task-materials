"""Build a deterministic source ZIP; never include bindings, runtime state or media."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from bridge import ROOT, VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT.parents[1] / "outputs/chat-task-bridge")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    vendor = ROOT / "vendor"
    vendor_hashes = {p.relative_to(vendor).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in sorted(vendor.rglob("*")) if p.is_file()
                     and "__pycache__" not in p.parts and p.name != "SHA256SUMS.json"}
    (vendor / "SHA256SUMS.json").write_text(json.dumps(vendor_hashes, indent=2) + "\n", encoding="utf-8")
    approved = {"README.md", "LICENSE", ".gitignore", "config.example.json", "requirements.txt", "requirements-lock-windows-py310.txt",
                "upstream-versions.json", "setup.ps1", "prepare-qq.ps1"}
    paths = [p for p in ROOT.iterdir() if p.is_file() and (p.name in approved or p.suffix == ".py")]
    paths += [p for p in vendor.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    contents = {p.relative_to(ROOT).as_posix(): p.read_bytes() for p in sorted(paths)}
    assert "config.local.json" not in contents
    assert all(not n.endswith((".pyc", ".db", ".zip", ".log")) for n in contents)
    manifest = {"version": VERSION, "files": {name: hashlib.sha256(body).hexdigest() for name, body in contents.items()}}
    contents["release-manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    path = args.output / ("chat-task-bridge-" + VERSION + ".zip")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, body in sorted(contents.items()):
            info = zipfile.ZipInfo("chat-task-bridge/" + name, date_time=(2026, 10, 30, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, body, compresslevel=9)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    line = digest + "  " + path.name + "\n"
    for name in ("SHA256SUMS.txt", "SHA256SUMS-v" + VERSION + ".txt"):
        (args.output / name).write_text(line, encoding="utf-8")
    (args.output / "LATEST.txt").write_text(path.name + "\n", encoding="utf-8")
    print(json.dumps({"version": VERSION, "path": str(path), "bytes": path.stat().st_size,
                      "files": len(contents), "sha256": digest}, ensure_ascii=False))


if __name__ == "__main__":
    main()
