---
name: inspect-ome-zarr
description: Use whenever someone hands over a .zarr / .ome.zarr path or URL (local, zip, http(s), s3://, gs://) or asks "what's in this", "describe this dataset", "is this valid / correct", or about pixel size, channels, pyramid levels, chunking, sharding or compression of an OME-Zarr store, and before any conversion, rechunking, sharding, validation or analysis task on an existing store. Produces a read-only plain-language report plus optional JSON.
---

# Inspect OME-Zarr

Describe an existing OME-Zarr store so a biologist can read it and an agent can
act on it. Read-only: metadata, object sizes, and at most a few chunks from the
smallest pyramid level. Never load full-resolution pixels.

The deterministic work is in [scripts/inspect_ome_zarr.py](scripts/inspect_ome_zarr.py).
Run it; don't re-derive its numbers by hand.

## 1. Context first

- `docs/agents/ome-zarr.md` (from `/setup-ome-zarr-skills`) if it exists: note its
  target version and domain. The script reads it too and notes a version
  mismatch. Never require it.
- If the user named several stores, inspect each; if they pointed at a folder
  that isn't a store, the script lists candidate `*.zarr` children.

## 2. Run the script

```bash
uv run <skill-dir>/scripts/inspect_ome_zarr.py STORE            # short report
uv run <skill-dir>/scripts/inspect_ome_zarr.py STORE --detail   # per-level table, all images, notes
uv run <skill-dir>/scripts/inspect_ome_zarr.py STORE --json     # JSON only, for other tools
uv run <skill-dir>/scripts/inspect_ome_zarr.py STORE --json-out report.json  # report + JSON file
```

`uv` reads the dependencies from the script header (zarr ≥ 3, fsspec, s3fs,
gcsfs). Without `uv`: `pip install "zarr>=3" numpy fsspec s3fs gcsfs aiohttp`
then `python inspect_ome_zarr.py ...`. zarr 2.x cannot read Zarr v3 stores.

Useful flags:

| Flag | Use when |
|------|----------|
| `--anon` | Public bucket and local credentials get refused. Without it the script tries your credentials, then falls back to anonymous on s3/gs. |
| `--no-sample` | The user forbids reading any pixels, or the smallest level is still huge. |
| `--no-size` | Many images or a slow link; skips per-level size requests. |
| `--no-cors` | Offline or non-browser use. |
| `--max-images N` | Collections, wells or labels with many entries (default 20). |

Write JSON only when asked or when another skill needs it. Never write inside
the store.

## 3. Read the output

The report has a headline, a structure tree, one section per image, and
findings (errors and warnings; `--detail` adds info notes).

- **Headline**: kind of store (multiscale image, plate, collection, well, label
  image, plain Zarr group), OME-Zarr version, Zarr format, then the
  representative image in x,y,z order with pixel size and physical extent.
- **Storage**: chunk (and shard) shape, codecs, uncompressed vs on-disk size.
  On-disk size is `exact` for local and zip stores (files walked) and
  `estimated, inferred` remotely (fixed, evenly spaced object sizes per level,
  extrapolated). Say which when you quote it.
- **Sample**: value range and 1–99.9 % percentiles from ≤ 4 chunks of the
  smallest level. Good for suggesting a contrast window when `omero` is
  missing; tag such suggestions `(inferred)`.
- **Plates**: only the first field of the first well is inspected in depth;
  every well's metadata is read (up to 2000) to find missing wells and uneven
  fields. Say so when describing the plate.
- **JSON** (`--json`): same facts with spec unit names, raw scales and
  translations per level, findings as `{severity, code, path, message, fix}`.
  Field list in [references/output.md](references/output.md).
- How the script decides version, kind and where it reads each field:
  [references/versions.md](references/versions.md).

Exit 1 means the store could not be opened; the message names the failing URL
and what to try (credentials, `--anon`, wrong root). Relay it, don't guess.

## 4. Explain it to the user

Lead with the headline in 2–3 sentences of plain language: what it is, how big
physically, how many channels and timepoints, whether anything is wrong. Then
the sections they need. Keep it short unless they ask for detail; offer
`--detail` or the JSON.

For each error or warning, give the one-line fix from the report and what it
means in practice (e.g. "levels will be misaligned in napari / neuroglancer").
[references/anomalies.md](references/anomalies.md) explains every code, how
sure the check is, and what to do. Some checks are heuristics (`LEVEL_GAP`,
`TRANSLATION_IN_VOXELS`); present those as "looks like", not as fact.

When a finding depends on what the spec says for this version (allowed units,
axis order, required fields), use the `reading-ome-zarr-spec` skill to fetch
the spec for the version reported and quote it, rather than answering from
memory. Codes ending `_UNCHECKED` mean the version is outside the rules the
script encodes (0.4, 0.5); check that version's spec before calling it valid.

Label every value: read from metadata (fact), computed by the script from
metadata (fact), or estimated / sampled (inferred). Use spec unit names in
anything you write back to metadata (`micrometer`, not `µm`); the report uses
symbols only for display.

## 5. Hand off

If the user's next step is conversion, rechunking, sharding, validation or
analysis, pass along the JSON (or the relevant facts) rather than re-inspecting:
chunk/shard shapes, dtype, axes, scales, findings. Fix suggestions are just
suggestions; do not modify the store from this skill.

## Remote stores

- Credentials: AWS env vars / `AWS_PROFILE`, `gcloud auth application-default
  login` or `GOOGLE_APPLICATION_CREDENTIALS`. The report's `Access:` line says
  which was used.
- The script never lists a remote prefix recursively. It reads metadata paths
  named by OME metadata, probes `0, 1, 2 …` for bioformats2raw series without an
  `OME/series` list, and asks for the size of a fixed sample of chunk keys.
- **CORS** applies to browsers (viewers like Vizarr, neuroglancer), not to this
  script. The report's `browser CORS:` line comes from an anonymous request with an
  `Origin` header: `allowed`, `not advertised` (browser viewers will likely fail),
  or not checked for private data.
- Remote zip stores are read, but pixel sampling is skipped.

## Common mistakes

- Opening level 0 with zarr/dask "just to look". Use the script; it never does.
- Quoting a remote on-disk size as exact.
- Reporting the store's own `version` without checking the Zarr format matches
  (0.4 ↔ v2, 0.5 ↔ v3); the script flags `VERSION_FORMAT_MISMATCH`.
- Calling a store valid because there are no findings. The script is a
  linter, not a full validator; for strict spec validation say so and point to
  a validator (ome-zarr-models / yaozarrs, or the OME-NGFF validator).
- Pasting spec text into explanations from memory instead of fetching it via
  `reading-ome-zarr-spec`.
