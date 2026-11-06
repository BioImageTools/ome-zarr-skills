---
name: setup-ome-zarr-skills
description: "Record this repo's OME-Zarr preferences (spec version, RFCs in use, imaging domain) in docs/agents/ome-zarr.md so the other OME-Zarr skills stop guessing. Run once per repo, before first use of the other skills."
disable-model-invocation: true
---

# Setup OME-Zarr Skills

Write one file, `docs/agents/ome-zarr.md`, that answers three questions for this
repo. Every other skill in this set reads it when present and infers the
answers from context when absent.

1. **Spec version**: which OME-Zarr version the repo reads and writes.
2. **RFCs**: which NGFF RFCs the repo follows beyond that released version.
3. **Domain**: what kind of imaging data, so skills pick sensible axes, dtypes,
   chunking and metadata.

Prompt-driven, not a script. Explore, propose, confirm, then write.

## 1. Explore

Read what is there; don't assume:

- `docs/agents/ome-zarr.md`: prior output of this skill. If present, offer to update rather than start over.
- Sample data in or referenced by the repo: `zarr.json` → `attributes.ome.version`; `.zattrs` → `multiscales[0].version`. Also note axes names/units, dtypes, chunk shapes, presence of `omero`, `labels`, `plate`, `bioformats2raw.layout`.
- Code: version strings in writers/tests/fixtures; pinned libraries (`ome-zarr-py`, `ngff-zarr`, `iohub`, `bioformats2raw`, `zarr` major version, `tensorstore`, `ome-zarr-models`).
- `CLAUDE.md` / `AGENTS.md`: does an `## OME-Zarr` section already exist?
- Live reference: fetch https://ngff.openmicroscopy.org/specifications/index.html for the current released version, and https://ngff.openmicroscopy.org/rfc/index.html for the RFC table (number, status, target version). Never hardcode these; both change.

## 2. Propose and ask

One section at a time, leading with the recommended answer so the user can accept in a word. Skip a question exploration already settled.

**Section A: Spec version.**
Propose the version found in data or code (a `zarr<3` pin or `.zattrs` files mean 0.4 or older; `zarr.json` means 0.5+). If none found, propose the current released version from the index, ignoring `.devN` entries. Record one `target` version and a one-line `reason`. If the repo must also *read* older versions, record them as `also_read`; default `none`.

**Section B: RFCs.**
Show the user the RFC table from the live index, split three ways using its Status and OME-Zarr Version columns: already part of the target version or earlier (implied, nothing to record); adopted into a later version (choosing one means changing the target, say so); everything else (candidates). Ask which candidates, if any, the repo follows. Default: none. For each chosen RFC record number, title, status as of today, and one line on how it is used (e.g. "RFC-5 coordinate transformations, writing `coordinateSystems` alongside multiscales"). Warn that unadopted RFCs can change.

**Section C: Domain.**
Ask for, with examples drawn from exploration where possible:
- Modality: e.g. light-sheet, confocal, EM, expansion, HCS/plate, spatial-omics.
- Typical axes and units: e.g. `tczyx`, µm, seconds.
- Dtypes and bit depth: e.g. `uint16` raw, `uint32` or `uint64` labels.
- Typical scale: image size, number of channels, timepoints.
- Extras in use: `omero` rendering, `labels`, `plate`/`well`, `bioformats2raw.layout`.
- Storage: local filesystem, S3/GCS, zip; preferred chunk/shard sizes if known.
Use spec unit names (`micrometer`, `second`), not symbols. A value read from data or code is fact; a value you deduced gets an `(inferred)` tag; anything else is `unknown`. Do not invent.

## 3. Confirm

Show the draft `docs/agents/ome-zarr.md` and the `## OME-Zarr` block for `CLAUDE.md`/`AGENTS.md`. Let the user edit before writing.

## 4. Write

Start from [ome-zarr.md](./ome-zarr.md) in this folder, fill it in with today's date, and delete the HTML comments. Write to `docs/agents/ome-zarr.md`.

Pick the instructions file: edit `CLAUDE.md` if it exists, else `AGENTS.md`; if neither exists, ask which to create. If an `## OME-Zarr` block exists, update it in place. The block:

```markdown
## OME-Zarr

Target spec version [X]; RFCs: [list or none]; domain: [one line]. See `docs/agents/ome-zarr.md`.
```

## 5. Done

Tell the user which file was written and that other OME-Zarr skills now read it. They can edit it by hand; re-run only to change version or start over.
