# /// script
# requires-python = ">=3.11"
# dependencies = ["zarr>=3.0.8", "numpy"]
# ///
"""Write small good and deliberately broken OME-Zarr fixtures for inspect-ome-zarr.

    uv run tests/inspect-ome-zarr/make_fixtures.py OUT_DIR

Each fixture is named for what it should trigger; stores.toml lists the
expected finding codes. Fixtures are generated, not committed.
"""
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import zarr
from zarr.codecs import BloscCodec, ZstdCodec

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "fixtures")


def axes(spec, units=None):
    units = units or {}
    t = {"t": "time", "c": "channel"}
    out = []
    for n in spec:
        a = {"name": n, "type": t.get(n, "space")}
        u = units.get(n, "micrometer" if a["type"] == "space" else "second" if n == "t" else None)
        if u:
            a["unit"] = u
        out.append(a)
    return out


def pyramid(shape, spec, n_levels, factor=2):
    """Shapes and scales downsampling spatial axes only."""
    shapes, scales = [], []
    base = [1.0 if n in "tc" else (2.0 if n == "z" else 0.5) for n in spec]
    for k in range(n_levels):
        f = factor ** k
        shapes.append([s if n in "tc" else max(1, s // f) for s, n in zip(shape, spec)])
        scales.append([b if n in "tc" else b * f for b, n in zip(base, spec)])
    return shapes, scales


def ms(spec, scales, paths=None, units=None, translations=None, version=None):
    paths = paths or [str(i) for i in range(len(scales))]
    ds = []
    for i, (p, s) in enumerate(zip(paths, scales)):
        ct = [{"type": "scale", "scale": s}]
        if translations:
            ct.append({"type": "translation", "translation": translations[i]})
        ds.append({"path": p, "coordinateTransformations": ct})
    m = {"axes": axes(spec, units), "datasets": ds, "name": "img"}
    if version:
        m["version"] = version
    return m


def write_image(root, spec, shape, n_levels=3, fmt=2, chunks=None, dtype="uint16",
                compressor="zstd", label=False, shards=None, skip_levels=(), shapes=None,
                scales=None, mscale=None, omero=True, units=None, translations=None):
    g = zarr.open_group(str(root), mode="w", zarr_format=fmt)
    s_shapes, s_scales = pyramid(shape, spec, n_levels)
    shapes, scales = shapes or s_shapes, scales or s_scales
    rng = np.random.default_rng(0)
    for k, shp in enumerate(shapes):
        if k in skip_levels:
            continue
        ch = [min(c, s) for c, s in zip(chunks or [1 if n in "tc" else 32 for n in spec], shp)]
        kw = {}
        if fmt == 2:
            kw["compressors"] = None if compressor is None else [{"zstd": {"id": "zstd", "level": 3}, "blosc": {"id": "blosc", "cname": "zstd", "clevel": 5, "shuffle": 1}}[compressor]]
        else:
            kw["compressors"] = None if compressor is None else [ZstdCodec(level=3) if compressor == "zstd" else BloscCodec(cname="zstd", clevel=5)]
            if shards:
                kw["shards"] = [min(s, x) if True else x for s, x in zip(shards, shp)]
                kw["shards"] = [max(c, (x // c) * c) for x, c in zip(kw["shards"], ch)]
        a = g.create_array(str(k), shape=shp, chunks=ch, dtype=dtype, fill_value=0, **kw,
                           **({"dimension_names": list(spec)} if fmt == 3 else {}))
        if label:
            data = (rng.integers(0, 6, size=shp)).astype(dtype)
        else:
            data = (rng.normal(500, 100, size=shp)).clip(0).astype(dtype)
        a[...] = data
    m = ms(spec, mscale or scales, units=units, translations=translations, version="0.4" if fmt == 2 else None)
    attrs = {"multiscales": [m]}
    if label:
        attrs["image-label"] = {"colors": [{"label-value": i, "rgba": [255, 0, 0, 255]} for i in range(1, 6)],
                                "source": {"image": "../../"}}
        if fmt == 2:
            attrs["image-label"]["version"] = "0.4"
    if omero and not label and "c" in spec:
        nc = shape[spec.index("c")]
        attrs["omero"] = {"channels": [{"label": f"ch{i}", "color": ["00FF00", "FF00FF", "FFFFFF"][i % 3], "active": True,
                                        "window": {"start": 300, "end": 900, "min": 0, "max": 65535}} for i in range(nc)]}
    set_attrs(g, attrs, fmt)
    return g


def set_attrs(g, attrs, fmt):
    if fmt == 3:
        g.attrs.update({"ome": {"version": "0.5", **attrs}})
    else:
        g.attrs.update(attrs)


def add_labels(root, fmt, names, image_shape, spec, dtype="uint32"):
    lg = zarr.open_group(str(root / "labels"), mode="w", zarr_format=fmt)
    set_attrs(lg, {"labels": names}, fmt)
    lspec = "".join(n for n in spec if n != "c")
    lshape = [s for s, n in zip(image_shape, spec) if n != "c"]
    for n in names:
        write_image(root / "labels" / n, lspec, lshape, fmt=fmt, dtype=dtype, label=True)


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    # 1. clean 0.4 image with omero + labels
    p = OUT / "good_v04_labels.zarr"
    write_image(p, "czyx", [2, 16, 128, 128], n_levels=3)
    add_labels(p, 2, ["cells"], [2, 16, 128, 128], "czyx")

    # 2. clean 0.5 image, sharded, with labels
    p = OUT / "good_v05_sharded.zarr"
    write_image(p, "tczyx", [2, 2, 16, 128, 128], n_levels=3, fmt=3, chunks=[1, 1, 16, 32, 32], shards=[1, 1, 16, 128, 128])
    add_labels(p, 3, ["nuclei"], [2, 2, 16, 128, 128], "tczyx")

    # 3. non-UDUNITS units
    write_image(OUT / "bad_units.zarr", "tczyx", [2, 1, 8, 64, 64], units={"t": "sec", "z": "um", "y": "µm", "x": "microns"})

    # 4. scales that don't match shapes (level 1 claims 3x, level 2 left at base)
    shapes, scales = pyramid([1, 16, 128, 128], "czyx", 3)
    scales[1] = [1.0, 6.0, 1.5, 1.5]
    scales[2] = [1.0, 2.0, 0.5, 0.5]
    write_image(OUT / "bad_scales.zarr", "czyx", [1, 16, 128, 128], scales=scales)

    # 5a. a level listed in datasets but not written
    write_image(OUT / "missing_level_array.zarr", "czyx", [1, 16, 256, 256], n_levels=4, skip_levels=(2,))

    # 5b. a level silently dropped from the pyramid (0,1,3 written as 0,1,2)
    shapes, scales = pyramid([1, 16, 256, 256], "czyx", 4)
    del shapes[2], scales[2]
    write_image(OUT / "dropped_level.zarr", "czyx", [1, 16, 256, 256], shapes=shapes, scales=scales)

    # 6. assorted problems: xyzc order, uncompressed, tiny chunks spanning channels, omero count wrong, float labels
    p = OUT / "bad_misc.zarr"
    g = write_image(p, "czyx", [3, 8, 64, 64], n_levels=2, chunks=[3, 4, 8, 8], compressor=None)
    a = dict(g.attrs)
    a["multiscales"][0]["axes"] = list(reversed(a["multiscales"][0]["axes"]))
    a["omero"]["channels"] = a["omero"]["channels"][:2]
    g.attrs.put(a)
    add_labels(p, 2, ["seg"], [3, 8, 64, 64], "czyx", dtype="float32")

    # 7. 0.4 translations in voxels (the light-sheet bug)
    shapes, scales = pyramid([1, 32, 128, 128], "czyx", 4)
    tr = [[0, 0, 0, 0]] + [[0] + [(2 ** k - 1) / 2] * 3 for k in range(1, 4)]
    write_image(OUT / "translation_voxels.zarr", "czyx", [1, 32, 128, 128], n_levels=4, translations=tr)

    # 8. HCS plate with a well missing its metadata, uneven fields
    p = OUT / "plate_missing_wells.zarr"
    pg = zarr.open_group(str(p), mode="w", zarr_format=2)
    rows, cols = ["A", "B"], ["1", "2", "3"]
    wells = [("A", "1"), ("A", "2"), ("A", "3"), ("B", "1"), ("B", "2")]
    pg.attrs.update({"plate": {"version": "0.4", "name": "test plate", "rows": [{"name": r} for r in rows],
                               "columns": [{"name": c} for c in cols], "field_count": 2,
                               "wells": [{"path": f"{r}/{c}", "rowIndex": rows.index(r), "columnIndex": cols.index(c)} for r, c in wells]}})
    for i, (r, c) in enumerate(wells):
        if (r, c) == ("B", "2"):
            continue  # listed but never written
        nf = 1 if (r, c) == ("A", "3") else 2
        wg = zarr.open_group(str(p / r / c), mode="w", zarr_format=2)
        wg.attrs.update({"well": {"version": "0.4", "images": [{"path": str(f)} for f in range(nf)]}})
        for f in range(nf):
            write_image(p / r / c / str(f), "czyx", [2, 1, 64, 64], n_levels=2)

    # 9. bioformats2raw collection with two series and OME/METADATA.ome.xml
    p = OUT / "bf2raw_collection.zarr"
    cg = zarr.open_group(str(p), mode="w", zarr_format=2)
    cg.attrs.update({"bioformats2raw.layout": 3})
    og = zarr.open_group(str(p / "OME"), mode="w", zarr_format=2)
    og.attrs.update({"series": ["0", "1"]})
    (p / "OME" / "METADATA.ome.xml").write_text('<?xml version="1.0"?><OME/>')
    write_image(p / "0", "czyx", [2, 8, 64, 64], n_levels=2)
    write_image(p / "1", "czyx", [2, 8, 32, 32], n_levels=2)

    # 10. zip store (copy of fixture 1, zipped with a top-level folder)
    shutil.make_archive(str(OUT / "good_v04_labels.zarr"), "zip", OUT, "good_v04_labels.zarr")

    # 11. 0.5 metadata written into a Zarr v2 store
    g = write_image(OUT / "version_mismatch.zarr", "czyx", [1, 8, 64, 64], n_levels=2)
    a = dict(g.attrs)
    a["multiscales"][0]["version"] = "0.5"
    g.attrs.put(a)

    print(json.dumps(sorted(p.name for p in OUT.iterdir()), indent=1))


if __name__ == "__main__":
    main()
