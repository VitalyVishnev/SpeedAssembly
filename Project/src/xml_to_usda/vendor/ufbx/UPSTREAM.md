# ufbx provenance

- Upstream: https://github.com/ufbx/ufbx
- Pinned revision: `83bc7cf44f76bc8622de63b809a42b5d557cd733` (v0.21.3)
- License: dual MIT or public domain; retained verbatim in `LICENSE`.
- `ufbx.c` SHA-256: `2614249210F4FA9702206A88284090EB05C94972AC0164E8AC08CA4037BFE664`
- `ufbx.h` SHA-256: `0447274A518C23FF0C9FE623569A778EA453C4D9D61E8034F29AB04BFFE28487`

`_ufbx.c` is the deliberately small CPython boundary. Do not replace it with a
third-party Python wrapper: production workers own only the vendored native
library and serializable geometry/skeleton data cross the process boundary.
