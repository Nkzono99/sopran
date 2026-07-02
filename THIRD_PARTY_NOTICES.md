# Third-Party Notices and Porting Policy

SOPRAN is licensed under Apache-2.0 for original SOPRAN code and
documentation.

This repository currently does not include copied SPEDAS or PySPEDAS source
code. Future ports of SPEDAS routines must follow the policy below.

## SPEDAS / PySPEDAS

Primary license findings as of 2026-07-02:

- The IDL SPEDAS `spedas/bleeding_edge` repository states that, unless
  otherwise indicated, MIT license terms apply to the SPEDAS source code:
  https://github.com/spedas/bleeding_edge/blob/master/LICENSE.txt
- PySPEDAS is distributed under MIT license terms:
  https://github.com/spedas/pyspedas/blob/master/LICENSE.txt
- The IDL SPEDAS tree also identifies exceptions, including GPL-licensed
  code in `external/aacgm_v2/astaog.pro`, BSD-licensed `mgunit.sav`, and
  NASA Open Source Agreement 1.3 references for NASA CDAWeb/CDAS-related
  external directories.

## Policy

- MIT-licensed SPEDAS/PySPEDAS routines may be studied, ported, or adapted
  into SOPRAN, but the original copyright and MIT permission notice must be
  retained for copied or derivative portions.
- Apache-2.0 should remain the project-level license for SOPRAN original
  code. SPEDAS-derived files should carry SPDX and provenance comments such
  as `SPDX-License-Identifier: Apache-2.0 AND MIT` when they include
  derivative material.
- Do not copy GPL-licensed or NASA Open Source Agreement licensed external
  SPEDAS components into the Apache-2.0 core package without a separate
  license review.
- Prefer clean Python/Rust implementations from public instrument/data
  specifications, papers, and golden tests. When behavior is compared with
  SPEDAS, document the tested SPEDAS version and routine path.
- Keep third-party source fragments isolated enough that they can be audited,
  replaced, or removed without changing the SOPRAN public API.

This file is an engineering policy note, not legal advice.
