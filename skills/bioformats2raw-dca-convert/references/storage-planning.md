# DCA v0.3 chunk and shard planning

Read before recommending settings. Rules below were checked against DCA commit
`31160de17c9370f953baaebe3e8ef00e2749ec4a` and bioformats2raw commit
`8494bfff993d860ef2d1c7f9782e270765da9c21`. The DCA draft and tool capabilities
can change; inspect the installed versions and retain their revisions.

## Thresholds and interpretations

Let `A=(T,C,Z,Y,X)`, inner chunk `K`, outer shard `S`, and `b` be dtype bytes.
Compute with integers:

```text
array_bytes = product(A) * b
chunk_bytes = product(K) * b
shard_bytes = product(S) * b
per_channel_array_bytes = T * Z * Y * X * b
per_channel_chunk_bytes = Kt * Kz * Ky * Kx * b
shard_count = product(ceil(Ai / Si))
chunks_per_shard = product(Si / Ki)
```

For sharded Zarr v3, the outer `chunk_grid.configuration.chunk_shape` is `S`;
`sharding_indexed.configuration.chunk_shape` is `K`. Inspect compression inside
the sharding codec. Do not mistake the outer grid for inner chunks. `Si` must
be a positive integer multiple of `Ki` in every dimension. An array dimension
need not divide evenly into a shard; edge shards may contain partial data.
The writer's restrictions and clamping still need to be checked.

| Rule | Threshold / scope |
| --- | --- |
| Base inner chunk MUST | >=524,288 bytes (512 KiB), except the full per-channel small-array case below. |
| Base inner chunk SHOULD | >=1,048,576 bytes (1 MiB). |
| Spatial chunk SHOULD | Z/Y/X near 128/128/128; T and C preferably 1. Adapt for shallow images. |
| Shard MUST | >=1,073,741,824 bytes (1 GiB) if the full array, including C, is >=1 GiB; <5,497,558,138,880 bytes (5 TiB). |
| Shard SHOULD | <5,368,709,120 bytes (5 GiB), spatial extents <=2048, T extent >=16 when the array has at least 16 timepoints. |
| Compression MUST | zstd, LZ4, or Blosc; apply compression to inner chunks when sharding. |
| Compression SHOULD | Integers: native zstd, level <=3; floats: byte shuffle then native zstd, level <=3. |

**Documentation/implementation distinction:** the array document describes the
chunk minimum on a uniform uint8 basis; the pinned validator uses the actual
dtype itemsize. Show both voxel count and actual bytes. Prefer at least 524,288
voxels when feasible, as well as >=1 MiB actual bytes, to satisfy either
interpretation. Do not halve the voxel target for uint16 without disclosing
this distinction. Examples in upstream prose do not replace arithmetic.

The pinned validator allows a base chunk below the minimum when its
T*Z*Y*X volume covers the complete per-channel array, excluding C from that
comparison. Use one chunk per channel for genuinely small arrays; do not
combine channels merely to reach the byte threshold or pad giant chunks to
game the exception.

The pinned validator checks both chunk-byte and shard-byte limits only at
level 0, and skips shard checks if no shard codec exists. The v0.3 document
explicitly relaxes chunk sizes for coarser levels but does not similarly
scope all shard requirements. Plan compliant shards at every level where
applicable and re-evaluate each array's bytes. Do not omit sharding merely to
bypass a validator check. The code warns above 5 GiB, while the prose says
smaller than 5 GB; choose strictly below 5 GiB.

## Derive a candidate

1. Start inner `K=(1,1,min(Z,128),min(Y,128),min(X,128))`.
   If too small, increase T by factors of two within T; then grow Y/X by
   factors of two within their extents. Aim for the recommended target when
   practical, and stop once the full per-channel image is covered. Preserve
   C=1. Recalculate when adapting a non-power-of-two extent. If T growth is
   unnecessary and a spatial-only candidate meets MUST requirements, offer
   it as a direct-converter alternative with its tradeoffs.
2. Build `S` from integer multiples of `K`. Prefer C=1, T>=16 if available,
   and spatial extents covering the image up to 2048. Align extents to `K`;
   do not blindly clip an aligned shard to a non-divisible image extent.
   For a writer allowing partial edge shards, round up to a chunk multiple
   when useful; otherwise choose a supported lower multiple or revise `K`.
3. If `array_bytes >=1 GiB`, grow shard extents until `shard_bytes >=1 GiB`.
   Prefer increasing T and spatial coverage; use C>1 only if needed and
   supported. Keep below 5 GiB where possible and always below 5 TiB.
   A large multi-channel array can trigger the 1 GiB rule even when a single
   channel/timepoint is small. In that case, a spatial-only converter may
   be unable to write a sufficiently large shard.
4. Reconcile the candidate with available writer controls, edge clamping,
   actual memory limits, and every pyramid level. If no feasible direct
   candidate exists, recommend a staged rewrite. Do not silently shrink
   shards below the required threshold. Record remaining SHOULD warnings.

## Worked examples

All tuples are TCZYX. These examples describe base-level layouts, not complete
DCA metadata or an assurance of full validation.

| dtype; array A | Inner K; actual bytes | Outer S; actual bytes | Rationale |
| --- | --- | --- | --- |
| uint16; (1,1,128,2048,2048) | (1,1,128,128,128); 4 MiB | (1,1,128,2048,2048); 1 GiB | Array is 1 GiB. Spatial-only direct conversion can satisfy the size rules. |
| uint16; (1024,2,1,1024,1024) | (32,1,1,128,128); 1 MiB | (512,1,1,1024,1024); 1 GiB | Array is 4 GiB. Requires a writer with time chunking/sharding; four shards total. |
| uint8; (100,1,1,512,512) | (64,1,1,128,128); 1 MiB | (64,1,1,512,512); 16 MiB | Array is 25 MiB, so no 1 GiB shard minimum; two partial/full edge shards. Requires time controls. |
| uint16; (1,3,1,256,256) | (1,1,1,256,256); 128 KiB | (1,1,1,256,256); 128 KiB | Small-image exception: one complete chunk per channel, three shards. |
| float32; (1,1,32,512,512) | (1,1,32,128,128); 2 MiB | (1,1,32,512,512); 32 MiB | Preserve floats; report dtype recommendation warning. Verify byte shuffle support or use a subsequent rewrite. |

## Sources

- [Pinned array requirements](https://github.com/chanzuckerberg/dynamic-cell-atlas-specs/blob/31160de17c9370f953baaebe3e8ef00e2749ec4a/docs/v0.3/array-standard.rst).
- [Pinned validator byte arithmetic and exceptions](https://github.com/chanzuckerberg/dynamic-cell-atlas-specs/blob/31160de17c9370f953baaebe3e8ef00e2749ec4a/helpers/src/dca_helpers/validation/versions/v0_1/models.py) (shared by later versions).
- [Pinned converter chunk/shard controls and clamping](https://github.com/glencoesoftware/bioformats2raw/blob/8494bfff993d860ef2d1c7f9782e270765da9c21/src/main/java/com/glencoesoftware/bioformats2raw/Converter.java).
