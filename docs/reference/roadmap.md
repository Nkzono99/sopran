# Roadmap

Near-term implementation priorities:

- KAGUYA ESA1 calibration application and SPEDAS parity tests. PACE FOV / INFO
  table readers are present; applying them to `energy_flux`, energy coordinates,
  look-angle coordinates, and golden tests is next.
- ARTEMIS raw discovery and CDAWeb/HAPI integration.
- Store registry and richer provenance.
- Project and case defaults for frame, region, and cache policy.
- Moon DEM/SVM data loading and projection metadata.
- Terrain-aware shadow and illumination calculations.
- Rust backend stages for expensive decode and batch products.
