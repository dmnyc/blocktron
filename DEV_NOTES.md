# BlockTron Dev Notes

## Subway Mode Memory & Display Stability (Feb 2026)

### Problem

After running in subway mode for extended periods, the LED display degraded:
- Color circles appeared before labels
- Blank gaps appeared before arrival times
- Overall refresh slowed down progressively

### Root Cause

`subway_setup_display()` was called every 10 seconds on line cycle and was recreating all display objects from scratch each time:

1. **displayio object churn**: New `Bitmap`, `Palette`, and `TileGrid` objects were allocated for the circle and arrow every cycle. CircuitPython's garbage collector couldn't keep up with the allocation rate.

2. **Unbounded `_text` list growth**: Every call to `matrixportal.add_text()` appends a new entry to the internal `_text` list. With two `add_text()` calls per 10-second cycle, this list grew by ~720 entries/hour. The growing list slowed splash group lookups and consumed memory.

3. **Insufficient GC frequency**: Garbage collection only ran every 300 seconds and only when free memory dropped below 90% -- far too infrequent given the allocation rate.

### Fix

**Bitmap/TileGrid reuse (circle + arrow):**
- Circle bitmap, palette, and TileGrid are created once on first call
- Circle color changes are done by rewriting `palette[1]` (single assignment)
- Arrow bitmap is created once; direction changes rewrite pixels in place via `_subway_arrow_bmp[col, row]`

**Text layer reuse (label + time):**
- `add_text()` is called exactly once during init for both the line label and arrival time
- On subsequent cycles, the label is repositioned by:
  1. Removing the old label object from `splash`
  2. Nullifying `_text[idx]["label"]` so MatrixPortal treats it as needing rebuild
  3. Updating `_text[idx]["position"]` to the new coordinates
  4. Calling `set_text()` which rebuilds and re-appends at the correct position
- The `_text` list never grows beyond its initial size

**Aggressive GC:**
- `gc.collect()` runs unconditionally every loop iteration (every 0.5s) in subway mode
- Additional `gc.collect()` after each API fetch to reclaim response/JSON temporaries
- `gc.collect()` at the end of `subway_setup_display()` after each cycle

### Key Globals for Display Reuse

```python
_subway_circle_bmp   # Bitmap object, written once, color via palette swap
_subway_circle_pal   # Palette object, [1] rewritten for color changes
_subway_arrow_bmp    # Bitmap object, pixels rewritten for direction changes
_subway_initialized  # Gates first-time vs update path
subway_label_index   # Fixed index into matrixportal._text (never changes after init)
subway_time_index    # Fixed index into matrixportal._text (never changes after init)
```

### Other Fixes in This Series

- **Blank instead of dashes**: When no arrival data exists, display shows empty string (`""`) instead of `"--"` or `"----"`
- **Direction-aware display**: Skips toggling to a direction with no data; starts each line cycle on whichever direction has arrivals (prefers N)
- **Line skip**: Lines with zero arrivals in both directions are skipped entirely during cycling

### Verification

Ran overnight in subway mode with no performance degradation. Memory stays stable as confirmed by per-cycle logging: `Subway display: <line> (mem: <bytes> bytes)`
