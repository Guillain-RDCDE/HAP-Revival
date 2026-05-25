# API spec

This directory will hold a machine-readable specification of the HAP ScalarWebAPI as we map it, plus annotated request/response examples.

Current state: **stub**. The catalog lives in [`../research/api-method-catalog.md`](../research/api-method-catalog.md) as a hand-maintained markdown table. Once that stabilizes, it will be promoted to a proper OpenAPI 3.1 spec here.

Planned files:

- `openapi.yaml` — the spec proper.
- `examples/` — annotated request/response pairs per method.
- `schema/` — JSON schema definitions for the request/response shapes (the URI scheme `audio:track?id=N`, the `coverArtUrl` format, etc.).

If you want to start the OpenAPI conversion: open an issue with the proposed structure first. The spec should be derivable from the markdown catalog mechanically, not curated by hand.
