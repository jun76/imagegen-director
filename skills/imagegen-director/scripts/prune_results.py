"""Move generated images whose input no longer matches the current scenarios out of the way.

After L4 is edited or regenerated, a batch output still holds images made from old prompts, and
the batches refuse to run over a record whose input changed. This tool moves each such
image/record pair from <output> to <output>_superseded/, so the next batch run regenerates
exactly the changed rows and keeps everything else.

Refuses to run while a batch holds the output directory's lock.

usage: python scripts/prune_results.py --project DIR results/iris [--dry-run]
       (the output path is relative to the project directory)
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path



def output_busy(out):
    """True if a batch currently holds <out>/.batch.lock (IRIS: OS byte lock; Unsloth: lock file)."""
    lock = out / ".batch.lock"
    if not lock.exists():
        return False
    try:
        content = lock.read_bytes()
    except OSError:
        return True
    if content.startswith(b"{"):  # Unsloth writes {"pid", "host"} and deletes the file on exit
        return True
    with lock.open("a+b") as f:
        f.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f, fcntl.LOCK_UN)
        except OSError:
            return True
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("output", help="batch output directory relative to the project, e.g. results/iris")
    ap.add_argument("--project", required=True, help="project directory; every file the script reads or writes is inside it")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    root = Path(a.project).resolve()
    if not (root / "project.yaml").is_file():
        print(f"ERROR: {root} is not a project directory (no project.yaml)", file=sys.stderr)
        return 1
    out = (root / a.output).resolve()
    if output_busy(out):
        print("ERROR: a batch is running on this output; stop it first", file=sys.stderr)
        return 1
    current = {}
    for line in (root / "out/scenarios.jsonl").open(encoding="utf-8"):
        row = json.loads(line)
        current[row["scenario_id"]] = row
    superseded = out.parent / (out.name + "_superseded")

    stale, kept = [], 0
    for rec in sorted((out / "records").glob("*.json")):
        record = json.loads(rec.read_text(encoding="utf-8"))
        if record.get("scenario") == current.get(rec.stem):
            kept += 1
        else:
            stale.append(rec.stem)
    # Images whose record was lost carry the same data in the PNG; the batch recovers them itself.

    for sid in stale:
        for sub, ext in (("records", ".json"), ("images", ".png")):
            src = out / sub / (sid + ext)
            if src.exists() and not a.dry_run:
                (superseded / sub).mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(superseded / sub / (sid + ext)))
    verb = "would move" if a.dry_run else "moved"
    print(f"{verb} {len(stale)} stale rows to {superseded}; kept {kept}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
