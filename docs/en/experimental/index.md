# Experimental APIs

`sopran.experimental` holds research models and analysis steps that are organized well enough to try on other data.
Unlike the regular instrument APIs, names, defaults, and storage formats may change or disappear without notice, and the physical correctness of results is not guaranteed.

```bash
python -m pip install -e ".[kaguya,viz,experimental]"
```

`import sopran` alone does not load any experiment. Import the module you need explicitly.

## Inventory

| Topic | Module | Page |
|---|---|---|
| Electron reflectometry (ER) estimators | `sopran.experimental.electron_reflection` | [Electron Reflectometry](er.md), [ER Model Definitions](er-models.md) |
| KAGUYA ER input preparation and estimator calls | `sopran.experimental.kaguya.er.KaguyaErInstrument` | [Electron Reflectometry](er.md) |
| ER input parts (16 s windows, paired distributions, SVM3D connection screening) | `sopran.experimental.kaguya.er_windows`, `electron_reflection.maps`, `moon.connection` | [ER Full-Period Batch](er-batch.md) |
| ER full-period batch (daily shards, Slurm) | `python -m sopran.experimental.kaguya.er_batch` | [ER Full-Period Batch](er-batch.md) |
| Tsunakawa SVM3D shell grid and field-line tracing | `sopran.experimental.moon.svm3d` | — |
| Wave candidate detection, ridge tracking, clustering | `sopran.experimental.waves` | [Wave Candidates](waves.md) |
| KAGUYA WFC detection presets and quality masks | `sopran.experimental.kaguya.waves` | [Wave Candidates](waves.md) |
| Pitch-angle spectra in the dHT frame | `sopran.experimental.kaguya.dht` | [dHT Frame](dht.md) |
| Spacecraft potential proxies, PACE low-level tables | `sopran.experimental.kaguya.spacecraft_potential`, `kaguya.pace_lowlevel` | [Spacecraft Potential Proxies](spacecraft-potential.md) |
| Mirror-transmission comparison estimator | `sopran.experimental.electron_reflection.mirror_transmission` | [ER Model Definitions](er-models.md) |
| Test-particle orbits, closed-field islands, field residuals, environment-response regression | `sopran.experimental.moon.test_particle`, `moon.closure`, `kaguya.field_residual`, `statistics.ridge` | [Field Models And Orbits](field-models.md) |

## Boundary with the regular API

PACE, LMAG, and LRS retrieval, calibration, native bins, coordinate transforms, the Store, PlotStack, and Moon maps stay at the regular entry points.
ER estimates are not instrument observations, so there is no `spn.kaguya.er` entry point, and ER types and functions are not re-exported under `spn`.

Dependencies point one way, from experiments to the regular API. The regular API never imports experiments, and
`tests/test_experimental_boundary.py` checks this boundary. When saving experimental results in the Store, use dataset IDs that start with
`experimental.` so they never mix with regular products.

Experiments that used to live in `sopran.analysis.electron_reflection`, `sopran.analysis.waves`, `sopran.missions.kaguya.er*`,
and `sopran.bodies.moon.svm3d` have moved to the places above. No aliases for the old names remain.

## Promote, keep, or retire

The purpose, open questions, promotion requirements, and last review date of each experiment are tracked in
`src/sopran/experimental/README.md`. They are reviewed before each release; experiments promoted to the regular API
get types, units, sources, regression tests, and a stated validation scope.

Runs over specific periods, comparison figures, interpretations of results, and literature surveys are recorded in each study's working directory
(`working/`), not in the public documentation. This section covers only how to use the experimental APIs and their limits.
