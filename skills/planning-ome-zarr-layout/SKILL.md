---
name: planning-ome-zarr-layout
description: Use when choosing or reviewing OME-Zarr chunk and shard shapes based on how downstream tools will read or write the data (tiled segmentation, pixel classification, tracking, viewers, cluster jobs), including pipeline outputs written by parallel jobs.
---

# Planning an OME-Zarr layout for downstream tools

Three units have to nest: the **inner chunk** is the smallest thing a reader
fetches, the **shard** is one file and the smallest thing a writer can safely
write, and the **tile** is one job's unit of compute. Choose them from the
workload first; apply specification rules (e.g. DCA) afterwards as constraints.

Explore, propose, confirm. Values read from data, code or measurements are
facts; values you deduced get an `(inferred)` tag; anything else is `unknown`.
Do not invent tool behaviour: profiles in the references are starting points
to verify against the installed version.

## 1. Read repo preferences

If `docs/agents/ome-zarr.md` exists (written by `/setup-ome-zarr-skills`),
read its `target` and `also_read` versions, `domain` (axes, dtypes, typical size, storage,
chunk/shard preferences, workloads) and Notes. Otherwise infer from the data
and the spec index; never assume which version is current.
Sharding needs Zarr v3 (OME-Zarr 0.5 and later). For 0.4 / Zarr v2 there are no shards:
the chunk is both the read and the write unit, and the shard rules below apply
to chunks. Use the `reading-ome-zarr-spec` skill when spec details matter.

## 2. Inspect the existing array

When data exists, record the Zarr format and `ome.version` of the hierarchy, then per pyramid level: shape, dtype, outer
`chunk_grid` shape, whether `codecs` contains `sharding_indexed` (its
`chunk_shape` is the inner chunk), inner codecs (compression), and
`index_location`. Count files and disk usage per level and compare them with
the expected shard count and data bytes. Excess bytes usually mean padded
partial chunks stored uncompressed. A stdlib-only inspection snippet is in
[layout arithmetic](references/layout-arithmetic.md).

## 3. Collect the workload

Ask for one row per consumer, leading with recommended defaults so the user
can accept in a word:

`tool+version | read/write | library + version that opens the store | Zarr v2 / v3 / sharding support | OME-Zarr versions supported | pyramid level | axes iterated one at a time (t, c, z) | 2D plane / 3D block / whole frame | tile core + halo | memory and GPU per job | concurrent jobs | storage backend`

Starting profiles for common tools: [tool profiles](references/tool-profiles.md).
Prefer measured numbers (peak RSS, GPU memory, seconds per tile) over profiles.

**Compatibility is a hard constraint, checked on two separate levels.** For every consumer, identify the
library that actually opens the store (possibly a script around the tool) and
check its version in the environment the pipeline runs: container, bundled
interpreter or conda env, not the system Python. Then check:

- **Zarr format:** can it read Zarr v3, and sharding? zarr-python 2.x reads and
  writes only Zarr v2. A v2-only consumer decides whether sharding is possible at all,
  so settle it before choosing shapes.
- **OME-Zarr metadata version:** does it understand the store's `ome.version`?
  Versions that share a Zarr format share layout rules but can differ in metadata.
  Writers adding outputs to an existing hierarchy must use that hierarchy's version.

See [Zarr and OME-Zarr compatibility](references/zarr-compatibility.md) for
checks, API differences and fallbacks.

## 4. Choose the tile grid (compute)

Tile size comes from the hardware and the tool, not from the storage layout:

- **Upper bound:** memory per job. `tile_voxels ≈ 0.7 × job_memory / bytes_per_voxel(tool)`.
  For GPU tools check which memory scales with the tile (often host RAM, not GPU memory).
  When the scheduler may assign different GPU types, size for the smallest.
- **Lower bound:** per-job overhead (container start, model load) and halo
  overhead `((core + 2·halo) / core)^d − 1`. Tiles should run for minutes, not seconds.
- Measure one tile at 2–3 sizes before scaling out.
- Make the tile core an integer multiple of the inner chunk (step 5), with the tile grid starting at 0.

## 5. Choose the inner chunk (reads)

- **Singleton** along every axis a consumer iterates one at a time (usually `t` and `c`).
  Grow only along axes that are read together.
- **Size:** about 1–4 MiB uncompressed. Keep compressed chunks at least
  ~0.5–1 MiB on network or parallel filesystems and object stores, where small
  requests are slow.
