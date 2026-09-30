# ADR-0011: Generate the frontend API contract

Use a FastAPI JSON API with a React and TypeScript frontend built by Vite, and SSE for progress. Generate the TypeScript schema from exported OpenAPI rather than hand-writing a second set of endpoint types. Backend contracts therefore remain the source for client shapes, while frontend code owns presentation.

First recorded 2026-09-03 in [commit 3959ee0](https://github.com/eli-jordan/etsy-listing-automation/commit/3959ee0c08172195bc726d81d2c98ed4a4f4efef).
