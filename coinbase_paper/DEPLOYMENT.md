# Vercel + Supabase deployment checklist (not deployed)

This repository remains a **local SQLite prototype**. `supabase_schema.sql` is a proposed PostgreSQL schema, not a completed migration or integrated storage adapter. **Do not deploy `server.py` on Vercel with local SQLite**: filesystem state is ephemeral and concurrent execution would violate the approval gate's persistence assumptions.

## Required steps

1. Create a **private** GitHub repository named `KodeE3/coinbase-paper-gate` and push the reviewed project files. No credentials in Git.
2. Connect a Supabase project. Apply and verify `supabase_schema.sql` in a controlled environment, check RLS/advisors, and keep schema `paper_gate` unexposed. Never place service-role keys in browser code.
3. Implement a PostgreSQL storage adapter using database transactions and row-level locks. Keep proposal approval and simulated fill creation atomic, with one-open-position and daily-loss enforcement inside a transaction.
4. Replace the built-in development HTTP server with a Vercel-compatible runtime and server-side bearer-token verification. Add replay protection, rate limits, and separate cron authentication. Disable all exchange trading endpoints.
5. Connect Coinbase using **read-only credentials** or the connected Coinbase tool, with bounded pagination and deduplication; reconcile historical coverage before computing realized P&L.
6. Implement Notion read/write reconciliation with exact database IDs and idempotent scan/fill keys; do not treat a Notion checkbox as a trusted authorization event.
7. Run migration, concurrency, replay, integration, and smoke tests. Deploy a protected preview before production. Verify persistent writes across separate requests and deploys.

## Environment variables (names only)

`DATABASE_URL`, `PAPER_API_TOKEN`, `CRON_SECRET`, `NOTION_TOKEN`, `COINBASE_READ_ONLY_API_KEY`, `COINBASE_READ_ONLY_API_SECRET`.

Use provider-managed secrets. Do not paste secrets in chat or save them in Notion.

## Safety

No live-order code is included or authorized. All fills in the approval engine are simulations. No production readiness claim until deployed end-to-end checks pass.