- **Shape:** plane-wise consumers → flat (few z, large y/x). 3D-block
  consumers → near-isotropic in **physical** units (use voxel sizes, not voxel counts).
- **Halo:** smaller chunks reduce read amplification at tile edges
  (formula in [layout arithmetic](references/layout-arithmetic.md)).
- **Grid:** powers of two that divide the tile core.

If consumers conflict, size the inner chunk for the most frequent or most
expensive reader, report the cost to the others, and consider a separate
processing copy. Rechunking once is usually cheaper than mismatched reads on every run.

## 6. Choose the shard (files and writes)

- **Arrays written by parallel jobs** (pipeline outputs, parallel conversion):
  every concurrent writer must write **whole shards** and no two may touch the same
  shard. Writing part of a shard rewrites the whole shard file, so concurrent
  writers can silently drop each other's data. Simplest rule: shard = tile core
  (or tile core = an integer multiple of the shard). Shard count must be at
  least the number of concurrent writers, and each worker holds roughly one
  uncompressed shard in memory.
- **Read-only inputs:** shard size is about file count, transfer and filesystem
  behaviour. 0.5–2 GiB uncompressed is a reasonable default unless a spec
  sets limits. Grouping along `t` or `c` in the shard is harmless for reads when the
  inner chunk is singleton there, but blocks per-timepoint/per-channel parallel writes.
- **Aligning tiles to shards** (tile core = one or more whole shards) lets each job read whole files.
- **Each pyramid level is separate:** recompute the shard for each level.
  Small levels: one shard per channel/timepoint, or unsharded.
- Put compression inside the sharding codec (on inner chunks).

## 7. Apply constraints, in this order

1. **Spec MUST rules** for the target (for DCA, hand the candidate to `bioformats2raw-dca-convert`).
2. **Zarr format and OME-Zarr version compatibility** of every library that opens the store (step 3). If one
   cannot handle the planned format, apply the fallbacks in
   [Zarr compatibility](references/zarr-compatibility.md) (change the reader,
   move the read, write unsharded v3 or v2, keep a copy) and report the cost.
3. **Workload preferences** from steps 4–6.
4. **Spec SHOULD rules:** follow them unless they conflict with the above; report each departure as a warning.
5. **Writer capabilities:** which axes the writer can chunk/shard, how it rounds
   or clamps shapes, and whether it writes shards in parallel safely. Check the installed help.

## 8. Report

Per level: `shape | dtype | inner chunk (shape, bytes) | shard (shape, bytes) | shard count | chunks per shard`.
For each tiled consumer: `tile core | halo | tiles per channel/timepoint | read amplification | est. memory per job | max parallel writers`.
List warnings, `(inferred)` values, and what to measure. Show how to
express the layout in the chosen writer
([writer options](references/tool-profiles.md#writer-options)).

## 9. Verify after writing

Read the written metadata at every level, compare file counts with the expected
shard counts and disk usage with data bytes, and decode one tile including its halo.
Writers may round, clamp or silently drop sharding. Requested flags do not prove the result.

Worked examples: [worked examples](references/worked-examples.md).

## Common mistakes

- Treating the shard as the read unit. Readers fetch inner chunks; shard shape mostly affects files and writes.
- Growing the inner chunk along `t` or `c` when tools read one timepoint or channel at a time.
- Letting parallel jobs write tiles into a shared shard, or tiles whose cores are off the shard grid.
- Snapping tile or shard sizes to the *nearest* chunk multiple, which can round away from the intended grid. Use exact multiples.
- Deriving tile size from the storage layout instead of from memory and runtime.
- Assuming every reader supports sharded Zarr v3 (e.g. zarr-python 2.x does not).
- Checking the zarr version in the system Python instead of the interpreter the tool actually runs (e.g. a bundled one in a container).
- Validating parallel-write alignment against `arr.chunks`: on a sharded zarr-python 3 array that is the inner chunk; use `arr.shards`.
- Code written for zarr-python 2 (`zarr.hierarchy.Group`, `compressor=`) failing under zarr-python 3, or the reverse.
- Treating the OME-Zarr version and the Zarr format as one check: a reader can handle Zarr v3 arrays but not the store's OME-Zarr metadata version.
- Writing labels or outputs into an existing hierarchy with a different OME-Zarr version than the image.
- Hardcoding the "latest" OME-Zarr version instead of reading the spec index.
- Rechunking for read speed when compute dominates per-tile time.
- Reporting a layout from CLI flags without reading back the written metadata.