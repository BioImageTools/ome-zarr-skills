# OME-Zarr preferences

Written by `/setup-ome-zarr-skills` on YYYY-MM-DD. Edit by hand freely.
Skills read this file when present; when a field is `unknown` they infer from context.

## Spec version

- target: 0.X
- reason: why this version (data on disk, library pins, downstream consumers)
- also_read: none
- spec: https://ngff.openmicroscopy.org/specifications/0.X/index.html

## RFCs in use

None.

<!-- or one bullet per RFC:
- RFC-N "Title" (status SN as of YYYY-MM-DD): how this repo uses it.
  https://ngff.openmicroscopy.org/rfc/N/index.html
-->

## Domain

- modality: unknown
- axes: unknown
- units: unknown
- dtypes: unknown
- typical_size: unknown
- extras: none  <!-- omero, labels, plate/well, bioformats2raw.layout -->
- storage: unknown  <!-- local, s3, gcs, zip; chunk/shard preferences -->

## Notes

Free-form conventions skills should respect (naming, directory layout, validators, libraries to prefer).
