# API spec

A machine-readable specification of the HAP **ScalarWebAPI** — to come.

**Current state: stub.** The live source of truth is the hand-maintained catalog at
[`../research/api-method-catalog.md`](../research/api-method-catalog.md) (~30 methods, validated
against a real device). Once it stabilizes it gets promoted to a proper OpenAPI 3.1 spec here.

**Planned layout:**

- `openapi.yaml` — the spec proper.
- `examples/` — annotated request/response pairs per method.
- `schema/` — JSON Schema for the request/response shapes (the `audio:track?id=N` URI scheme, the `coverArtUrl` format, …).

The spec should be **derivable from the markdown catalog mechanically**, not curated by hand. If
you want to start that conversion, open an issue with the proposed structure first.
