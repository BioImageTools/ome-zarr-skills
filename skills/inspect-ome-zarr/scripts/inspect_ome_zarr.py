# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "zarr>=3.0.8",
#   "numpy",
#   "fsspec>=2024.6",
#   "s3fs",
#   "gcsfs",
#   "aiohttp",
# ]
# ///
"""Read-only inspection of an OME-Zarr store.

Reads metadata only, plus at most a few chunks from the smallest pyramid level.
Never loads full-resolution pixel data.

    uv run inspect_ome_zarr.py STORE [--detail] [--json | --json-out PATH] [--anon]

STORE: local dir, .zip, http(s)://, s3://, gs://. Exit codes: 0 ok (findings may
exist), 1 store unreadable, 2 bad arguments.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.request
import warnings

warnings.filterwarnings("ignore", module="zarr")
from concurrent.futures import ThreadPoolExecutor

TOOL_VERSION = "0.1.0"
KNOWN_VERSIONS = {"0.4", "0.5"}  # versions whose rules the checks below encode

# Unit names accepted by OME-Zarr 0.4/0.5 axes (UDUNITS-2 names). If the spec
# changes, update here and confirm with the reading-ome-zarr-spec skill.
SPACE_UNITS = {
    "angstrom", "attometer", "centimeter", "decimeter", "exameter", "femtometer",
    "foot", "gigameter", "hectometer", "inch", "kilometer", "megameter", "meter",
    "micrometer", "mile", "millimeter", "nanometer", "parsec", "petameter",
    "picometer", "terameter", "yard", "yoctometer", "yottameter", "zeptometer",
    "zettameter",
}
TIME_UNITS = {
    "attosecond", "centisecond", "day", "decisecond", "exasecond", "femtosecond",
    "gigasecond", "hectosecond", "hour", "kilosecond", "megasecond", "microsecond",
    "millisecond", "minute", "nanosecond", "petasecond", "picosecond", "second",
    "terasecond", "yoctosecond", "yottasecond", "zeptosecond", "zettasecond",
}
UNIT_ALIASES = {
    "um": "micrometer", "µm": "micrometer", "μm": "micrometer", "micron": "micrometer",
    "microns": "micrometer", "microm": "micrometer", "nm": "nanometer",
    "mm": "millimeter", "cm": "centimeter", "m": "meter", "a": "angstrom",
    "å": "angstrom", "pm": "picometer", "s": "second", "sec": "second",
    "seconds": "second", "ms": "millisecond", "us": "microsecond",
    "µs": "microsecond", "ns": "nanosecond", "min": "minute", "minutes": "minute",
    "h": "hour", "hr": "hour", "hours": "hour", "micrometers": "micrometer",
    "nanometers": "nanometer", "millimeters": "millimeter",
}
SHORT_UNIT = {
    "micrometer": "µm", "nanometer": "nm", "millimeter": "mm", "centimeter": "cm",
    "meter": "m", "angstrom": "Å", "picometer": "pm", "second": "s",
    "millisecond": "ms", "microsecond": "µs", "nanosecond": "ns", "minute": "min",
    "hour": "h",
}
MULTISCALE_KEYS = {"version", "name", "axes", "datasets", "coordinateTransformations",
                   "type", "metadata"}
NON_COMPRESSING = {"bytes", "transpose", "crc32c", "endian", "vlen-utf8", "vlen-bytes"}

TINY_CHUNK = 64 * 1024          # uncompressed bytes
HUGE_CHUNK = 256 * 1024 ** 2
HUGE_SHARD = 4 * 1024 ** 3
MAX_WELLS = 2000                # well metadata reads before giving up
MAX_SERIES = 50


# --------------------------------------------------------------------------- findings
class Findings:
    def __init__(self):
        self.items: list[dict] = []

    def add(self, severity, code, path, message, fix):
        self.items.append({"severity": severity, "code": code, "path": path or "/",
                           "message": message, "fix": fix})


# --------------------------------------------------------------------------- store access
class StoreError(Exception):
    pass


def _is_not_found(e):
    return isinstance(e, (FileNotFoundError, KeyError)) or getattr(e, "status", None) == 404


def _is_denied(e):
    name = type(e).__name__
    return (isinstance(e, PermissionError) or getattr(e, "status", None) in (401, 403)
            or name in ("NoCredentialsError", "PartialCredentialsError", "ClientError")
            or "AccessDenied" in str(e) or "403" in str(e)[:40])


class Store:
    def __init__(self, url: str, anon: bool | None):
        import fsspec
        from fsspec.core import url_to_fs

        self.url = url.rstrip("/") if not url.endswith("://") else url
        self.protocol = url.split("://", 1)[0] if "://" in url else "file"
        self.explicit_anon = anon
        self.access = "local" if self.protocol == "file" else None
        self.is_zip = self.url.lower().endswith(".zip")
        self.prefix = ""
        self._fsspec = fsspec
        self._url_to_fs = url_to_fs
        self._open(anon if anon is not None else False)

    def _opts(self, anon):
        if self.protocol in ("s3", "s3a"):
            return {"anon": bool(anon)}
        if self.protocol in ("gs", "gcs"):
            return {"token": "anon"} if anon else {}
        return {}

    def _open(self, anon):
        self.storage_options = self._opts(anon)
        if self.protocol in ("s3", "s3a", "gs", "gcs"):
            self.access = "anonymous" if anon else "credentials"
        elif self.protocol in ("http", "https"):
            self.access = "anonymous (http)"
        if self.is_zip:
            from fsspec.implementations.zip import ZipFileSystem
            self.fs = ZipFileSystem(fo=self.url, target_options=self.storage_options or None)
            self.root = ""
        else:
            self.fs, self.root = self._url_to_fs(self.url, **self.storage_options)

    def full(self, rel):
        parts = [p for p in (self.root, self.prefix, rel) if p]
        return "/".join(s.strip("/") if i else s.rstrip("/") for i, s in enumerate(parts))

    def get_many(self, rels):
        """Return {rel: bytes | None}; raise StoreError on access problems."""
        paths = {self.full(r): r for r in rels}
        try:
            res = self.fs.cat(list(paths), on_error="return")
        except Exception as e:  # some fs raise even with on_error=return
            res = {p: e for p in paths}
        if not isinstance(res, dict):
            res = {next(iter(paths)): res}
        out = {}
        for p, r in paths.items():
            v = res.get(p, FileNotFoundError(p))
            if isinstance(v, Exception):
                if _is_not_found(v):
                    out[r] = None
                elif _is_denied(v):
                    raise StoreError(("denied", p, v))
                else:
                    raise StoreError(("other", p, v))
            else:
                out[r] = v
        return out

    def get(self, rel):
        return self.get_many([rel])[rel]

    def size(self, rel):
        try:
            return self.fs.size(self.full(rel))
        except Exception as e:
            if _is_not_found(e):
                return None
            return -1  # unknown

    def ls(self, rel, cap=1000):
        try:
            items = self.fs.ls(self.full(rel), detail=False)
        except Exception:
            return None
        return [i.rstrip("/").rsplit("/", 1)[-1] for i in items[:cap]]

    def connect(self):
        """Find root metadata; fall back to anonymous access on credential errors."""
        names = ["zarr.json", ".zattrs", ".zgroup", ".zarray"]
        try:
            got = self.get_many(names)
        except StoreError as e:
            kind, path, err = e.args[0]
            if (kind == "denied" and self.explicit_anon is None
                    and self.protocol in ("s3", "s3a", "gs", "gcs")):
                self._open(True)
                self.access = "anonymous (fallback: credentials missing or refused)"
                got = self.get_many(names)
            else:
                raise
        if not any(got.values()) and self.is_zip:
            top = self.ls("")
            if top and len(top) == 1:
                self.prefix = top[0]
                got = self.get_many(names)
        return got

    def zarr_store(self):
        import zarr
        if self.is_zip and self.protocol == "file":
            return zarr.storage.ZipStore(self.url, mode="r"), self.prefix
        if self.protocol == "file":
            return zarr.storage.LocalStore(self.root, read_only=True), ""
        if self.is_zip:
            return None, ""
        return zarr.storage.FsspecStore.from_url(
            self.url, storage_options=self.storage_options, read_only=True), ""


def explain_store_error(e: StoreError, url: str) -> str:
    kind, path, err = e.args[0]
    if kind == "denied":
        msg = f"Access denied reading {path} ({type(err).__name__}: {str(err)[:200]})."
        if url.startswith(("s3://", "s3a://")):
            msg += (" If the bucket is public, retry with --anon; otherwise set "
                    "AWS_PROFILE or AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY (and "
                    "AWS_REGION) and make sure the role can s3:GetObject on this prefix.")
        elif url.startswith(("gs://", "gcs://")):
            msg += (" If the bucket is public, retry with --anon; otherwise run "
                    "`gcloud auth application-default login` or set "
                    "GOOGLE_APPLICATION_CREDENTIALS.")
        else:
            msg += " The server refused the request; check the URL and any required token."
        return msg
    return f"Could not read {path}: {type(err).__name__}: {str(err)[:300]}"


# --------------------------------------------------------------------------- nodes
def read_node(store: Store, rel: str, pref: int | None = None):
    """Read zarr metadata at rel. Returns dict or None."""
    j = lambda *p: "/".join(x for x in (rel, *p) if x)
    names = [j("zarr.json"), j(".zattrs"), j(".zgroup"), j(".zarray")]
    if pref == 3:
        names = names[:1]
    elif pref == 2:
        names = names[1:]
    got = store.get_many(names)
    z3 = got.get(j("zarr.json"))
    if z3:
        m = json.loads(z3)
        attrs = m.get("attributes", {}) or {}
        return {"zarr_format": 3, "node_type": m.get("node_type", "group"), "meta": m,
                "attrs": attrs, "ome": attrs.get("ome", {}) or {}}
    za, zg, zr = (got.get(j(n)) for n in (".zattrs", ".zgroup", ".zarray"))
    if za is None and zg is None and zr is None:
        return None
    attrs = json.loads(za) if za else {}
    meta = json.loads(zr) if zr else (json.loads(zg) if zg else {})
    return {"zarr_format": 2, "node_type": "array" if zr else "group", "meta": meta,
            "attrs": attrs, "ome": attrs}


def ome_version(node):
    ome = node["ome"]
    if node["zarr_format"] == 3 and "version" in ome:
        return str(ome["version"])
    for key in ("multiscales", "plate", "well", "image-label"):
        v = ome.get(key)
        if isinstance(v, list) and v and isinstance(v[0], dict) and "version" in v[0]:
            return str(v[0]["version"])
        if isinstance(v, dict) and "version" in v:
            return str(v["version"])
    return ome.get("version")


# --------------------------------------------------------------------------- arrays
def _itemsize(dtype):
    import numpy as np
    try:
        return np.dtype(dtype).itemsize
    except Exception:
        return None


def _codec_str(c):
    if c is None:
        return None
    if "id" in c:  # zarr v2 numcodecs
        cid = c["id"]
        extra = {k: v for k, v in c.items() if k != "id"}
    else:
        cid = c.get("name")
        extra = c.get("configuration", {}) or {}
    if cid == "blosc":
        return f"blosc({extra.get('cname', '?')}, clevel={extra.get('clevel', '?')}, shuffle={extra.get('shuffle', '?')})"
    keep = {k: v for k, v in extra.items() if k in ("level", "clevel", "endian", "order")}
    return f"{cid}({', '.join(f'{k}={v}' for k, v in keep.items())})" if keep else cid


def array_info(node):
    m = node["meta"]
    if node["zarr_format"] == 2:
        dtype = m.get("dtype")
        dtype = dtype if isinstance(dtype, str) else json.dumps(dtype)
        filters = m.get("filters") or []
        comp = m.get("compressor")
        sep = m.get("dimension_separator", ".")
        return {
            "shape": list(m.get("shape", [])), "dtype": dtype,
            "chunks": list(m.get("chunks", [])), "shards": None,
            "codecs": [s for s in [*(_codec_str(f) for f in filters), _codec_str(comp)] if s],
            "compressed": comp is not None,
            "fill_value": m.get("fill_value"), "itemsize": _itemsize(dtype),
            "key": lambda idx, sep=sep: sep.join(map(str, idx)) if idx else "0",
            "dimension_names": None, "filters_empty": m.get("filters") == [],
        }
    dtype = m.get("data_type")
    dtype = dtype if isinstance(dtype, str) else json.dumps(dtype)
    grid = (m.get("chunk_grid") or {}).get("configuration", {}).get("chunk_shape", [])
    codecs = m.get("codecs") or []
    shards, chunks, inner = None, list(grid), codecs
    if codecs and codecs[0].get("name") == "sharding_indexed":
        cfg = codecs[0].get("configuration", {})
        shards, chunks = list(grid), list(cfg.get("chunk_shape", []))
        inner = cfg.get("codecs", [])
    names = [c.get("name") for c in inner]
    cke = m.get("chunk_key_encoding") or {"name": "default"}
    sep = (cke.get("configuration") or {}).get("separator", "/" if cke.get("name") == "default" else ".")
    if cke.get("name") == "v2":
        keyf = lambda idx, sep=sep: sep.join(map(str, idx)) if idx else "0"
    else:
        keyf = lambda idx, sep=sep: "c" + "".join(sep + str(i) for i in idx)
    codec_list = [s for s in (_codec_str(c) for c in inner) if s]
    if shards:
        codec_list = ["sharding_indexed"] + codec_list
    return {
        "shape": list(m.get("shape", [])), "dtype": dtype, "chunks": chunks,
        "shards": shards, "codecs": codec_list,
        "compressed": any(n not in NON_COMPRESSING for n in names),
        "fill_value": m.get("fill_value"), "itemsize": _itemsize(dtype), "key": keyf,
        "dimension_names": m.get("dimension_names"),
    }


def grid_of(shape, block):
    return [max(1, math.ceil(s / b)) if b else 1 for s, b in zip(shape, block)]


# --------------------------------------------------------------------------- helpers
def prod(xs):
    return math.prod(int(x) for x in xs) if xs else 0


def fmt_bytes(n):
    if n is None:
        return "?"
    for u in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if abs(n) < 1024 or u == "PiB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


def fmt_dtype(d):
    import numpy as np
    try:
        dt = np.dtype(d)
    except Exception:
        return str(d)
    s = dt.name
    if dt.byteorder == ">" and dt.itemsize > 1:
        s += " (big-endian)"
    return s


def fmt_num(x):
    if x is None:
        return "?"
    if isinstance(x, float) and not x.is_integer():
        return f"{x:.4g}"
    return str(int(x)) if isinstance(x, float) else str(x)


def fmt_len(value, unit):
    """Human length, promoting µm → mm etc. for display only."""
    if value is None:
        return "?"
    if unit == "micrometer" and value >= 1000:
        return f"{value / 1000:.3g} mm"
    if unit == "nanometer" and value >= 1000:
        return f"{value / 1000:.3g} µm"
    return f"{value:.4g} {SHORT_UNIT.get(unit, unit or '(no unit)')}"


def norm_axes(raw, ndim):
    if raw is None:
        return None
    out = []
    for a in raw:
        if isinstance(a, str):  # 0.3 style
            out.append({"name": a, "type": {"t": "time", "c": "channel"}.get(a, "space" if a in "zyx" else None), "unit": None})
        else:
            out.append({"name": a.get("name"), "type": a.get("type"), "unit": a.get("unit")})
    return out


def split_ct(cts):
    scale = trans = None
    for t in cts or []:
        if t.get("type") == "scale":
            scale = t.get("scale")
        elif t.get("type") == "translation":
            trans = t.get("translation")
    return scale, trans


# --------------------------------------------------------------------------- checks
def check_version(version, zfmt, path, F):
    if version is None:
        F.add("warning", "VERSION_MISSING", path, "No OME-Zarr version found in the metadata.",
              "Add the version field your writer targets (see reading-ome-zarr-spec).")
        return
    if version not in KNOWN_VERSIONS:
        F.add("info", "VERSION_UNCHECKED", path,
              f"OME-Zarr {version}: checks here encode 0.4/0.5 rules only.",
              f"Confirm version-specific rules with the reading-ome-zarr-spec skill for {version}.")
    if version == "0.4" and zfmt == 3:
        F.add("error", "VERSION_FORMAT_MISMATCH", path, "OME-Zarr 0.4 metadata in a Zarr v3 store.",
              "0.4 is Zarr v2; either write v2 or upgrade metadata to 0.5 (attributes.ome).")
    if version == "0.5" and zfmt == 2:
        F.add("error", "VERSION_FORMAT_MISMATCH", path, "OME-Zarr 0.5 metadata in a Zarr v2 store.",
              "0.5 requires Zarr v3 (zarr.json); convert the store or declare 0.4.")


def check_axes(axes, ndim, version, path, F):
    if axes is None:
        if version in KNOWN_VERSIONS:
            F.add("error", "AXES_MISSING", path, "multiscales has no axes.", "Add an axes list (name, type, unit).")
        return
    if ndim is not None and len(axes) != ndim:
        F.add("error", "AXES_NDIM_MISMATCH", path,
              f"{len(axes)} axes declared but level 0 has {ndim} dimensions.",
              "Make the axes list match the array dimensions one-to-one.")
    names = [a["name"] for a in axes]
    if len(set(names)) != len(names):
        F.add("error", "AXES_DUPLICATE", path, f"Duplicate axis names: {names}.", "Give every axis a unique name.")
    for a in axes:
        u, t = a["unit"], a["type"]
        if u is None:
            if t in ("space", "time"):
                F.add("warning", "UNIT_MISSING", path, f"Axis '{a['name']}' ({t}) has no unit.",
                      "Add a unit (e.g. micrometer, second) so physical sizes are known.")
            continue
        allowed = SPACE_UNITS if t == "space" else TIME_UNITS if t == "time" else SPACE_UNITS | TIME_UNITS
        if u not in allowed:
            sug = UNIT_ALIASES.get(str(u).strip().lower())
            F.add("warning", "UNIT_NONSTANDARD", path,
                  f"Axis '{a['name']}' unit '{u}' is not a UDUNITS-2 name.",
                  f"Use '{sug}'." if sug else "Use a full UDUNITS-2 name such as 'micrometer' or 'second'.")
        if t == "channel":
            F.add("info", "UNIT_ON_CHANNEL", path, f"Channel axis '{a['name']}' has unit '{u}'.",
                  "Channel axes normally carry no unit; remove it unless intentional.")
    if version not in KNOWN_VERSIONS:
        return
    types = [a["type"] for a in axes]
    if not 2 <= len(axes) <= 5:
        F.add("error", "AXES_COUNT", path, f"{len(axes)} axes; {version} allows 2–5.", "Drop or merge axes.")
    nspace = types.count("space")
    if nspace not in (2, 3):
        F.add("error", "AXES_SPACE_COUNT", path, f"{nspace} space axes; {version} requires 2 or 3.",
              "Mark exactly 2 or 3 axes as type 'space'.")
    for t in ("time", "channel"):
        if types.count(t) > 1:
            F.add("error", "AXES_TYPE_REPEAT", path, f"More than one '{t}' axis.", f"Keep one {t} axis.")
    rank = {"time": 0, "channel": 1, "space": 3}
    ranks = [rank.get(t, 2) for t in types]
    if ranks != sorted(ranks):
        F.add("error", "AXES_ORDER", path,
              f"Axis order {''.join(n or '?' for n in names)} violates {version}: time, then channel/custom, then space.",
              "Transpose the arrays and axes to t,c,z,y,x order (only the axes you have).")
    unknown = [a["name"] for a in axes if a["type"] not in ("space", "time", "channel")]
    if unknown:
        F.add("info", "AXES_CUSTOM_TYPE", path, f"Axes with non-standard type: {unknown}.",
              "Fine if intentional; many viewers ignore custom axes.")
    sp = [a["name"] for a in axes if a["type"] == "space"]
    if sp and sp != ["z", "y", "x"][-len(sp):]:
        F.add("info", "AXES_SPACE_NAMES", path, f"Space axes are named {sp}, not {['z','y','x'][-len(sp):]}.",
              "Many tools assume z,y,x names; rename if this was not deliberate.")


def check_multiscale_keys(m, path, F):
    extra = sorted(set(m) - MULTISCALE_KEYS)
    if extra:
        F.add("info", "MULTISCALE_EXTRA_KEYS", path, f"Non-spec keys in multiscales: {extra}.",
              "Harmless to readers; move tool-specific data under 'metadata' or your own top-level key.")


def check_levels(img, path, F):
    levels = [l for l in img["levels"] if l.get("shape") is not None]
    axes = img["axes"] or [{"name": f"d{i}", "type": None} for i in range(img["ndim"] or 0)]
    if not levels:
        return
    l0 = levels[0]
    dtypes = {l["dtype"] for l in levels}
    if len(dtypes) > 1:
        F.add("warning", "LEVEL_DTYPE_MIXED", path, f"Pyramid levels use different dtypes: {sorted(dtypes)}.",
              "Regenerate the pyramid with one dtype.")
    for lv in img["levels"]:
        if lv.get("shape") is None:
            F.add("error", "LEVEL_MISSING", f"{path}/{lv['path']}".lstrip("/"),
                  f"Level '{lv['path']}' is listed in datasets but its array metadata is missing.",
                  "Regenerate that level, or remove it from multiscales.datasets.")
            continue
        if len(lv["shape"]) != len(l0["shape"]):
            F.add("error", "LEVEL_NDIM", path, f"Level {lv['path']} has {len(lv['shape'])} dims, level 0 has {len(l0['shape'])}.",
                  "All levels must have the same dimensionality.")
            continue
        sc, tr = lv["scale"], lv["translation"]
        if sc is None:
            F.add("error", "CT_SCALE_MISSING", path, f"Level {lv['path']} has no scale transformation.",
                  "Add a 'scale' coordinateTransformation to every dataset.")
            continue
        if len(sc) != len(lv["shape"]) or (tr is not None and len(tr) != len(lv["shape"])):
            F.add("error", "CT_LENGTH", path, f"Level {lv['path']} transformation length doesn't match {len(lv['shape'])} dims.",
                  "Give one scale/translation value per axis.")
            continue
        if any((s is None) or s <= 0 for s in sc):
            F.add("error", "CT_SCALE_NONPOSITIVE", path, f"Level {lv['path']} has non-positive scale {sc}.",
                  "Scales must be > 0.")
        if lv.get("ct_order_bad"):
            F.add("error", "CT_ORDER", path, f"Level {lv['path']}: translation comes before scale.",
                  "List scale first, then translation.")
    good = [l for l in levels if l["scale"] and len(l["scale"]) == len(l0["shape"]) == len(l["shape"])]
    if not good or good[0] is not l0:
        return
    mism = []
    for lv in good[1:]:
        for i, ax in enumerate(axes):
            s0, sk, n0, nk = l0["scale"][i], lv["scale"][i], l0["shape"][i], lv["shape"][i]
            if not s0 or not sk:
                continue
            expected = n0 * s0 / sk
            if abs(nk - expected) > max(1.0, 0.01 * expected):
                mism.append(f"level {lv['path']} {ax['name']}: shape {nk}, scale implies ~{expected:.1f}")
    if mism:
        F.add("error", "SCALE_SHAPE_MISMATCH", path,
              "Level scales don't match level shapes (" + "; ".join(mism[:4]) + ("; …" if len(mism) > 4 else "") + ").",
              "Recompute each level's scale as level-0 scale × (level-0 shape / level shape).")
    for a, b in zip(good, good[1:]):
        if any(nb > na for na, nb in zip(a["shape"], b["shape"])):
            F.add("error", "LEVEL_ORDER", path, f"Level {b['path']} is larger than level {a['path']}.",
                  "Order datasets from highest to lowest resolution.")
            break
    # gap detection: per-level max downsampling factor
    facs = []
    for a, b in zip(good, good[1:]):
        f = max((na / nb) for na, nb in zip(a["shape"], b["shape"]) if nb)
        facs.append((b["path"], f))
    if len(facs) >= 2:
        med = min(f for _, f in facs if f > 1.05) if any(f > 1.05 for _, f in facs) else 1
        for p, f in facs:
            if med > 1 and f >= 1.9 * med:
                F.add("warning", "LEVEL_GAP", path,
                      f"Level {p} is downsampled {f:.1f}× from the previous level (typical step {med:.1f}×); a level may be missing.",
                      "Check whether an intermediate level was dropped and regenerate it.")
    # translation-in-voxels heuristic (spatial axes only)
    sp = [i for i, a in enumerate(axes) if a.get("type") == "space"]
    t0 = l0["translation"] or [0.0] * len(l0["shape"])
    hits = total = 0
    for lv in good[1:]:
        tk = lv["translation"]
        if not tk:
            continue
        for i in sp:
            s0, sk = l0["scale"][i], lv["scale"][i]
            if not s0 or sk == s0:
                continue
            d = tk[i] - t0[i]
            phys, vox = (sk - s0) / 2, (sk / s0 - 1) / 2
            tol = 1e-3 * max(abs(phys), abs(vox), 1e-9)
            if abs(phys - vox) > tol:
                total += 1
                if abs(d - vox) <= tol:
                    hits += 1
    if total and hits == total:
        F.add("warning", "TRANSLATION_IN_VOXELS", path,
              "Per-level translations equal (factor−1)/2 in level-0 voxels, not physical units; levels will be offset in viewers.",
              "Multiply translations by the level-0 scale (offset = (scale_k − scale_0)/2 in physical units).")


def check_storage(img, path, F):
    l0 = next((l for l in img["levels"] if l.get("shape")), None)
    if not l0:
        return
    axes = img["axes"] or []
    if not l0["compressed"]:
        F.add("warning", "NO_COMPRESSION", path, "Arrays are stored uncompressed.",
              "Rewrite with a compressor (e.g. zstd or blosc-zstd); typically 2–5× smaller for microscopy.")
    isz = l0["itemsize"] or 1
    cb = prod(l0["chunks"]) * isz
    nchunks = prod(grid_of(l0["shape"], l0["chunks"]))
    if cb < TINY_CHUNK and nchunks >= 100:
        F.add("warning", "CHUNK_TINY", path,
              f"Level-0 chunks are {fmt_bytes(cb)} uncompressed ({nchunks:,} chunks); slow on cloud storage and file systems.",
              "Rechunk to ~1–16 MiB chunks, or use v3 sharding to group small chunks.")
    if cb > HUGE_CHUNK:
        F.add("warning", "CHUNK_HUGE", path, f"Level-0 chunks are {fmt_bytes(cb)} uncompressed; partial reads will be slow and memory-hungry.",
              "Rechunk to ~1–64 MiB (use shards for large objects).")
    if l0["shards"]:
        sb = prod(l0["shards"]) * isz
        if sb > HUGE_SHARD:
            F.add("info", "SHARD_HUGE", path, f"Shards are {fmt_bytes(sb)} uncompressed.",
                  "Fine for reading; writers must hold a whole shard, so smaller shards ease rewriting.")
    for i, a in enumerate(axes):
        if a.get("type") in ("channel", "time") and i < len(l0["chunks"]) and l0["shape"][i] > 1 and l0["chunks"][i] > 1:
            F.add("warning", "CHUNK_SPANS_" + a["type"].upper(), path,
                  f"Chunks span {l0['chunks'][i]} of {l0['shape'][i]} along '{a['name']}' ({a['type']}); reading one {'channel' if a['type'] == 'channel' else 'time point'} reads all {l0['chunks'][i]}.",
                  f"Rechunk with chunk size 1 along '{a['name']}'.")
    if l0["shards"] and any(s % c for s, c in zip(l0["shards"], l0["chunks"])):
        F.add("error", "SHARD_NOT_MULTIPLE", path, "Shard shape is not a multiple of the inner chunk shape.",
              "Choose shards that are whole multiples of chunks along every axis.")


# --------------------------------------------------------------------------- size estimation
def estimate_level_bytes(store, rel, lv, max_list, n_sample):
    """Return (on_disk_bytes, objects_present, method)."""
    block = lv["shards"] or lv["chunks"]
    grid = grid_of(lv["shape"], block)
    n = prod(grid)
    arr_rel = "/".join(x for x in (rel, lv["path"]) if x)
    if store.protocol == "file" and not store.is_zip:
        base = store.full(arr_rel)
        tot = cnt = 0
        for dp, _, files in os.walk(base):
            for f in files:
                if f in (".zarray", ".zattrs", "zarr.json", ".zgroup"):
                    continue
                cnt += 1
                tot += os.path.getsize(os.path.join(dp, f))
                if cnt > max_list:
                    break
            if cnt > max_list:
                break
        if cnt <= max_list:
            return tot, cnt, "exact"
    if store.is_zip:
        try:
            infos = [i for i in store.fs.zip.infolist() if i.filename.startswith(store.full(arr_rel).lstrip("/") + "/")]
            data = [i for i in infos if not i.filename.endswith((".zarray", ".zattrs", "zarr.json"))]
            return sum(i.compress_size for i in data), len(data), "exact"
        except Exception:
            pass
    # sample object sizes with HEAD-style requests at deterministic positions
    k = min(n, n_sample)  # deterministic, evenly spaced over the chunk grid
    idxs = [int(round(i * (n - 1) / max(1, k - 1))) for i in range(k)] if k > 1 else [n // 2]
    keys = []
    for li in idxs:
        idx, r = [], li
        for g in reversed(grid):
            idx.append(r % g)
            r //= g
        keys.append(arr_rel + "/" + lv["key"](list(reversed(idx))))
    with ThreadPoolExecutor(8) as ex:
        sizes = list(ex.map(store.size, keys))
    known = [s for s in sizes if s is not None and s >= 0]
    present = len(known)
    if any(s == -1 for s in sizes) or not sizes:
        return None, None, "unknown"
    if present == 0:
        return 0, 0, f"sampled {k} of {n:,} objects: none present (all fill value?)"
    frac = present / len(sizes)
    est = sum(known) / present * frac * n
    return int(est), int(round(frac * n)), f"estimated from {k} of {n:,} objects"


# --------------------------------------------------------------------------- sampling
def sample_smallest(store, rel, img, is_label):
    import numpy as np
    import zarr
    lv = next((l for l in reversed(img["levels"]) if l.get("shape")), None)
    if lv is None:
        return None
    zs, pre = store.zarr_store()
    if zs is None:
        return {"skipped": "chunk sampling not supported for remote zip"}
    arr_rel = "/".join(x for x in (pre, rel, lv["path"]) if x)
    try:
        a = zarr.open_array(store=zs, path=arr_rel, mode="r", zarr_format=img["zarr_format"])
    except Exception as e:
        return {"skipped": f"could not open level {lv['path']}: {type(e).__name__}: {str(e)[:120]}"}
    chunks = lv["chunks"]
    grid = grid_of(lv["shape"], chunks)
    picks = {tuple(g // 2 for g in grid), tuple(0 for _ in grid)}
    blocks = []
    for idx in sorted(picks)[:4]:
        sl = tuple(slice(i * c, min((i + 1) * c, s)) for i, c, s in zip(idx, chunks, lv["shape"]))
        try:
            blocks.append(np.asarray(a[sl]).ravel())
        except Exception as e:
            return {"skipped": f"read failed: {type(e).__name__}: {str(e)[:120]}"}
    v = np.concatenate(blocks)
    out = {"level": lv["path"], "chunks_read": len(blocks), "values": int(v.size)}
    if v.size == 0:
        return out
    if v.dtype.kind in "iufb":
        fv = lv.get("fill_value")
        out.update({"min": float(v.min()), "max": float(v.max()),
                    "fraction_fill": float((v == (fv if isinstance(fv, (int, float)) else 0)).mean())})
        if is_label:
            u = np.unique(v)
            out["distinct_labels"] = int(u.size - (1 if 0 in u else 0))
            out["non_integer_values"] = bool(v.dtype.kind == "f" and not np.all(np.mod(v, 1) == 0))
        else:
            out["p1"], out["p99_9"] = (float(x) for x in np.percentile(v, [1, 99.9]))
    return out


# --------------------------------------------------------------------------- image
def inspect_image(store, rel, node, F, args, sample=True, is_label=False, parent=None):
    ome = node["ome"]
    version = ome_version(node)
    zfmt = node["zarr_format"]
    ms_list = ome.get("multiscales") or []
    path = rel or "/"
    if len(ms_list) > 1:
        F.add("info", "MULTISCALES_MULTIPLE", path, f"{len(ms_list)} multiscales entries; reporting the first.",
              "Most viewers only read the first entry.")
    m = ms_list[0] if ms_list else {}
    check_multiscale_keys(m, path, F)
    datasets = m.get("datasets") or []
    if not datasets:
        F.add("error", "DATASETS_MISSING", path, "multiscales has no datasets.", "List each pyramid level in datasets.")
    gscale, gtrans = split_ct(m.get("coordinateTransformations"))
    # read every level's array metadata in one batch
    names = []
    for d in datasets:
        p = "/".join(x for x in (rel, d.get("path", "")) if x)
        names += [p + "/zarr.json"] if zfmt == 3 else [p + "/.zarray"]
    got = store.get_many(names) if names else {}
    levels = []
    for d, nm in zip(datasets, names):
        cts = d.get("coordinateTransformations") or []
        sc, tr = split_ct(cts)
        types = [t.get("type") for t in cts]
        lv = {"path": d.get("path"), "scale": sc, "translation": tr,
              "ct_order_bad": "translation" in types and "scale" in types and types.index("translation") < types.index("scale")}
        raw = got.get(nm)
        if raw:
            meta = json.loads(raw)
            ai = array_info({"zarr_format": zfmt, "meta": meta})
            lv.update(ai)
        else:
            lv["shape"] = None
        if sc and gscale and len(gscale) == len(sc):
            lv["scale"] = [a * b for a, b in zip(sc, gscale)]
        levels.append(lv)
    l0 = next((l for l in levels if l.get("shape")), None)
    ndim = len(l0["shape"]) if l0 else None
    axes = norm_axes(m.get("axes"), ndim)
    if axes is None and l0 and l0.get("dimension_names"):
        axes = [{"name": n, "type": None, "unit": None} for n in l0["dimension_names"]]
    img = {"path": path, "name": m.get("name"), "version": version, "zarr_format": zfmt,
           "axes": axes, "ndim": ndim, "levels": levels, "is_label": is_label}
    check_version(version, zfmt, path, F)
    check_axes(axes if m.get("axes") is not None else None, ndim, version, path, F)
    if l0 and l0.get("dimension_names") and axes and [a["name"] for a in axes] != l0["dimension_names"]:
        F.add("warning", "DIMENSION_NAMES_MISMATCH", path,
              f"zarr dimension_names {l0['dimension_names']} differ from OME axes {[a['name'] for a in axes]}.",
              "Make dimension_names match the OME axis names.")
    check_levels(img, path, F)
    check_storage(img, path, F)
    if zfmt == 2 and any(l.get("filters_empty") for l in levels):
        F.add("info", "V2_EMPTY_FILTERS", path, "Zarr v2 arrays have \"filters\": [] instead of null.",
              "Write null; zarr-python 3 warns and plans to reject empty filter lists.")
    # physical summary
    if l0 and axes and l0.get("scale") and len(axes) == len(l0["shape"]) == len(l0["scale"]):
        img["pixel_size"] = {a["name"]: {"value": s, "unit": a["unit"]} for a, s in zip(axes, l0["scale"]) if a["type"] == "space"}
        img["extent"] = {a["name"]: {"value": s * n, "unit": a["unit"]} for a, s, n in zip(axes, l0["scale"], l0["shape"]) if a["type"] == "space"}
        sp = [v["value"] for v in img["pixel_size"].values() if v["value"]]
        img["anisotropy"] = round(max(sp) / min(sp), 4) if len(sp) > 1 else None
        for a, s, n in zip(axes, l0["scale"], l0["shape"]):
            if a["type"] == "time":
                img["timepoints"] = {"count": n, "interval": s, "unit": a["unit"]}
            if a["type"] == "channel":
                img["channel_count"] = n
    # omero
    om = ome.get("omero")
    if isinstance(om, dict) and om.get("channels") is not None:
        chans = []
        for c in om["channels"]:
            w = c.get("window") or {}
            chans.append({"label": c.get("label"), "color": c.get("color"), "active": c.get("active"),
                          "window": [w.get("start"), w.get("end")] if w else None,
                          "range": [w.get("min"), w.get("max")] if w else None})
        img["channels"] = chans
        cc = img.get("channel_count", 1 if axes and not any(a["type"] == "channel" for a in axes) else None)
        if cc is not None and len(chans) != cc:
            F.add("warning", "OMERO_CHANNEL_COUNT", path, f"omero lists {len(chans)} channels but the image has {cc}.",
                  "Make omero.channels one entry per channel.")
    elif not is_label:
        F.add("info", "OMERO_MISSING", path, "No omero metadata: no channel names, colors or contrast windows.",
              "Add omero.channels (label, color, window) so viewers show sensible defaults.")
    if is_label:
        il = ome.get("image-label") or {}
        img["image_label"] = {"colors": len(il.get("colors") or []), "properties": len(il.get("properties") or []),
                              "source": (il.get("source") or {}).get("image")}
        if l0 and l0.get("dtype") and ("f" in l0["dtype"].lstrip("<>|=")[:1] or "float" in l0["dtype"]):
            F.add("warning", "LABEL_FLOAT", path, f"Label image has float dtype {fmt_dtype(l0['dtype'])}.",
                  "Store labels as an integer dtype (uint32 or uint64 for many objects).")
        if parent and l0 and parent.get("axes") and axes:
            pn = {a["name"]: parent["levels"][0]["shape"][i] for i, a in enumerate(parent["axes"])
                  if a["type"] == "space" and parent["levels"][0].get("shape")}
            ln = {a["name"]: l0["shape"][i] for i, a in enumerate(axes) if a["type"] == "space"}
            bad = {k: (ln[k], pn[k]) for k in ln if k in pn and ln[k] != pn[k]}
            if bad:
                F.add("warning", "LABEL_SHAPE_MISMATCH", path,
                      "Label level-0 spatial shape differs from its image: " + ", ".join(f"{k} {a} vs {b}" for k, (a, b) in bad.items()) + ".",
                      "Regenerate labels on the image grid, or make sure their scales map onto it.")
    # sizes
    total_disk, total_raw, methods = 0, 0, set()
    for lv in levels:
        if not lv.get("shape"):
            continue
        lv["uncompressed_bytes"] = prod(lv["shape"]) * (lv["itemsize"] or 0)
        block = lv["shards"] or lv["chunks"]
        lv["objects_expected"] = prod(grid_of(lv["shape"], block))
        if args.no_size:
            continue
        b, cnt, how = estimate_level_bytes(store, rel, lv, args.max_list, 32 if lv is l0 else 4)
        lv["on_disk_bytes"], lv["objects_present"], lv["size_method"] = b, cnt, how
        total_raw += lv["uncompressed_bytes"]
        if b is None:
            total_disk = None
        elif total_disk is not None:
            total_disk += b
        methods.add("exact" if how == "exact" else "estimated")
    img["uncompressed_bytes"] = sum(l.get("uncompressed_bytes", 0) for l in levels)
    img["on_disk_bytes"] = total_disk if not args.no_size else None
    img["on_disk_method"] = ("exact" if methods == {"exact"} else "estimated, inferred") if methods else None
    if sample and not args.no_sample:
        img["sample"] = sample_smallest(store, rel, img, is_label)
        s = img["sample"] or {}
        if is_label and s.get("non_integer_values"):
            F.add("error", "LABEL_NON_INTEGER", path, "Sampled label values are not integers.",
                  "Labels must be integer ids; this may be an intensity image stored as a label.")
        if s.get("fraction_fill") == 1.0 and not is_label:
            F.add("info", "SAMPLE_EMPTY", path, f"Sampled chunks of level {s.get('level')} contain only the fill value.",
                  "May be normal (sparse data); otherwise check the pyramid was actually written.")
    # labels
    lab = read_node(store, "/".join(x for x in (rel, "labels") if x), pref=zfmt)
    img["labels"] = []
    if lab:
        lnames = lab["ome"].get("labels") or []
        if not lnames:
            F.add("warning", "LABELS_UNLISTED", path, "labels group exists but lists no labels.",
                  "Add the 'labels' list naming each label image.")
        for ln in lnames[: args.max_images]:
            lrel = "/".join(x for x in (rel, "labels", ln) if x)
            ln_node = read_node(store, lrel, pref=zfmt)
            if not ln_node or not ln_node["ome"].get("multiscales"):
                F.add("error", "LABEL_MISSING", lrel, f"Label '{ln}' is listed but has no multiscales metadata.",
                      "Write the label image or remove it from labels.labels.")
                continue
            img["labels"].append(inspect_image(store, lrel, ln_node, F, args, sample=sample, is_label=True, parent=img))
    img["tables"] = find_tables(store, rel, zfmt)
    for lv in levels:
        lv.pop("key", None)
    return img


def find_tables(store, rel, zfmt):
    trel = "/".join(x for x in (rel, "tables") if x)
    node = read_node(store, trel, pref=None)
    if not node:
        return []
    listed = node["attrs"].get("tables") or (node["ome"].get("tables") if isinstance(node["ome"], dict) else None)
    names = listed if isinstance(listed, list) else (store.ls(trel, cap=200) or [])
    names = [n for n in names if not n.startswith((".z", "zarr.json"))]
    out = []
    for n in names[:50]:
        tn = read_node(store, f"{trel}/{n}")
        if tn is None:
            continue
        a = tn["attrs"]
        out.append({"name": n, "path": f"{trel}/{n}", "encoding": a.get("encoding-type"),
                    "region": (a.get("spatialdata_attrs") or {}).get("region") or a.get("region")})
    return out


# --------------------------------------------------------------------------- plate / collection
def inspect_plate(store, rel, node, F, args):
    pl = node["ome"]["plate"]
    path = rel or "/"
    rows = [r.get("name") for r in pl.get("rows", [])]
    cols = [c.get("name") for c in pl.get("columns", [])]
    wells = pl.get("wells", [])
    out = {"name": pl.get("name"), "rows": rows, "columns": cols, "well_count": len(wells),
           "field_count": pl.get("field_count"), "acquisitions": len(pl.get("acquisitions") or []),
           "version": ome_version(node)}
    check_version(out["version"], node["zarr_format"], path, F)
    zfmt = node["zarr_format"]
    wl = wells[:MAX_WELLS]
    names = [("/".join(x for x in (rel, w.get("path")) if x)) + ("/zarr.json" if zfmt == 3 else "/.zattrs") for w in wl]
    got = store.get_many(names) if names else {}
    missing, fields, first_img = [], {}, None
    for w, nm in zip(wl, names):
        raw = got.get(nm)
        if not raw:
            missing.append(w.get("path"))
            continue
        meta = json.loads(raw)
        wa = (meta.get("attributes", {}).get("ome", {}) if zfmt == 3 else meta).get("well", {})
        ims = wa.get("images", [])
        fields[w.get("path")] = len(ims)
        if first_img is None and ims:
            first_img = f"{w.get('path')}/{ims[0].get('path')}"
    if missing:
        F.add("error", "PLATE_MISSING_WELLS", path,
              f"{len(missing)} wells listed in plate metadata have no well metadata: {missing[:8]}{' …' if len(missing) > 8 else ''}.",
              "Write the missing wells or remove them from plate.wells.")
    if len(wells) > MAX_WELLS:
        F.add("info", "PLATE_WELLS_CAPPED", path, f"Checked first {MAX_WELLS} of {len(wells)} wells.", "Re-run on a local copy for a full check.")
    grid = len(rows) * len(cols)
    if grid and len(wells) < grid:
        taken = {(w.get("rowIndex"), w.get("columnIndex")) for w in wells}
        empty = [f"{r}{c}" for i, r in enumerate(rows) for j, c in enumerate(cols) if (i, j) not in taken]
        out["empty_positions"] = empty if len(empty) <= 24 else len(empty)
        F.add("info", "PLATE_PARTIAL", path, f"{len(wells)} of {grid} plate positions have wells.",
              "Normal for partially used plates; confirm it matches the experiment layout.")
    fc = sorted(set(fields.values()))
    out["fields_per_well"] = fc
    if len(fc) > 1:
        F.add("warning", "PLATE_FIELDS_UNEVEN", path, f"Wells have different field counts: {fc}.",
              "Usually means acquisition failed for some fields; check missing ones.")
    if pl.get("field_count") and fc and max(fc) > pl["field_count"]:
        F.add("warning", "PLATE_FIELD_COUNT", path, f"plate.field_count={pl['field_count']} but a well has {max(fc)} fields.",
              "Update plate.field_count to the maximum fields per well.")
    out["representative"] = first_img
    img = None
    if first_img:
        irel = "/".join(x for x in (rel, first_img) if x)
        inode = read_node(store, irel, pref=zfmt)
        if inode and inode["ome"].get("multiscales"):
            img = inspect_image(store, irel, inode, F, args)
        else:
            F.add("error", "PLATE_IMAGE_MISSING", irel, "First field image has no multiscales metadata.", "Rewrite that field.")
    return out, img


def inspect_collection(store, rel, node, F, args):
    """bioformats2raw layout: OME/ + numbered series."""
    zfmt = node["zarr_format"]
    om = read_node(store, "/".join(x for x in (rel, "OME") if x))
    series = None
    if om:
        series = om["ome"].get("series") or om["attrs"].get("series")
    probed = False
    if not series:
        probed, series, i = True, [], 0
        while i < MAX_SERIES:
            batch = [str(k) for k in range(i, i + 16)]
            meta = "zarr.json" if zfmt == 3 else ".zattrs"
            got = store.get_many(["/".join(x for x in (rel, b, meta) if x) for b in batch])
            hit = [b for b in batch if got.get("/".join(x for x in (rel, b, meta) if x))]
            series += hit
            if len(hit) < len(batch):
                break
            i += 16
    xml = store.size("/".join(x for x in (rel, "OME", "METADATA.ome.xml") if x))
    out = {"layout": node["ome"].get("bioformats2raw.layout"), "series": series, "series_probed": probed,
           "ome_xml": xml is not None and xml != -1, "ome_xml_bytes": xml if xml and xml > 0 else None}
    imgs = []
    for k, s in enumerate(series[: args.max_images]):
        srel = "/".join(x for x in (rel, str(s)) if x)
        sn = read_node(store, srel)
        if sn and sn["ome"].get("multiscales"):
            imgs.append(inspect_image(store, srel, sn, F, args, sample=(k == 0)))
        else:
            F.add("error", "SERIES_MISSING", srel, f"Series '{s}' has no multiscales metadata.", "Rewrite the series or fix OME/series.")
    if len(series) > args.max_images:
        F.add("info", "SERIES_CAPPED", rel or "/", f"Inspected {args.max_images} of {len(series)} series.", "Pass --max-images N to see more.")
    return out, imgs


# --------------------------------------------------------------------------- cors
def check_cors(store, rel_meta):
    if store.protocol in ("s3", "s3a"):
        b, _, k = store.root.partition("/")
        url = f"https://{b}.s3.amazonaws.com/{'/'.join(x for x in (k, store.prefix, rel_meta) if x)}"
    elif store.protocol in ("gs", "gcs"):
        url = f"https://storage.googleapis.com/{store.full(rel_meta)}"
    elif store.protocol in ("http", "https"):
        url = store.full(rel_meta)
    else:
        return None
    if "anonymous" not in (store.access or ""):
        return {"url": url, "status": "not checked (private bucket)"}
    try:
        req = urllib.request.Request(url, headers={"Origin": "https://example.org", "Range": "bytes=0-0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            acao = r.headers.get("Access-Control-Allow-Origin")
        return {"url": url, "status": "allowed" if acao else "not advertised", "allow_origin": acao}
    except Exception as e:
        return {"url": url, "status": f"check failed ({type(e).__name__})"}


# --------------------------------------------------------------------------- report
def axes_str(img):
    l0 = next((l for l in img["levels"] if l.get("shape")), None)
    if not img.get("axes") or not l0:
        return "?"
    return " × ".join(f"{a['name']} {n}" for a, n in zip(img["axes"], l0["shape"]))


def img_headline(img):
    l0 = next((l for l in img["levels"] if l.get("shape")), None)
    if not l0:
        return "image with no readable levels"
    sp = [(a, n) for a, n in zip(img.get("axes") or [], l0["shape"]) if a["type"] == "space"]
    bits = []
    if sp:
        bits.append(f"{len(sp)}D " + "×".join(str(n) for _, n in reversed(sp)) + " (" + ",".join(a["name"] for a, _ in reversed(sp)) + ")")
    if img.get("pixel_size"):
        ps = img["pixel_size"]
        us = {ps[a["name"]]["unit"] for a, _ in sp}
        if len(us) == 1:
            u = us.pop()
            txt = "at " + "×".join(fmt_num(ps[a["name"]]["value"]) for a, _ in reversed(sp)) + f" {SHORT_UNIT.get(u, u or '(no unit)')}"
        else:
            txt = "at " + " × ".join(fmt_len(ps[a["name"]]["value"], ps[a["name"]]["unit"]) for a, _ in reversed(sp))
        if img.get("extent"):
            ex = img["extent"]
            txt += " (" + " × ".join(fmt_len(ex[a["name"]]["value"], ex[a["name"]]["unit"]) for a, _ in reversed(sp)) + ")"
        bits.append(txt)
    cc = img.get("channel_count")
    if cc:
        bits.append(f"{cc} channel{'s' * (cc != 1)}")
    tp = img.get("timepoints")
    if tp and tp["count"] > 1:
        bits.append(f"{tp['count']} timepoints")
    bits.append(fmt_dtype(l0["dtype"]))
    bits.append(f"{sum(1 for l in img['levels'] if l.get('shape'))} levels")
    return ", ".join(bits)


def render(rep, detail):
    L = []
    st = rep["store"]
    F = rep["findings"]
    errs = [f for f in F if f["severity"] == "error"]
    warns = [f for f in F if f["severity"] == "warning"]
    infos = [f for f in F if f["severity"] == "info"]
    kind = st["kind"]
    imgs = rep["images"]
    main = imgs[0] if imgs else None
    ver = st.get("ome_version") or "unknown version"
    head = f"**{kind.capitalize()}**, OME-Zarr {ver} (Zarr v{st['zarr_format']})"
    if kind == "plate" and rep.get("plate"):
        p = rep["plate"]
        head += f": {len(p['rows'])}×{len(p['columns'])} plate, {p['well_count']} wells, {'/'.join(map(str, p['fields_per_well'])) or '?'} field(s) per well"
    if kind == "collection" and rep.get("collection"):
        head += f" with {len(rep['collection']['series'])} series"
    if main:
        head += (". Representative image: " if kind in ("plate", "collection") else ": ") + img_headline(main)
    head += "."
    if main and main.get("labels"):
        head += f" Labels: {', '.join(l['path'].rsplit('/', 1)[-1] for l in main['labels'])}."
    verdict = (f" **{len(errs)} error(s), {len(warns)} warning(s)**" if errs or warns else " No problems found")
    L += [head + verdict + (f" ({len(infos)} note{'s' * (len(infos) != 1)})." if infos else "."), ""]

    L += ["## Structure", "```", *rep["tree"], "```", ""]
    for img in imgs[: (None if detail else 1)]:
        L += [f"## Image `{img['path']}`" + (f" ({img['name']})" if img.get("name") and img["name"] not in ("/", img["path"]) else "")]
        L.append(f"- Axes: {axes_str(img)}  ·  units: " + ", ".join(f"{a['name']}={a['unit'] or '—'}" for a in img.get("axes") or []))
        if img.get("pixel_size"):
            L.append("- Pixel size: " + ", ".join(f"{k} {fmt_len(v['value'], v['unit']) if v['unit'] != 'micrometer' else fmt_num(v['value']) + ' µm'}" for k, v in img["pixel_size"].items())
                     + (f"  ·  anisotropy {img['anisotropy']:.3g}×" if img.get("anisotropy") and img["anisotropy"] != 1 else "  ·  isotropic" if img.get("anisotropy") == 1 else ""))
            L.append("- Physical extent: " + ", ".join(f"{k} {fmt_len(v['value'], v['unit'])}" for k, v in img["extent"].items()))
        tp = img.get("timepoints")
        if tp:
            L.append(f"- Time: {tp['count']} point(s)" + (f", every {fmt_num(tp['interval'])} {SHORT_UNIT.get(tp['unit'], tp['unit'] or '')}" if tp["count"] > 1 else ""))
        if img.get("channels"):
            L.append("- Channels: " + "; ".join(
                f"{c['label'] or '(no label)'}" + (f" #{c['color']}" if c.get("color") else "") +
                (f" window {fmt_num(c['window'][0])}–{fmt_num(c['window'][1])}" if c.get("window") and c["window"][0] is not None else "")
                for c in img["channels"]))
        elif img.get("channel_count"):
            L.append(f"- Channels: {img['channel_count']} (no omero names/colors)")
        lv = [l for l in img["levels"] if l.get("shape")]
        if lv:
            l0 = lv[0]
            stor = f"- Storage: chunks {'×'.join(map(str, l0['chunks']))}"
            if l0.get("shards"):
                stor += f", shards {'×'.join(map(str, l0['shards']))}"
            stor += f" ({fmt_bytes(prod(l0['chunks']) * (l0['itemsize'] or 0))} per chunk uncompressed), {', '.join(l0['codecs']) or 'no compression'}"
            L.append(stor)
            sz = f"- Size: {fmt_bytes(img['uncompressed_bytes'])} uncompressed"
            if img.get("on_disk_bytes") is not None:
                ratio = img["uncompressed_bytes"] / img["on_disk_bytes"] if img["on_disk_bytes"] else None
                sz += f", {fmt_bytes(img['on_disk_bytes'])} on disk ({img['on_disk_method']})" + (f", {ratio:.1f}× compression" if ratio else "")
            L.append(sz + f"; level 0 = {l0['objects_expected']:,} {'shard' if l0.get('shards') else 'chunk'} objects")
        if img.get("sample") and "min" in img["sample"]:
            s = img["sample"]
            L.append(f"- Sample (level {s['level']}, {s['chunks_read']} chunk(s)): range {fmt_num(s['min'])}–{fmt_num(s['max'])}"
                     + (f", 1–99.9% {fmt_num(s['p1'])}–{fmt_num(s['p99_9'])}" if "p1" in s else "")
                     + f", {s['fraction_fill'] * 100:.0f}% fill value")
        if detail and lv:
            L += ["", "| level | shape | scale | translation | chunks | on disk |", "|---|---|---|---|---|---|"]
            for l in img["levels"]:
                if not l.get("shape"):
                    L.append(f"| {l['path']} | MISSING | {l.get('scale')} | | | |")
                    continue
                L.append(f"| {l['path']} | {'×'.join(map(str, l['shape']))} | {', '.join(fmt_num(x) for x in l['scale'] or [])} | "
                         f"{', '.join(fmt_num(x) for x in l['translation'] or []) or '—'} | {'×'.join(map(str, l['chunks']))} | "
                         f"{fmt_bytes(l.get('on_disk_bytes'))} |")
        for lab in img.get("labels", []):
            l0 = next((l for l in lab["levels"] if l.get("shape")), None)
            s = lab.get("sample") or {}
            L.append(f"- Label `{lab['path'].rsplit('/', 1)[-1]}`: {fmt_dtype(l0['dtype']) if l0 else '?'}, {axes_str(lab)}, "
                     f"{sum(1 for l in lab['levels'] if l.get('shape'))} levels"
                     + (f", {s['distinct_labels']} ids in sample" if "distinct_labels" in s else "")
                     + (f", {lab['image_label']['colors']} colors" if lab.get("image_label", {}).get("colors") else ""))
        for t in img.get("tables", []):
            L.append(f"- Table `{t['name']}`: {t.get('encoding') or 'unknown encoding'}" + (f", annotates {t['region']}" if t.get("region") else ""))
        L.append("")
    if not detail and len(imgs) > 1:
        L += [f"_{len(imgs) - 1} more image(s) not shown; ask for detail._", ""]
    if st.get("cors"):
        c = st["cors"]
        L += [f"Access: {st['access']}; browser CORS: {c['status']}.", ""]
    shown = errs + warns + (infos if detail else [])
    if shown:
        L.append("## Findings")
        for f in shown:
            L.append(f"- **{f['severity'].upper()}** `{f['code']}` at `{f['path']}`: {f['message']}  \n  Fix: {f['fix']}")
        if not detail and infos:
            L.append(f"- _{len(infos)} informational note(s) hidden ({', '.join(sorted({i['code'] for i in infos}))}); rerun with --detail._")
    return "\n".join(L)


def build_tree(rep):
    st, imgs = rep["store"], rep["images"]
    name = st["url"].rstrip("/").rsplit("/", 1)[-1] or st["url"]
    T = [f"{name}  [{st['kind']}]"]

    def img_lines(img, prefix):
        out = []
        lv = [l["path"] for l in img["levels"]]
        miss = [l["path"] for l in img["levels"] if not l.get("shape")]
        lvs = f"{lv[0]}…{lv[-1]}" if len(lv) > 2 else ",".join(lv)
        out.append(f"{prefix}├── levels {lvs} ({len(lv)})" + (f"  MISSING: {miss}" if miss else ""))
        if img.get("labels"):
            out.append(f"{prefix}├── labels/ " + ", ".join(l["path"].rsplit("/", 1)[-1] for l in img["labels"]))
        if img.get("tables"):
            out.append(f"{prefix}├── tables/ " + ", ".join(t["name"] for t in img["tables"]))
        if out:
            out[-1] = out[-1].replace("├──", "└──", 1)
        return out

    if st["kind"] == "plate" and rep.get("plate"):
        p = rep["plate"]
        T.append(f"├── rows {p['rows'][0]}–{p['rows'][-1]} × columns {p['columns'][0]}–{p['columns'][-1]}: {p['well_count']} wells" if p["rows"] and p["columns"] else f"├── {p['well_count']} wells")
        T.append(f"│   └── <row>/<col>/<field>  ({'/'.join(map(str, p['fields_per_well']))} field(s) per well)")
        if imgs:
            T.append(f"└── {imgs[0]['path']}  (representative)")
            T += img_lines(imgs[0], "    ")
    elif st["kind"] == "collection":
        T.append("├── OME/" + ("  METADATA.ome.xml" if rep["collection"].get("ome_xml") else ""))
        for k, img in enumerate(imgs):
            last = k == len(imgs) - 1
            T.append(f"{'└' if last else '├'}── {img['path'].rsplit('/', 1)[-1]}  {axes_str(img)}")
            T += img_lines(img, "    " if last else "│   ")
    elif imgs:
        T += img_lines(imgs[0], "")
    return T


# --------------------------------------------------------------------------- main
def read_prefs():
    p = os.path.join(os.getcwd(), "docs", "agents", "ome-zarr.md")
    if not os.path.exists(p):
        return None
    target = None
    for line in open(p, encoding="utf-8"):
        if line.strip().startswith("- target:"):
            target = line.split(":", 1)[1].strip()
    return {"file": p, "target": target}


def inspect(url, args):
    store = Store(url, True if args.anon else None)
    F = Findings()
    got = store.connect()
    if not any(got.values()):
        hint = ""
        if store.protocol == "file" and not store.is_zip and not os.path.exists(store.root):
            raise StoreError(("other", store.root, FileNotFoundError("path does not exist")))
        if store.protocol == "file" and os.path.isdir(store.root):
            kids = [k for k in sorted(os.listdir(store.root)) if k.endswith((".zarr", ".ome.zarr", ".zip"))][:10]
            hint = f" Candidate stores inside: {kids}." if kids else ""
        raise StoreError(("other", store.full(""), FileNotFoundError(
            "no zarr.json, .zattrs, .zgroup or .zarray here; is this the store root?" + hint)))
    node = read_node(store, "")
    ome = node["ome"]
    rep = {"tool": "inspect-ome-zarr", "tool_version": TOOL_VERSION,
           "store": {"url": url, "protocol": store.protocol, "access": store.access,
                     "zarr_format": node["zarr_format"], "ome_version": ome_version(node)},
           "images": [], "plate": None, "collection": None, "preferences": read_prefs()}
    if ome.get("plate"):
        kind = "plate"
        rep["plate"], img = inspect_plate(store, "", node, F, args)
        rep["images"] = [img] if img else []
    elif ome.get("bioformats2raw.layout") is not None:
        kind = "collection"
        rep["collection"], rep["images"] = inspect_collection(store, "", node, F, args)
        if rep["images"] and not rep["store"]["ome_version"]:
            rep["store"]["ome_version"] = rep["images"][0]["version"]
    elif ome.get("well"):
        kind = "well"
        ims = ome["well"].get("images", [])
        for k, im in enumerate(ims[: args.max_images]):
            n = read_node(store, im.get("path"))
            if n:
                rep["images"].append(inspect_image(store, im.get("path"), n, F, args, sample=(k == 0)))
    elif ome.get("multiscales"):
        img = inspect_image(store, "", node, F, args)
        rep["images"] = [img]
        n = len(img["levels"])
        kind = "label image" if ome.get("image-label") else ("multiscale image" if n > 1 else "single-resolution image")
        if img.get("labels") or img.get("tables"):
            kind += " with " + " and ".join(x for x in ("labels" if img.get("labels") else "", "tables" if img.get("tables") else "") if x)
    else:
        kind = "plain zarr group" if node["node_type"] == "group" else "plain zarr array"
        F.add("warning", "NOT_OME", "/", "No OME-Zarr metadata (multiscales, plate, well, bioformats2raw.layout) at the root.",
              "Point at the image/plate root, or add OME metadata.")
        kids = store.ls("", cap=50) if store.protocol == "file" or args.detail else None
        if kids:
            rep["store"]["children"] = [k for k in kids if not k.startswith(".") and k != "zarr.json"]
    rep["store"]["kind"] = kind
    pv = (rep["preferences"] or {}).get("target")
    if pv and rep["store"]["ome_version"] and pv not in ("unknown", rep["store"]["ome_version"]) and not pv.startswith("0.X"):
        F.add("info", "VERSION_VS_REPO", "/", f"Store is {rep['store']['ome_version']}; docs/agents/ome-zarr.md targets {pv}.",
              "Convert before mixing with this repo's data, or read it as-is if the repo also reads this version.")
    meta_name = "zarr.json" if node["zarr_format"] == 3 else ".zattrs"
    if not args.no_cors:
        rep["store"]["cors"] = check_cors(store, meta_name)
    order = {"error": 0, "warning": 1, "info": 2}
    rep["findings"] = sorted(F.items, key=lambda f: order[f["severity"]])
    rep["tree"] = build_tree(rep)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read-only OME-Zarr inspection.")
    ap.add_argument("store", help="path or URL (local dir, .zip, http(s)://, s3://, gs://)")
    ap.add_argument("--detail", action="store_true", help="per-level table, all images, informational notes")
    ap.add_argument("--json", action="store_true", help="print JSON instead of the report")
    ap.add_argument("--json-out", metavar="PATH", help="also write JSON to PATH")
    ap.add_argument("--anon", action="store_true", help="force anonymous access (s3/gs)")
    ap.add_argument("--no-sample", action="store_true", help="do not read any pixel chunks")
    ap.add_argument("--no-size", action="store_true", help="skip on-disk size measurement")
    ap.add_argument("--no-cors", action="store_true", help="skip the browser CORS probe")
    ap.add_argument("--max-list", type=int, default=200_000, help="max local files to walk per level")
    ap.add_argument("--max-images", type=int, default=20, help="max series/fields/labels to inspect")
    args = ap.parse_args(argv)
    try:
        rep = inspect(args.store, args)
    except StoreError as e:
        msg = explain_store_error(e, args.store)
        if args.json:
            print(json.dumps({"tool": "inspect-ome-zarr", "error": msg}, indent=2))
        else:
            print(f"ERROR: {msg}", file=sys.stderr)
        return 1
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, indent=2, default=str)
    print(json.dumps(rep, indent=2, default=str) if args.json else render(rep, args.detail))
    return 0


if __name__ == "__main__":
    sys.exit(main())
