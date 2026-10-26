# RFC-EDGE-014 — source registry

Each source is pinned to a full SHA, and its licence is read from the licence file at that commit rather than from the brief's table.

| id | repo | pinned sha | pin resolves | licence family from file | rule |
| --- | --- | --- | --- | --- | --- |
| SRC-01 | freqtrade/freqtrade | `b33068949fc16e69e288e0a5bef5bd1f086f0a27` | True | GPL | NO_COPY |
| SRC-02 | jesse-ai/jesse | `5e642997f9623d67b63543962eab46caca30e613` | True | MIT | COPY_WITH_ATTRIBUTION |
| SRC-03 | vnpy/vnpy_ctastrategy | `7a8768de9784dda35a7b261a7ade1dbfbff50919` | True | MIT | COPY_WITH_ATTRIBUTION |
