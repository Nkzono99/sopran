# License And Porting

SOPRAN's original code and documentation are released under the Apache License 2.0 (`LICENSE`, `NOTICE`).
Project metadata, `LICENSE`, `NOTICE`, and `THIRD_PARTY_NOTICES.md` are kept consistent.

## Porting SPEDAS behavior

SOPRAN follows IDL SPEDAS behavior for KAGUYA processing and similar work. No SPEDAS or PySPEDAS source is currently copied.

| Subject | Policy |
|---|---|
| New SOPRAN code | Apache-2.0 |
| SPEDAS behavior | Used to understand specifications and as a reference for agreement tests |
| MIT-licensed SPEDAS and PySPEDAS routines | May be ported. Copied or derivative parts keep the original copyright and MIT permission notice, with `SPDX-License-Identifier: Apache-2.0 AND MIT` and their source |
| GPL or NASA Open Source Agreement external components | Not copied into the core package without a separate license review |
| External data | The provider's terms are recorded in dataset manifests |

Ported files state the upstream routine, the upstream commit or release, and whether they are a clean reimplementation, a behavior-compatible rewrite, or a direct translation.
Where possible, implementations are rebuilt in Python and Rust from public instrument specifications, papers, and golden tests. When compared with SPEDAS,
the SPEDAS version and routine path are recorded. Third-party fragments are kept separate so they can be audited, replaced, or removed without changing the public API.

The license findings and the full policy are in `THIRD_PARTY_NOTICES.md`.
