"""Check tracked public paths, common credential formats, links and vendor hashes."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_NAMES = {"config.local.json", "runtime.local.json", ".env"}
PRIVATE_DIRS = {"state", "downloads", "materials", "private-state", "receipts", "work", ".venv"}
TOKEN = re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")


def main():
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    paths = [ROOT / p.decode("utf-8") for p in listed.stdout.split(b"\0") if p]
    assert paths, "No tracked source files"
    for path in paths:
        rel = path.relative_to(ROOT)
        assert path.name not in PRIVATE_NAMES and not path.name.startswith(".env."), str(rel)
        assert not set(rel.parts) & PRIVATE_DIRS, str(rel)
        assert path.suffix not in {".db", ".db-wal", ".db-shm", ".log", ".pyc", ".zip", ".whl"}, str(rel)
        assert not TOKEN.search(path.read_bytes()), "Credential-shaped content: " + str(rel)
        if path.suffix == ".md":
            for target in re.findall(r"\]\(([^)\s]+)\)", path.read_text(encoding="utf-8")):
                if ":" in target or target.startswith("#"):
                    continue
                assert (path.parent / target.split("#", 1)[0]).exists(), str(rel) + ": " + target
    vendor = ROOT / "chat-task-bridge/vendor"
    for name, expected in json.loads((vendor / "SHA256SUMS.json").read_text(encoding="utf-8")).items():
        assert hashlib.sha256((vendor / name).read_bytes()).hexdigest() == expected, name
    print(json.dumps({"ok": True, "tracked_public_files": len(paths), "vendor_hashes": "passed", "markdown_links": "passed"}))


if __name__ == "__main__":
    main()
