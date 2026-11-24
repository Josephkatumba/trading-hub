"""TRADEDEN product layer (Phase 1).

Thin, read-mostly modules that turn the existing engine, research and qualification
records into product concepts without changing those records:

- ``plans``             subscription plan catalogue and capabilities (billing inactive)
- ``evidence``          product-facing strategy evidence tiers (EXPERIMENTAL / VALIDATED /
                        PRODUCTION / ARCHIVED), derived only from recorded evidence
- ``execution_policy``  fail-closed execution gate, emergency stop and audit log; no broker calls
- ``api``               read-only ``/api/platform/*`` routes

Nothing here sends orders, charges money or rewrites research or signal history.
"""
