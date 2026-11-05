# JSON output

`--json` prints, and `--json-out PATH` writes, one object. Stable keys for other
skills (conversion, sharding, validation, cataloguing) to consume. Units are
spec names (`micrometer`), never display symbols. Sizes are bytes.

```text
tool, tool_version
store:
  url, protocol (file|s3|gs|http|https), access, zarr_format (2|3),
  ome_version, kind, cors {url, status, allow_origin}, children? (plain groups)
preferences: {file, target} | null        # from docs/agents/ome-zarr.md
plate: null | {name, rows[], columns[], well_count, field_count, fields_per_well[],
               acquisitions, empty_positions, representative, version}
collection: null | {layout, series[], series_probed, ome_xml, ome_xml_bytes}
images: [ image ]                         # first = representative
findings: [ {severity: error|warning|info, code, path, message, fix} ]
tree: [ str ]                             # the rendered structure tree
```

`image`:

```text
path, name, version, zarr_format, is_label, ndim
axes: [ {name, type, unit} ]
levels: [ {path, shape[], dtype, chunks[], shards[]|null, codecs[], compressed,
           fill_value, itemsize, scale[], translation[]|null, dimension_names,
           uncompressed_bytes, objects_expected, on_disk_bytes, objects_present,
           size_method ("exact" | "estimated from N of M objects" | ...)} ]
pixel_size: {axis: {value, unit}}         # level 0, space axes
extent:     {axis: {value, unit}}         # shape × scale, level 0
anisotropy                                # max / min spatial pixel size
channel_count, timepoints {count, interval, unit}
channels: [ {label, color, active, window [start, end], range [min, max]} ]
uncompressed_bytes, on_disk_bytes, on_disk_method ("exact" | "estimated, inferred")
sample: {level, chunks_read, values, min, max, fraction_fill, p1, p99_9
         | distinct_labels, non_integer_values | skipped}
image_label: {colors, properties, source}  # labels only
labels: [ image ]                          # nested, is_label = true
tables: [ {name, path, encoding, region} ]
```

`scale` is already multiplied by any multiscale-level `coordinateTransformations`
scale. `objects_expected` counts shards when sharded, else chunks.

Errors: on exit code 1 with `--json`, the output is `{"tool": ..., "error": msg}`.
