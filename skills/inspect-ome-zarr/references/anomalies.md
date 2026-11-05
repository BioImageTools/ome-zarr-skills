# Finding codes

Every finding the script can emit, grouped by area. **Basis** says how sure
the check is:

- **rule**: a requirement of the 0.4/0.5 rules encoded in the script. Confirm
  wording for the store's version with `reading-ome-zarr-spec` before quoting.
- **consistency**: metadata contradicts itself or the arrays; true in any version.
- **heuristic**: a pattern that is usually a mistake. Say "looks like".
- **advice**: performance or usability, not correctness.

In explanations, translate the code into consequences: what breaks, in which tool,
and the one-line fix.

## Version and format

| Code | Sev | Basis | Meaning / what to tell the user |
|---|---|---|---|
| `VERSION_MISSING` | warning | rule | No version field. Readers guess; some refuse. Add the version the writer targets. |
| `VERSION_UNCHECKED` | info | — | Version outside 0.4/0.5; axis-order and unit checks were skipped or may not apply. Fetch that version's spec. |
| `VERSION_FORMAT_MISMATCH` | error | rule | 0.4 metadata in Zarr v3, or 0.5 in Zarr v2. Readers that dispatch on version will fail. |
| `VERSION_VS_REPO` | info | — | Store version differs from `docs/agents/ome-zarr.md` target. Conversion may be needed before mixing. |
| `NOT_OME` | warning | — | Root has no OME metadata. Usually the wrong path (pointed at a parent or a level). |

## Axes and units

| Code | Sev | Basis | Meaning |
|---|---|---|---|
| `AXES_MISSING` | error | rule | No `axes`; readers can't tell z from channel. |
| `AXES_NDIM_MISMATCH` | error | consistency | Number of axes ≠ array dimensions. Viewers misinterpret or crash. |
| `AXES_DUPLICATE` | error | rule | Two axes share a name. |
| `AXES_COUNT` / `AXES_SPACE_COUNT` / `AXES_TYPE_REPEAT` | error | rule | Too many/few axes, wrong number of space axes, repeated time/channel. |
| `AXES_ORDER` | error | rule | Not time → channel/custom → space. Viewers put channels on the wrong slider. Fix by transposing data *and* axes; renaming alone corrupts meaning. |
| `AXES_CUSTOM_TYPE` | info | — | A type other than space/time/channel. Allowed, often ignored by viewers. |
| `AXES_SPACE_NAMES` | info | advice | Space axes not called z,y,x. Legal, but many tools assume it. |
| `UNIT_MISSING` | warning | advice | Space/time axis without a unit: pixel sizes are unitless. |
| `UNIT_NONSTANDARD` | warning | rule | `um`, `µm`, `microns`, `sec` etc. Viewers may show no scale bar or treat sizes as unitless. The fix names the correct UDUNITS-2 word. |
| `UNIT_ON_CHANNEL` | info | heuristic | Channel axis carries a unit; usually a copy-paste error. |
| `DIMENSION_NAMES_MISMATCH` | warning | consistency | Zarr v3 `dimension_names` disagree with OME axes. Tools reading one or the other will disagree. |

## Pyramid and coordinate transformations

| Code | Sev | Basis | Meaning |
|---|---|---|---|
| `DATASETS_MISSING` | error | rule | `multiscales.datasets` empty. |
| `LEVEL_MISSING` | error | consistency | A listed level has no array. Viewers fail when zooming to it. |
| `LEVEL_NDIM` | error | consistency | Levels differ in dimensionality. |
| `LEVEL_DTYPE_MIXED` | warning | consistency | Levels have different dtypes; contrast changes on zoom. |
| `LEVEL_ORDER` | error | rule | A later level is larger than an earlier one; must go high → low resolution. |
| `LEVEL_GAP` | warning | heuristic | One step downsamples ≥ ~2× more than the smallest step (e.g. 2,2,4). Often a dropped level; harmless if deliberate. |
| `CT_SCALE_MISSING` / `CT_LENGTH` / `CT_SCALE_NONPOSITIVE` / `CT_ORDER` | error | rule | Each level needs one scale (positive, one value per axis), optional translation after it. |
| `SCALE_SHAPE_MISMATCH` | error | consistency | `scale_k / scale_0` disagrees with `shape_0 / shape_k` by more than one pixel. Levels won't overlay; physical sizes at that level are wrong. Recompute scales from shapes. |
| `TRANSLATION_IN_VOXELS` | warning | heuristic | Every per-level translation equals `(factor − 1)/2` in level-0 voxels rather than `(scale_k − scale_0)/2` in physical units. Typical of writers that compute pixel-centre offsets before applying the pixel size. Effect: levels drift relative to each other by up to half a level-0 voxel × factor. Fix: multiply translations by the level-0 scale. |
| `MULTISCALE_EXTRA_KEYS` | info | advice | Unknown keys inside a multiscales entry. Ignored by readers; strict validators may reject. |
| `MULTISCALES_MULTIPLE` | info | — | More than one multiscales entry; only the first was described. |

