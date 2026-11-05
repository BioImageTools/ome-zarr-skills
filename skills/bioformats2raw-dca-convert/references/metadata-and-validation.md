# Complete DCA metadata and verify the result

Read when preparing the final store. Consult the pinned v0.3 schemas for field
types, enumerations, and conditional requirements rather than copying a
minimal-looking example and assuming it is complete.

## NGFF structure

At every selected image group, retain `attributes.ome.version="0.5"`, axes,
multiscales datasets and coordinate transformations. Arrays must be rank 5 in
TCZYX order, including singleton dimensions. Use consistent lower-case names
`t,c,z,y,x` (or consistent upper-case names); array `dimension_names` must
match image-group axes exactly. Include valid spatial and temporal units and
grounded scale values. Preserve the multi-image or plate hierarchy.

For variable time sampling, the specification permits omitting the time unit
only with `dca.acquisition.time_sampling="variable"`, one non-decreasing UTC
Unix-seconds timestamp per base-level timepoint, and base time scale 1. For
uniform time-lapse data, check the required acquisition time interval against
the NGFF transform. Do not invent an interval, pixel size, or acquisition time
to satisfy validation. Resolve missing calibration, including placeholder-axis
conventions, with the user or authoritative acquisition metadata.

Record the downsampling method actually used; do not label a median or Gaussian
pyramid as mean. Maintain T/C lengths and transforms across resolutions. Check
that at least one resolution has Z, Y, and X all <=2048.

## DCA image-group attributes

Write `attributes.dca` **beside** `attributes.ome` on each multiscales image
group, not inside `ome`, at the store root indiscriminately, or at an array
node. Required content includes:

- `version: "0.3"`, the specification `url`, and `channels`.
  Each channel entry needs `name`, zero-based `index`, and `description`.
  Provide entries corresponding to the actual C axis with unique valid indices.
- `normalization_statistics`, keyed by string channel index. Each entry needs
  `dataset_statistics` containing `p1`, `p5`, `p95`, and `p99` computed from
  that channel across spatial dimensions and time. Use bounded/streaming
  statistics or a documented representative sampling scheme; record sampling
  parameters under its optional `metadata`. Never insert dummy percentiles.
  Optional `timepoint_statistics`, if included, must cover every timepoint.
- The experimental-metadata required blocks: `study`, `biosample`, `specimen`,
  `study_component`, and `provenance`, including their required fields and
  conditional rules. Validate against the v0.3 experimental schema. Block
  names alone or empty objects are not a substitute for that schema.

Derive the experimental record from the curated sibling Parquet, which is
the source of truth, and mirror the same record into the image group's DCA
attributes. For a new dataset, assemble and validate grounded metadata before
writing both representations. Do not treat the image header as evidence for
organism, disease, licence, release date, or channel biology when it lacks
that information. Report the exact missing fields; use only schema-permitted
unknown sentinels where they truthfully apply. Preserve metadata provenance.

When perturbations are present, include the appropriate assignment and
definition. For projected data, consult the v0.3 projection specification for
the sibling-store layout, source relationship and `dca.projection` metadata.
Do not create projections merely to make a conversion pass, and do not attach
projection metadata to an unprojected image. Label image groups are exempt
from DCA image metadata, but still need their NGFF label structure and array
requirements; use maximum or decimation for their pyramids.

## Gate the final result

Use `dca-validate --help` and record the installed distribution/revision.
If it lacks v0.3 support, use a compatible pinned installation within the
authorized environment; do not change the spec version to obtain a pass.
Always pass `--spec-version 0.3` because defaults can target older versions.

Run the validator on the final store, inspect the JSON report and exit status,
and verify that every intended image was discovered. If a converter collection
is not traversed by the installed validator, explicitly validate all image
groups and report this scope rather than accepting zero checked images.
Report MUST errors separately from SHOULD warnings. Use `--strict` only when
strict conformance is requested, or as an additional explicitly labelled check.

Independently inspect each level's real chunk grid, sharding codec and nested
compression, dimensions, and bytes. Decode bounded pixel samples at corners,
center, chunk/shard boundaries and representative T/C positions. Compare the
base against the source and test pyramid values against the documented filter.
Metadata validation alone does not establish pixel completeness or scientific
correctness; missing chunks can read back as fill values.

## Sources (DCA revision 31160de17c9370f953baaebe3e8ef00e2749ec4a)

- [NGFF metadata requirements](https://github.com/chanzuckerberg/dynamic-cell-atlas-specs/blob/31160de17c9370f953baaebe3e8ef00e2749ec4a/docs/v0.3/ome-zarr-metadata.rst).
- [DCA attributes and Parquet](https://github.com/chanzuckerberg/dynamic-cell-atlas-specs/blob/31160de17c9370f953baaebe3e8ef00e2749ec4a/docs/v0.3/dca-metadata.rst).
- [DCA JSON Schema](https://github.com/chanzuckerberg/dynamic-cell-atlas-specs/blob/31160de17c9370f953baaebe3e8ef00e2749ec4a/docs/v0.3/schema.json).
- [Experimental metadata](https://github.com/chanzuckerberg/dynamic-cell-atlas-specs/blob/31160de17c9370f953baaebe3e8ef00e2749ec4a/docs/v0.3/experimental-metadata.rst) and [schema](https://github.com/chanzuckerberg/dynamic-cell-atlas-specs/blob/31160de17c9370f953baaebe3e8ef00e2749ec4a/schema/v0.3/dca_experimental_metadata.yaml).
- [Normalization statistics](https://github.com/chanzuckerberg/dynamic-cell-atlas-specs/blob/31160de17c9370f953baaebe3e8ef00e2749ec4a/docs/v0.3/normalization-statistics.rst).
- [Projections](https://github.com/chanzuckerberg/dynamic-cell-atlas-specs/blob/31160de17c9370f953baaebe3e8ef00e2749ec4a/docs/v0.3/projections.rst).
- [v0.3 validator selection](https://github.com/chanzuckerberg/dynamic-cell-atlas-specs/blob/31160de17c9370f953baaebe3e8ef00e2749ec4a/docs/v0.3/index.rst) and [shared CLI documentation](https://github.com/chanzuckerberg/dynamic-cell-atlas-specs/blob/31160de17c9370f953baaebe3e8ef00e2749ec4a/docs/v0.2/validator.rst).
