# Where the script looks, by version

This is a map of *where* metadata lives so you can follow the script's
reasoning. It is not the spec. For what a field means or requires in a given
version, use the `reading-ome-zarr-spec` skill.

| | 0.1–0.3 | 0.4 | 0.5 | later / unknown |
|---|---|---|---|---|
| Zarr format | v2 | v2 | v3 | read from store |
| Group attributes | `.zattrs` | `.zattrs` | `zarr.json` → `attributes.ome` | either |
| Version field | `multiscales[0].version` | `multiscales[0].version`, `plate.version`, `well.version`, `image-label.version` | `attributes.ome.version` | either |
| Array metadata | `.zarray` | `.zarray` | `zarr.json` (`node_type: array`) | either |
| Axes | absent or list of strings | list of `{name, type, unit}` | same as 0.4 | parsed, rules not applied |
| Per-level transforms | absent | `datasets[].coordinateTransformations` | same as 0.4 | parsed, rules not applied |
| Rules the script enforces | units only | axes order/count, units, transforms | same as 0.4 + v3 sharding | none; emits `VERSION_UNCHECKED` |

Detection order (first hit wins): `zarr.json` at the root → v3 and
`attributes.ome`; otherwise `.zattrs` / `.zgroup` / `.zarray` → v2. Kind:
`plate` → plate; `bioformats2raw.layout` → collection (series from
`OME/series`, else probed `0, 1, 2 …`); `well` → well; `multiscales` → image
(plus `labels/` and `tables/` children); none of these → plain Zarr group.

For a newer version (e.g. one with RFC-5 coordinate systems), the script still
reports shapes, chunks and whatever `multiscales` it can parse, but treat its
axis and transformation findings as unverified and check the spec.
