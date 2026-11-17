# PDF parser: STC section ends before NMOT and rear-side electrical data (11.5a.2)

The original 11.5a.1 spatial fallback detected an STC heading but reported duplicate rows for Pmax, Voc, Isc, Vmp and Imp on a real Polish TW Solar 505 W datasheet. The diagnostic also exposed a later heading `CHARAKTERYSTYKA ELEKTRYCZNA (N MOT)`. A word-level boundary detector recognized `NMOT`, not `N MOT` split into multiple PDF words; it could accidentally include another electrical table in the region considered STC.

The spatial fallback now scans **visual rows** for subsequent section headings, including `N MOT` and `TYLNA STRONA`, and truncates the STC region at the heading. A two-line split heading is also handled. Text-row parsing has the equivalent `N MOT` recognition. Genuine duplicate metric rows inside the STC segment remain a hard failure.

Offline regression: original 39 tests + 6 new tests = 45 tests PASS. Full-project test suite must still run in user's repository. A generated, visually inspected, two-page PDF with an `(N MOT)` section produced the expected candidate for the exact 505 W STC column. The actual Soltech PDF was **not available as local bytes** in the build environment, so no claim of exact-file validation is made.

No live network, OCR, automatic importer, Postgres writes, or schema changes. JSON results remain human-review candidates only.
