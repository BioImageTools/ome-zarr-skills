# /// script
# requires-python = ">=3.11"
# ///
"""Run inspect-ome-zarr on every store in stores.toml and check expectations.

    uv run tests/inspect-ome-zarr/run_all.py [--only SUBSTR] [--out DIR]

Writes DIR/<id>.md (report), DIR/<id>.json and DIR/summary.json.
Fixture URLs ("fixtures/...") resolve against DIR/.. unless --fixtures is given.
Exit code 1 if any expectation fails.
"""
import argparse
import json
import subprocess
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parents[1] / "skills" / "inspect-ome-zarr" / "scripts" / "inspect_ome_zarr.py"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--out", default="out")
    ap.add_argument("--fixtures", default="fixtures", help="dir made by make_fixtures.py")
    ap.add_argument("--detail", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    stores = tomllib.loads((HERE / "stores.toml").read_text())["store"]
    summary, failed = [], 0
    for s in stores:
        if a.only and a.only not in s["id"]:
            continue
        url = s["url"]
        if url.startswith("fixtures/"):
            url = str(Path(a.fixtures) / url.removeprefix("fixtures/"))
        jpath = out / f"{s['id']}.json"
        cmd = ["uv", "run", "-q", str(SCRIPT), url, "--json-out", str(jpath)] + (["--detail"] if a.detail else [])
        r = subprocess.run(cmd, capture_output=True, text=True)
        (out / f"{s['id']}.md").write_text(r.stdout if r.returncode == 0 else f"ERROR\n{r.stderr}")
        codes = set()
        if r.returncode == 0 and jpath.exists():
            codes = {f["code"] for f in json.loads(jpath.read_text())["findings"]}
        missing = [c for c in s.get("expect", []) if c not in codes]
        unwanted = [c for c in s.get("forbid", []) if c in codes]
        ok = r.returncode == 0 and not missing and not unwanted
        failed += not ok
        summary.append({"id": s["id"], "url": s["url"], "ok": ok, "exit": r.returncode,
                        "missing": missing, "unwanted": unwanted, "codes": sorted(codes),
                        "facts": s.get("facts", []), "modality": s.get("modality")})
        print(f"{'PASS' if ok else 'FAIL'}  {s['id']:28} {', '.join(sorted(codes)) or '-'}"
              + (f"  missing={missing}" if missing else "") + (f"  unwanted={unwanted}" if unwanted else "")
              + ("" if r.returncode == 0 else f"  exit={r.returncode}: {r.stderr.strip()[-200:]}"))
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
