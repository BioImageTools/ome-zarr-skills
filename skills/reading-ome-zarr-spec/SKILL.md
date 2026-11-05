---
name: reading-ome-zarr-spec
description: Use when working with OME-Zarr / OME-NGFF data or code (zarr.json, .zattrs, multiscales, omero, labels, plate/well, bioformats2raw layout) and you need to check what the specification actually says for the version in use.
---

# Reading the OME-Zarr Spec

Fetch the official spec for the version in play instead of relying on memory.
Versions differ in important ways (e.g. 0.4 is Zarr v2 with `.zattrs`;
0.5+ is Zarr v3 with `zarr.json` and an `ome` key).

## 1. Infer the version

Look, in order, until one hits:

1. Explicit mention in the conversation or task ("0.4 dataset", "v0.5 writer").
2. `docs/agents/ome-zarr.md` in the repo (written by `/setup-ome-zarr-skills`): its `target` version, plus any RFCs it lists.
3. Data on disk: `zarr.json` → `attributes.ome.version`; `.zattrs` → `multiscales[0].version` (or `plate.version`, `image-label.version`).
4. Code/config: version strings in writers, tests, fixtures, or pinned libraries (`ome-zarr-py`, `ngff-zarr`, `iohub`, `bioformats2raw`).
5. Nothing found → read the index page (section 2) for the current released version, use it, and say so.

## 2. Fetch the spec

Build the URL from the version string; this works for any version, including
ones released after this skill was written:

    https://ngff.openmicroscopy.org/specifications/<version>/index.html

e.g. `.../specifications/0.4/index.html`, `.../specifications/0.6/index.html`.
Use `dev` for the unreleased draft; its version number may skip ahead of
current+0.1, so read the number off the page rather than assuming it.

If that URL 404s, or you need to know which version is current, read the index
and follow its links: https://ngff.openmicroscopy.org/specifications/index.html
(it states "The current released version of the OME-Zarr specification is X").
Never assume a version is the newest; check the index. If the named version
404s and is not on the index, tell the user it is unpublished, show the index's
list, and use the current release unless they say otherwise.

Use WebFetch (or `curl`) on the URL and read the section relevant to the task
(multiscales, coordinate transformations, omero, labels, plate/well, bf2raw).
Quote the spec when the answer matters.

## Common mistakes

- Assuming 0.4 layout (`.zattrs`, Zarr v2) when the data is 0.5+ (`zarr.json`, Zarr v3), or vice versa.
- Reading `latest` or `dev` when the user is on an older pinned version.
- Guessing the version when a `zarr.json` / `.zattrs` is right there to check.
