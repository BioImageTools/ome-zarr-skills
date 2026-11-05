---
name: bioformats2raw-dca-convert
description: Inspect local images or image URLs with bia-remote-metadata for dtype, dimensionality, and axis sizes; recommend chunks and shards; and convert with bioformats2raw to OME-Zarr for Dynamic Cell Atlas specification v0.3 validation. Use when DCA compliance is required, including metadata completion and validation.
---

# Convert an image for DCA v0.3

Target **DCA specification 0.3, OME-NGFF 0.5 and above, Zarr v3**. The generic
bioformats2raw skill's NGFF 0.4 default does not apply. Specification version
and installed validator package version are different identifiers. The linked
v0.3 specification is a draft: record the specification/validator Git revision
and explicitly select `--spec-version 0.3`.

Complete inspection and present the storage recommendation **before** starting
conversion. For a planning-only request, stop after the plan. For an authorized
conversion, proceed with supported settings and identified metadata; ask for
missing scientific information instead of inventing it.

## 1. Inspect the source before choosing sizes

For an HTTP/HTTPS image URL, first follow
[remote inspection](references/remote-inspection.md) using the available
[`bia-remote-metadata`](https://github.com/BioImage-Archive/bia-remote-metadata) tool. Use its
successful per-series metadata to prepare the sizing recommendation without
first downloading the complete source. Preserve warnings, interpretation
profiles, and unresolved pixel/calibration checks in the plan. A URL probe
does not make the URL a supported bioformats2raw input.

Locate the source fileset and retain its companion files. Record versions of
bioformats2raw, Bio-Formats, Java, and the DCA validator; read their installed
help. For local inputs, or after staging a remote fileset for conversion, use
a Bio-Formats reader consistent with the converter. For an available `showinf`
installation, inspect metadata without loading the image:

```bash
showinf -nopix -noflat -omexml-only "/data/input.czi" > "/data/input-inspection.ome.xml"
```

Use a fresh report path outside the source fileset. Parse OME-XML with an XML
parser, respecting its namespace. For each selected `Image/Pixels`, report:

- Source series index/name; source axis order, source rank when exposed by
  the reader, and all axis lengths. OME-XML represents five logical axes even
  for 2D acquisitions: report singleton axes and the number of non-singleton
  axes separately; do not call that count the source rank.
- `Type`, storage bytes per sample, signedness, and RGB/interleaved samples.
  Reconcile `SizeC` and `SamplesPerPixel` with the converter's separated output
  channels. Preserve pixel type unless a scientifically justified conversion
  was requested. Float-to-integer quantization is not a harmless format change.
- `SizeT`, `SizeC`, `SizeZ`, `SizeY`, `SizeX`, and their mapping to output
  `(T,C,Z,Y,X)`. Insert singleton placeholders for absent axes. Do not squeeze
  output or guess ambiguous nonstandard axes. Treat source pyramid levels as
  resolutions, not additional images.
- Physical pixel sizes/units, time interval or timestamps, channel metadata,
  and raw-image versus label semantics. List missing calibration and metadata.

Read a bounded source pixel region to confirm the actual dtype and reader
interpretation when a pixel reader is available. A metadata-only remote plan
must mark this check pending; confirm it after staging and before conversion.
If metadata tools are missing or the axes remain ambiguous,
resolve that before choosing final sizes. Preserve all requested series; plan
heterogeneous series separately rather than assuming one shape for the file.

## 2. Recommend chunks and shards

Read [sizing rules and worked examples](references/storage-planning.md).
Use the **output** dtype and five-dimensional shape. Present a row per image:

`series | dtype/itemsize | source axes/shape | output TCZYX | array bytes | inner chunk TCZYX/bytes | outer shard TCZYX/bytes | expected errors/warnings | conversion route`

Show the arithmetic, small-array exceptions, and estimated shard count. State
whether the plan meets MUST requirements and which SHOULD recommendations it
departs from. Normal validation permits warnings; `--strict` does not. Do not
promise strict success based only on storage settings.

Check disk space and inodes for the output, pyramids, and any intermediate
rewrite. Budget heap, native memory, workers, and writer shard buffers; nominal
shard bytes are not a guarantee of peak memory usage.

## 3. Select a route that the converter can actually write

Verify local help supports NGFF 0.5 and the chosen compression/sharding flags.
The inspected implementation maps `--tile-width`, `--tile-height`, and
`--chunk-depth` to inner X/Y/Z extents and `--shard-width`, `--shard-height`,
and `--shard-depth` to outer X/Y/Z extents, **in pixels, not chunk counts**.
It uses T=C=1 for these chunk/shard axes and has no corresponding time/channel
controls. Do not invent `--shard-time` or silently replace a planned time extent
with 1. Recheck these capabilities against the installed release.

- **Direct spatial route:** use when the planned T/C extents are 1 and the
  converter can produce all required spatial levels with the correct filter.
- **Staged route:** when time/channel chunking or sharding is needed, write
  full-resolution NGFF 0.5 with bioformats2raw, then stream into a fresh final
  store using a Zarr-v3-capable writer supporting explicit 5D inner/outer
  shapes. Rechunk every selected image and retain its hierarchy and metadata.
  Use `--resolutions 1` for an intermediate whose pyramid will be rebuilt.
  Never attempt to rechunk by changing JSON shape fields alone.

For example, a **confirmed** uint16 image shaped `(1,1,128,2048,2048)` can use
this array-layout conversion (it still needs the metadata steps below):

```bash
bioformats2raw --ngff-version 0.5 --resolutions 1 \
  --tile-width 128 --tile-height 128 --chunk-depth 128 \
  --shard-width 2048 --shard-height 2048 --shard-depth 128 \
  --compression zstd --compression-properties level=3 \
  "/data/input.czi" "/data/output.ome.zarr"
```

This is a worked example, not universal settings. Choose fresh destinations;
do not overwrite inputs or prior outputs. Keep logs outside the store and
retain converter exit status, including when piping through `tee`.

Every image needs a level with **all** spatial extents <=2048. One level is
sufficient when the base already qualifies. If downsampling is required, use
mean for raw images and maximum or decimation for labels; preserve T and C.
Document the actual filter and update spatial coordinate transformations.
Prefer factor-two spatial reduction. Do not assume the converter's default
filter satisfies DCA. In the inspected implementation `--downsample-z` uses
median, so it cannot supply DCA's raw-image mean pyramid. Rebuild a mean
pyramid in the staged route when needed, especially when Z exceeds 2048.
For direct XY pyramids, verify the selected filter's mean semantics and edge
handling against the installed implementation before using it.

Read actual written array metadata at **every** level: bioformats2raw clamps
spatial extents to array sizes and can abandon sharding when chunk/shard
divisibility fails. Correct an unsupported layout with a new conversion or
rewrite, not by claiming the requested CLI flags prove the result.

## 4. Complete metadata and validate the final store

Read [DCA metadata and validation](references/metadata-and-validation.md).
Add scientifically grounded calibration, channel/experimental metadata, and
computed normalization statistics. These are required beyond standard
bioformats2raw output; storage compliance alone is insufficient.

Run the installed validator explicitly against v0.3, saving the report outside
the store:

```bash
dca-validate "/data/output.ome.zarr" --spec-version 0.3 --output json \
  > "/data/output.dca-v0.3-validation.json"
```

Check exit status, errors, warnings, discovered image groups, and coverage of
every selected series and level. Also decode representative final chunks and
compare full-resolution samples with the source. Verify pyramids separately.
Only call the output DCA-valid after the actual complete validator run passes.
If blocked by missing metadata or unavailable tools, identify the exact gap
and distinguish an intermediate from a validated deliverable.

Report output/log/report paths, tool and spec revisions, source-to-output
mapping, actual dtype/shape/chunks/shards and their bytes, compression, pyramid
method, metadata provenance, validation result, and any warnings.

Sources: [DCA v0.3](https://github.com/chanzuckerberg/dynamic-cell-atlas-specs/tree/main/docs/v0.3),
[Bio-Formats inspection CLI](https://github.com/ome/bioformats/blob/develop/components/bio-formats-tools/src/loci/formats/tools/ImageInfo.java).
