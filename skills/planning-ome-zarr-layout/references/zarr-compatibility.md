# Zarr format and OME-Zarr version compatibility

Check two things separately for every consumer:

1. **Zarr format** (v2 or v3, sharding): decides whether the array layout can be read at all.
2. **OME-Zarr metadata version**: decides whether the tool understands the
   `ome` metadata (multiscales, coordinate transformations, labels). Versions that
   share a Zarr format share the layout rules, but they can differ in metadata,
   including breaking changes. A tool can open the arrays and still reject
   or misread the image.

Do not hardcode which versions exist. Read the current release and the version
history from https://ngff.openmicroscopy.org/specifications/index.html (or use
the `reading-ome-zarr-spec` skill), and record versions found on disk.

## OME-Zarr metadata version

- Store: `zarr.json` → `attributes.ome.version` (Zarr v3 versions);
  `.zattrs` → `multiscales[0].version` (Zarr v2 versions). Newer versions may
  drop per-object `version` fields and keep only `ome.version`, so read
  `ome.version` first.
- Consumer: which OME-Zarr versions the reader library supports (release notes,
  version checks in code, tests). Some readers refuse unknown versions; others open
  the arrays but ignore or misread changed metadata such as scales and translations.
- Writers adding to an existing hierarchy (labels, probabilities, segmentation
  written next to the image) must write the **same** OME-Zarr version as the
  hierarchy. The spec requires the version to be consistent within a hierarchy.
- If a consumer lags behind: write that output as a separate store, pin the
  pipeline to a version every consumer reads, or convert. Converting between
  versions with the same Zarr format is usually metadata-only; converting
  between Zarr formats is usually a data rewrite. Check the version history.

## Zarr format

A layout is only usable if every library that **opens** the store can read or
write it. That library may differ from the analysis tool: a script can read a
tile with zarr-python and pass a NumPy array to ilastik, Cellpose or another tool.
Check each consumer's actual environment (container, bundled interpreter, conda env),
not the system Python.

## Check the environment that opens the store

```bash
# use the interpreter the pipeline actually runs, e.g. a tool's bundled Python
<interpreter> -c "import sys; print(sys.version)"
<interpreter> -c "import zarr; print(zarr.__version__)"
<interpreter> -c "import tensorstore; print(tensorstore.__version__)"    # if present
```

Record per consumer: interpreter path, Python version, zarr-python (or other
library) version, and whether it reads and writes Zarr v3 and sharding. Read
values from the environment or lock files are facts; otherwise mark `(inferred)`.

## What each library can do

Confirm against the installed version; support changes between releases.

| Library | Zarr v2 (OME-Zarr ≤0.4) | Zarr v3 (OME-Zarr ≥0.5) | Sharding | Notes |
| --- | --- | --- | --- | --- |
| zarr-python 2.x | read/write | not the released v3 format | no | Experimental v3 support in late 2.x followed an older draft; do not rely on it. |
| zarr-python ≥3 | read/write (`zarr_format=2`) | read/write | yes | Needs a recent Python (3.11+ for 3.0); older bundled interpreters cannot upgrade. |
| tensorstore | `zarr` driver | `zarr3` driver | yes | Wheels exist for older Pythons in older releases. Useful as a reader where zarr-python 3 cannot be installed. |
| ome-zarr-py, ngff-zarr, napari-ome-zarr | yes | version-dependent | version-dependent | Check the release notes for OME-Zarr 0.5 support. |
| Java (N5/zarr readers, Fiji, BigDataViewer, MoBIE) | yes | version-dependent | version-dependent | Check the installed plugin version. |
| neuroglancer | yes | yes | yes | |

## Code differences that break silently or loudly

| Topic | zarr-python 2.x | zarr-python ≥3 |
| --- | --- | --- |
| Group type check | `zarr.hierarchy.Group` (also `zarr.Group`) | `zarr.hierarchy` removed; use `zarr.Group` |
| Create array | `zarr.create(..., chunks=, compressor=)` | `zarr.create_array(..., chunks=, shards=, compressors=)` |
| `arr.chunks` on a sharded array | n/a | **inner** chunk shape |
| Write unit | `arr.chunks` | `arr.shards` if not `None`, else `arr.chunks` |
| Metadata files | `.zarray`, `.zattrs`, `.zgroup` | `zarr.json` (v3); v2 files when `zarr_format=2` |

Alignment checks for parallel writes must use the **write unit**:

```python
write_grid = getattr(arr, "shards", None) or arr.chunks
```

Validating tiles against `arr.chunks` on a sharded zarr-python 3 array passes
while tiles still split shards, which lets concurrent writers corrupt data.

## When a consumer cannot read the planned layout

In order of preference:

1. **Change the reader** in that environment (e.g. tensorstore `zarr3` when zarr-python 3 cannot be installed).
2. **Move the read** to a step that runs in a compatible environment and hand over the
   tile (e.g. `.npy`). This costs one extra write and read per tile.
3. **Write unsharded Zarr v3**, if the reader handles v3 but not sharding, or
   **Zarr v2 / OME-Zarr 0.4** if it handles only v2. This costs more files.
4. **Keep a separate compatible copy** for that consumer. This doubles storage.

Report the choice and its cost; never assume compatibility from the tool's name alone.