# Knowledgebase: OME-Zarr & Bioimage Analysis

A high-level primer to give an agent working context. It is not a spec — when exact
field names or constraints matter, check the official OME-NGFF specification at
https://ngff.openmicroscopy.org and the source code of the tool in question.

---

## 1. The domain in one paragraph

Bioimage analysis turns microscopy images into quantitative biological information.
Images come from many modalities (widefield and confocal fluorescence, light-sheet,
whole-slide imaging, high-content screening, spatial transcriptomics such as ISS/FISH,
electron microscopy). Datasets range from megabytes to many terabytes, are often
multi-dimensional, and are increasingly processed on HPC clusters or in the cloud
via workflow managers such as Nextflow. The recurring problems are: reading
proprietary formats, handling data larger than memory, keeping metadata (pixel size,
channels, time) attached to the pixels, and making pipelines reproducible and FAIR.

---

## 2. Core image concepts

- **Dimensions**: microscopy images are up to 5D, conventionally **T, C, Z, Y, X**
  (time, channel, depth, rows, columns). Many datasets have singleton dimensions.
  Axis order differs between tools — never assume it, read it from metadata.
- **Pixel/voxel size**: the physical size of one pixel (e.g. 0.325 µm in X/Y,
  2 µm in Z). Z spacing is often much coarser than X/Y (anisotropy). Analysis results
  in physical units depend on this being correct.
- **Data type (dtype)**: typically `uint8`, `uint16` (most common for raw
  fluorescence), `float32` (after processing), or integer types for label images.
  Preserve dtype unless a step deliberately changes it; avoid silent clipping/overflow.
- **Channels**: each channel is usually one fluorophore/stain/marker, with a name,
  colour and display range used for visualisation.
- **Tiles / fields of view**: large samples are imaged as many overlapping tiles that
  must be stitched; HCS acquires multiple fields per well per plate.
- **Label image**: an integer image where each object (cell, nucleus) has a unique ID
  and 0 is background. The standard output of instance segmentation.
- **Pyramid / multiscale**: the same image stored at successively downsampled
  resolutions, so viewers and some algorithms can work at coarse levels.

---

## 3. File formats

| Format | What it is | Notes |
|---|---|---|
| Vendor formats (`.czi`, `.nd2`, `.lif`, `.vsi`, `.ims`, …) | Proprietary instrument output | Read via Bio-Formats or vendor-specific Python readers |
| **OME-XML** | XML metadata model from the Open Microscopy Environment | Describes instrument, channels, pixel sizes, planes; can be embedded or companion |
| **OME-TIFF** | TIFF with OME-XML in the header | Monolithic, widely supported; can be tiled and pyramidal; poor for parallel writes and cloud access |
| **Zarr** | Generic chunked, compressed N-dimensional array storage | Not imaging-specific on its own |
| **OME-Zarr** (OME-NGFF) | Zarr + OME metadata conventions | Cloud-native, chunked, parallel-friendly; the community's "next-generation" format |
| HDF5 / N5 | Older chunked containers | Still used (e.g. BigStitcher/BigDataViewer, Imaris) |

**Bio-Formats** (Java) reads ~150 formats into the OME data model. **bioformats2raw**
converts them to OME-Zarr, **raw2ometiff** converts that onward to OME-TIFF.

---

## 4. Zarr basics

- A Zarr store is a hierarchy of **groups** (like folders) and **arrays**.
- Arrays are split into **chunks**; each chunk is compressed independently
  (e.g. Blosc, Zstd) and stored as a separate object/file. Only the chunks you touch
  are read or written — this is what makes huge data and parallel processing practical.
- Metadata is JSON:
  - **Zarr v2**: `.zgroup`, `.zarray`, `.zattrs`
  - **Zarr v3**: a single `zarr.json` per group/array
- **Sharding (Zarr v3)**: many chunks are packed into one **shard** object to reduce
  file counts on filesystems and object stores. Chunk = unit of read; shard = unit of
  write.
- **Stores**: local filesystem, S3/GCS/HTTP, zip, in-memory. Same API regardless.
- **Concurrency rule of thumb**: parallel writers are safe if each writes to
  *different* chunks (v2) or *different* shards (v3). Two writers touching the same
  chunk/shard will corrupt or lose data unless coordinated.
