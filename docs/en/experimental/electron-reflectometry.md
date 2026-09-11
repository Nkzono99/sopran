# Experimental Electron Reflectometry

ER estimates a reflection barrier from an energy-pitch distribution.
Numerical fit success does not establish physical magnetic-field accuracy.

```python
import sopran as spn
from sopran.experimental.kaguya.er import KaguyaErInstrument

mission = spn.Kaguya()
er = KaguyaErInstrument(mission)
result = er.effective_field.fit_timeseries(
    spn.day("2008-04-26"), integration="16s", workers=3,
)
result.plot(y="effective_field")
```

This uses the global-joint model, not the Halekas binary-distribution estimator.
Install `kaguya`, `viz`, and `experimental` extras as needed. Prepared pitch counts
can instead be passed to `er.effective_field.fit(...)`. Independent model inputs
and estimators are available from `sopran.experimental.electron_reflection`.

`mirror_ratio` is $R_m=B_{\mathrm{eff}}/B_{sc}$; `effective_field` is in nT and
is not a lunar-surface vector. `delta_u_eff` is an effective energy term in eV,
not an independently validated absolute surface potential. Retain model, quality,
support, beam and bound flags. Do not interpret $R_m\le1$ as a direct crustal-field
measurement or combine success labels from different models indiscriminately.

Default Store IDs are `experimental.kaguya.er.effective_field` and
`experimental.kaguya.er.global_joint_effective_field`. Schemas reside in
`sopran.experimental.kaguya.schema`, outside the built-in instrument inventory.