## Storage

| Code | Sev | Basis | Meaning |
|---|---|---|---|
| `NO_COMPRESSION` | warning | advice | No compressor. Expect 2–5× more storage and transfer for typical microscopy. |
| `CHUNK_TINY` | warning | advice | Level-0 chunks < 64 KiB uncompressed and ≥ 100 of them. Many small objects: slow listing, high request overhead on S3/GCS, file-count quotas on HPC. Rechunk or shard. |
| `CHUNK_HUGE` | warning | advice | Chunks > 256 MiB uncompressed. Any read pulls the whole chunk; memory spikes. |
| `SHARD_HUGE` | info | advice | Shards > 4 GiB. Fine to read; rewriting needs whole shards. |
| `SHARD_NOT_MULTIPLE` | error | rule | Shard shape not divisible by inner chunk shape (Zarr v3 requirement). |
| `CHUNK_SPANS_CHANNEL` / `CHUNK_SPANS_TIME` | warning | advice | Chunks cover several channels/timepoints; showing one channel reads all of them. Rechunk to 1 along that axis. |
| `V2_EMPTY_FILTERS` | info | consistency | `"filters": []` in `.zarray` instead of `null`. zarr-python 3 warns and plans to reject it. |

## Channels (omero)

| Code | Sev | Basis | Meaning |
|---|---|---|---|
| `OMERO_MISSING` | info | advice | No channel names/colours/windows; viewers show grey with auto contrast. Offer a window from the sample percentiles, tagged inferred. |
| `OMERO_CHANNEL_COUNT` | warning | consistency | `omero.channels` length ≠ channel axis length. Names attach to the wrong channels. |

## Labels and tables

| Code | Sev | Basis | Meaning |
|---|---|---|---|
| `LABELS_UNLISTED` | warning | rule | `labels/` group without a `labels` list; readers won't find them. |
| `LABEL_MISSING` | error | consistency | A listed label has no multiscales metadata. |
| `LABEL_FLOAT` | warning | rule/advice | Float label dtype. Ids must be integers; float labels break equality lookups and colormaps. |
| `LABEL_NON_INTEGER` | error | consistency | Sampled label values have fractions; probably an intensity image saved as a label. |
| `LABEL_SHAPE_MISMATCH` | warning | heuristic | Label level-0 spatial shape ≠ image level-0 shape. Fine if scales map it (e.g. 2D label of a max projection), otherwise misaligned overlay. Mention which axes differ. |

Tables are only reported (name, encoding, region); no checks.

## Plates and collections

| Code | Sev | Basis | Meaning |
|---|---|---|---|
| `PLATE_MISSING_WELLS` | error | consistency | Wells in `plate.wells` with no well metadata. Plate viewers show holes or fail. |
| `PLATE_PARTIAL` | info | — | Fewer wells than rows × columns. Normal for partial plates; empty positions are in the JSON. |
| `PLATE_FIELDS_UNEVEN` | warning | heuristic | Wells have different field counts; often failed acquisitions. |
| `PLATE_FIELD_COUNT` | warning | consistency | A well has more fields than `plate.field_count`. |
| `PLATE_IMAGE_MISSING` | error | consistency | The representative field has no image metadata. |
| `PLATE_WELLS_CAPPED` | info | — | Over 2000 wells; only the first 2000 checked. |
| `SERIES_MISSING` | error | consistency | bioformats2raw series listed but no image there. |
| `SERIES_CAPPED` | info | — | More series than `--max-images`. |

## Sample

| Code | Sev | Basis | Meaning |
|---|---|---|---|
| `SAMPLE_EMPTY` | info | heuristic | Sampled smallest-level chunks are all fill value. Sparse data, or a pyramid that was never written. |

## Adding a check

Add it in `scripts/inspect_ome_zarr.py` (a `F.add(severity, CODE, path, message, fix)`
call), add a row here, and add a fixture plus `expect` entry in
`tests/inspect-ome-zarr/`.