- **Icechunk**: a transactional storage engine for Zarr v3 that adds commits,
  version history and safe concurrent writes on top of object storage.

Python libraries: `zarr` (zarr-python), `tensorstore` (Google, fast, many backends),
`dask.array` (lazy, parallel computation over chunks).

---

## 5. OME-Zarr structure

OME-Zarr = Zarr + standard metadata stored in group attributes (under the `"ome"` key
in v0.5+). A minimal single image looks like:

```
image.zarr/
├── zarr.json            # group metadata incl. "ome": {"version", "multiscales", "omero"}
├── 0/                   # full-resolution array
├── 1/                   # downsampled ×2 (typically in X/Y)
├── 2/                   # downsampled ×4 ...
└── labels/              # optional segmentation label images
    └── nuclei/          # itself a multiscale image with "image-label" metadata
```

Key metadata blocks:

- **`multiscales`**: lists the resolution levels (`datasets`), their `path`s, the
  **`axes`** (name, type `time`/`channel`/`space`, unit) and per-level
  **`coordinateTransformations`** (`scale`, optional `translation`) that map array
  indices to physical space. Level `0` is full resolution.
- **`omero`**: (transitional) rendering hints — channel names, colours, display windows.
- **`labels`** / **`image-label`**: links images to their segmentation masks,
  with optional colours/properties per label value.
- **High-content screening (HCS)**: `plate.zarr/<row>/<column>/<field>/`, with
  `plate` metadata at the top, `well` metadata per well, and each field an image.
- **bioformats2raw layout**: a wrapper group holding multiple series (`0/`, `1/`, …)
  plus the original OME-XML in `OME/METADATA.ome.xml`.

### Spec versions (as of late 2026)

- **0.4** — Zarr v2. Still the most widely deployed; many tools read only this.
- **0.5** — Zarr v3 (`zarr.json`, sharding possible), metadata moved under `"ome"`.
- **0.6** — adds RFC-5: named coordinate systems and richer transformations
  (affine, rotation, displacement fields, sequences), relevant for registration
  and multi-modal alignment. Tool support is still catching up.
- A future **1.0** is planned (e.g. collections).

Always check which version a dataset uses and which versions a tool supports.

---

## 6. Tooling ecosystem

- **Conversion**: bioformats2raw, `ome-zarr-py`, `ngff-zarr`, `bioio`, `tifffile`
  (excellent for TIFF/OME-TIFF in Python), `aicsimageio` (older, superseded by bioio).
- **Visualisation**: napari (+ napari-ome-zarr), Fiji/ImageJ (+ MoBIE, BigDataViewer,
  N5/Zarr plugins), vizarr and Neuroglancer (browser), OMERO (server), QuPath (WSI).
- **Data management**: OMERO (image database/server, imports via Bio-Formats),
  BioImage Archive / IDR for public data.
- **Spatial omics**: SpatialData (Python, builds on OME-Zarr for images/labels plus
  points, shapes and tables), Squidpy, scverse ecosystem.
- **Workflows**: Nextflow / nf-core (DSL2 modules), Snakemake, Galaxy.

### Community effort & cutting-edge work: BioImageTools

**https://github.com/BioImageTools** is a shared GitHub organisation for work on
OME-Zarr and scalable, FAIR bioimage analysis workflows. It grew out of the
OME-NGFF workflows hackathons at the BioVisionCenter (UZH), held yearly since 2023,
and is where much of the newest community work appears before it reaches stable
releases or formal specs. Interests include tools that read/write OME-Zarr,
OCI containers, Nextflow modules and subworkflows, Galaxy and Fractal integrations,
OME-Zarr examples, performance benchmarks, and evaluation of tool support for
newer OME-Zarr versions.

Repositories worth knowing (check the org for the current list):

- `ome-zarr-skills` — agentic skills for working with OME-Zarr (directly relevant
  to agents)
- `ome-zarr-image-analysis-nextflow` — basic example of OME-Zarr in a Nextflow pipeline
- `nextflow-modules` — nf-core-compatible bioimage modules
- `nf-module-aggregator` — catalogue of Nextflow modules across repositories
- `fractal-multistep-nextflow` — running Fractal tasks via Nextflow
- `ngff-transformations` — examples around NGFF coordinate transformations
- `zarr-convention-provenance` — convention for recording workflow provenance
  (software, inputs, checks) in Zarr
