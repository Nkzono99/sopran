# Time, Units, And Frames

SOPRAN public APIs use half-open UTC ranges:

```python
time = spn.period("2008-02-01", "2008-02-02")
day = spn.day("2008-02-01")
month = spn.month("2008-02")
year = spn.year("2008")
```

The interval is `[start, stop)`. This avoids double-counting records at
boundaries when appending daily or monthly shards.

Coordinate frames and units are still early-stage. The design goal is to avoid
reimplementing established space-physics and planetary geometry libraries. SPICE
and SpacePy-family tools should be used for kernel-backed geometry and common
coordinate transforms where they fit.
