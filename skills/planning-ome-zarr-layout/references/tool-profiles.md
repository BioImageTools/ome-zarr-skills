# Tool, storage and writer profiles

Starting points only. Behaviour changes between releases: confirm against the
installed version's docs or help, and prefer measured memory and runtime. Tag
anything not confirmed as `(inferred)` in the plan.

## Consumers

| Tool | Unit of work | Layout implications |
| --- | --- | --- |
| Cellpose 2D (≤3, Cellpose-SAM) | Planes or YX tiles; the network runs on fixed-size patches (224 px in ≤3, 256 px in Cellpose-SAM) in batches | GPU memory scales mainly with `batch_size`, not tile size; host RAM scales with tile voxels (image, flows, cell probability, masks). Flat inner chunks (1–8 z, 256–1024 YX). Halo ≈ 1–2 cell diameters. |
| Cellpose 3D | Runs the 2D network on XY, ZY and ZX slices and combines flows | Host RAM per voxel is several times the 2D case, and higher when `anisotropy` resamples z. Needs a halo in z too; consider taller tiles in z so fewer cells are cut. |
| ilastik pixel classification | CPU; computes filter features per voxel, then a random forest | Memory ≈ voxels × n_features × 4 B (float32) plus overhead; cap with `LAZYFLOW_TOTAL_RAM_MB`, threads with `LAZYFLOW_THREADS`. Halo grows with the largest filter σ. No GPU needed. When driven from Python with an in-memory array (e.g. headless `PreloadedArrayDatasetInfo`), ilastik never opens the store: the compatibility check applies to the library that reads the tile in that Python environment (often ilastik's bundled Python). Otherwise check that the installed ilastik reads OME-Zarr 0.5 / sharding. |
| Ultrack | Reads foreground/contour (or label) arrays one timepoint at a time; links adjacent timepoints | Inner chunk T=1; spatial chunk shape matters little if whole frames are read. Do not shard along T for arrays written per timepoint by parallel jobs. `(inferred)`: check the installed version's I/O. |
| napari (napari-ome-zarr, ome-zarr-py, ngff-zarr readers) | Loads the visible plane(s) at the level matching zoom | Flat inner chunks (1–8 z, ≥256 YX) and a full pyramid. Reading sharded arrays needs a zarr-python ≥3 backend. |
| neuroglancer | 3D chunk requests per visible region and level | Supports Zarr v3 and sharding; prefers small near-isotropic chunks (~64³–128³ voxels). |
| Fiji / BigDataViewer / MoBIE (n5-zarr) | Block-wise | Zarr v3 / sharding support depends on version: check. |
| dask `map_blocks` / `map_overlap`, xarray | Dask chunk = unit of compute | Dask chunks = whole shards when writing; a multiple of the inner chunk when reading. `map_overlap` depth = halo. |
| zarr-python 2.x tools | Chunk-wise | Zarr v2 only; cannot read sharded v3. See [Zarr compatibility](zarr-compatibility.md). |
| tensorstore | Chunk- and shard-aware | Reads and writes sharded v3. Concurrent writers in separate processes still must not share a shard. |

## Storage backends

| Backend | What matters |
| --- | --- |
| HPC parallel/network filesystem (GPFS, Lustre, BeeGFS, NFS) | Large sequential requests (≥256 KiB–1 MiB) and few files; many small files load the metadata servers. Sharding mainly helps file count. |
| Object store / HTTP (S3, GCS) | Each inner-chunk read is a range request, plus reading the shard index. Keep compressed inner chunks ≥ ~1 MiB. `index_location` decides whether the index sits at the start or the end of the shard. |
| Local NVMe | Almost any reasonable layout performs well. Optimise for the eventual destination instead. |
| Transfer (rclone, multipart upload) | Fewer, larger files transfer faster than many small ones. Shards of 0.5–5 GiB are fine. |

## Writer options

Confirm names and semantics with the installed version's help before use.

| Writer | Inner chunk | Shard | Notes |
| --- | --- | --- | --- |
| zarr-python ≥3 | `create_array(chunks=K)` | `create_array(shards=S)` | Compression via `compressors=`; applied to inner chunks when sharded. |
| ngff-zarr | chunks on `to_multiscales` | `chunks_per_shard` on `to_ngff_zarr` | Shard given as a chunk count, not voxels. |
| zarrsmith | `--chunk_size` (or `--max_size`) | `--shards auto` with `--shard_target_mb`, `--shard_exclude_axes`; or an explicit shape | Explicit shard shapes are rounded to the nearest chunk multiple per level; writes one shard per dask block. |
| bioformats2raw | `--tile-width/--tile-height/--chunk-depth` | `--shard-width/--shard-height/--shard-depth` (pixels) | Spatial only (T=C=1); clamps to array size and can drop sharding when divisibility fails. See `bioformats2raw-dca-convert`. |
| tensorstore | `sharding_indexed` codec `chunk_shape` | outer `chunk_grid` | Write whole shards per transaction or task. |