- `capability-manifest` — describing what tools/viewers support
- `ome-zarr-fiji-java` — OME-Zarr support in Fiji/ImageJ and BigDataViewer
- `biomero-schema` — spec for BIOMERO (OMERO-integrated) workflows

When the agent needs up-to-date conventions, examples or tool-support status that
may post-date this file, look here (and at the image.sc forum, `ome-ngff` tag)
before falling back on general knowledge.

---

## 7. A typical analysis pipeline

1. **Ingest / convert** — vendor format → OME-TIFF or OME-Zarr; import to OMERO.
2. **Preprocessing**
   - Illumination / flat-field correction (e.g. BaSiC)
   - Denoising (Noise2Void, CAREamics, N2N)
   - Deconvolution (DeconvolutionLab2, deconwolf, CLIJ2-FFT)
   - Background subtraction
3. **Stitching** — assemble tiles into a mosaic (BigStitcher, ASHLAR).
4. **Registration** — align rounds/cycles, timepoints or modalities
   (rigid → affine → non-rigid; e.g. for multi-round ISS/FISH or multiplex IF).
5. **Segmentation** — classical (thresholding, watershed) or deep learning
   (Cellpose, StarDist, empanada for EM, etc.) → label images.
6. **Feature extraction / quantification** — per-object intensity, morphology,
   texture, counts (CellProfiler, scikit-image `regionprops`) → tables.
7. **Domain-specific steps** — e.g. spot detection and barcode decoding against a
   codebook for spatial transcriptomics; cell–gene assignment.
8. **Visualisation, QC and export** — overlays, summary tables, AnnData/SpatialData.

Each step usually maps to one or more workflow modules.

---

## 8. Processing large images: patterns to know

- **Work chunk-wise, lazily**: never load a full multi-TB array into memory; use
  Dask/tensorstore or explicit block iteration.
- **Align work to chunks**: processing blocks should align with (multiples of) the
  storage chunks/shards so that each worker writes whole, disjoint units.
- **Halos / overlaps**: neighbourhood operations (filtering, deconvolution,
  segmentation) need overlapping tiles; process with a margin, then crop or merge.
  Segmentation across tiles needs label stitching/relabelling to keep IDs unique.
- **Per-plane / per-channel / per-timepoint parallelism**: many steps are
  embarrassingly parallel along T, C or Z.
- **Write metadata last**: write the arrays first, then the multiscales/OME
  metadata, so a partially written dataset is not mistaken for a complete one.
- **Regenerate pyramids** after modifying full-resolution data.

---

## 9. Guidance for the agent

- Read axes, dtype, shape, chunking and physical scale from metadata before writing
  any processing code; do not hard-code `TCZYX` or pixel sizes.
- Distinguish **array index space** from **physical space**
  (`coordinateTransformations`). Mixing them is a common source of bugs.
- Preserve or correctly update metadata on output (axes, scale, channel names,
  OME version). Outputs should be valid OME-Zarr/OME-TIFF, not bare arrays.
- Be explicit about which OME-Zarr version (0.4/0.5/0.6) and Zarr version (v2/v3)
  code reads and writes.
- Prefer established libraries over hand-written format code.
- Label images are integer-typed; never interpolate them (use nearest-neighbour when
  resampling).
- When unsure about a spec detail, say so and point to the spec rather than guessing.

---

## 10. Glossary

| Term | Meaning |
|---|---|
| NGFF | Next-Generation File Format — the community spec process; OME-Zarr is its implementation |
| FOV | Field of view; one camera acquisition position |
| HCS | High-content screening (plates, wells, fields) |
| WSI | Whole-slide imaging (digital pathology) |
| ISS / FISH | In situ sequencing / fluorescence in situ hybridisation (spatial transcriptomics) |
| Codebook | Mapping from multi-round fluorescence barcodes to genes |
| PSF | Point spread function; needed for deconvolution |
| ROI | Region of interest |
| Instance vs semantic segmentation | Unique ID per object vs one class per pixel |
| FAIR | Findable, Accessible, Interoperable, Reusable |
| Chunk / shard | Unit of storage/read / group of chunks forming one write object (Zarr v3) |
