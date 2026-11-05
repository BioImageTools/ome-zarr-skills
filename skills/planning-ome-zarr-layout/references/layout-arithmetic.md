# Layout arithmetic

Use integers. Tuples follow the array's axis order (e.g. TCZYX). Let array
shape `A`, inner chunk `K`, shard `S`, dtype bytes `b`.

```text
array_bytes      = product(A) * b
chunk_bytes      = product(K) * b
shard_bytes      = product(S) * b
shard_count      = product(ceil(A_i / S_i))
chunks_per_shard = product(S_i / K_i)          # S_i must be a multiple of K_i
files_per_level  = shard_count + 1             # + zarr.json; unsharded: chunk count + 1
```

In Zarr v3 array metadata, the outer `chunk_grid.configuration.chunk_shape` is
`S` and `sharding_indexed.configuration.chunk_shape` is `K`. Without a
`sharding_indexed` codec, the outer grid is the chunk and every chunk is a file.

## Padding

Partial inner chunks at array edges are stored at full size. Uncompressed,
the stored bytes per level are about `product(ceil(A_i / K_i) * K_i) * b`. Compression
makes the padding nearly free. A large gap between `du` and `array_bytes` on an
uncompressed store usually comes from this padding.

## Tiles and halo

For an interior tile whose core length `L` is a multiple of `k` and starts on
the chunk grid, with halo `h` per side, along one axis:

```text
needed_read  = L + 2*h
actual_read  = L + 2*ceil(h / k) * k           # whole chunks
amplification(axis) = actual_read / L
amplification(tile) = product over tiled axes
halo_compute_overhead = product((L + 2*h) / L) - 1
tiles = product(ceil(A_i / L_i))               # over tiled axes
```

Example: `L=2560, h=64, k=512` gives 3584/2560 = 1.4 per axis, about 1.96 in YX;
with `k=256` it is 1.2 per axis, about 1.44. This only matters when reads are a
noticeable share of per-tile time.

## Memory per job

```text
tile_voxels_max ≈ 0.7 * job_memory_bytes / bytes_per_voxel(tool)
writer_memory   ≈ concurrent_workers * shard_bytes   # uncompressed shard buffers
```

Get `bytes_per_voxel` by measuring one tile (`sacct --format=MaxRSS`,
`/usr/bin/time -v`, `nvidia-smi`); profile values are rough starting points.

## Inspect a store (stdlib only)

```python
import json, math, pathlib, sys
Z = pathlib.Path(sys.argv[1])
root = json.loads((Z / "zarr.json").read_text())
ome = root["attributes"]["ome"]
ms = ome["multiscales"][0]
print("zarr_format:", root.get("zarr_format"), "ome.version:", ome.get("version"),
      "axes:", [a["name"] for a in ms["axes"]])
for ds in ms["datasets"]:
    p = Z / ds["path"]
    m = json.loads((p / "zarr.json").read_text())
    b = {"uint8":1,"int8":1,"uint16":2,"int16":2,"uint32":4,"int32":4,"float32":4,"uint64":8,"int64":8,"float64":8}[m["data_type"]]
    outer = m["chunk_grid"]["configuration"]["chunk_shape"]
    shard = next((c["configuration"] for c in m["codecs"] if c["name"] == "sharding_indexed"), None)
    inner = shard["chunk_shape"] if shard else outer
    codecs = [c["name"] for c in (shard["codecs"] if shard else m["codecs"])]
    n = math.prod(math.ceil(a / s) for a, s in zip(m["shape"], outer))
    files = sum(1 for f in p.rglob("*") if f.is_file())
    disk = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    print(f"{ds['path']}: shape={m['shape']} {m['data_type']} inner={inner} "
          f"({math.prod(inner)*b/2**20:.1f} MiB) "
          + (f"shard={outer} ({math.prod(outer)*b/2**30:.2f} GiB) x{n} " if shard else f"UNSHARDED x{n} chunks ")
          + f"codecs={codecs} index={shard.get('index_location','end') if shard else '-'} "
          f"files={files} disk={disk/2**30:.2f} GiB data={math.prod(m['shape'])*b/2**30:.2f} GiB")
```

For Zarr v2 (`.zarray`), read `shape`, `chunks`, `dtype`, `compressor`; there is no sharding.