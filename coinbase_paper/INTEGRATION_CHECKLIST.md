# Deployment and synchronization acceptance checklist

1. Create a private GitHub repo and require branch protection before any secrets are configured.
2. Connect a Supabase project, apply and review the `paper_gate` schema; confirm it is not in Data API exposed schemas. Verify RLS and table privileges using SQL queries.
3. Migrate the *runtime* gate from SQLite to PostgreSQL in atomic transactions before any serverless deployment. Existing SQLite server is NOT compatible with ephemeral Vercel storage.
4. Verify the live Notion Trade Fills data-source schema, especially `Mode`, `Pair`, `Side`, `Source` select options and all property types.
5. Add a read-only Coinbase connector worker; exhaust pagination and record an explicit completeness checkpoint. Treat absent records as unknown if pagination is incomplete.
6. Read all existing Notion fill pages and run `plan_staged_to_notion`. Halt on conflicts, incomplete pagination, or missing required properties. Only create new pages with stable fill keys.
7. Implement durable outbox and retries: write a sync intent transactionally, perform Notion create, and reconcile after timeout before retrying (Notion create is not inherently idempotent).
8. Add authenticated server-to-server endpoints and a separate human approval mechanism; Notion statuses must never confer execution authority.
9. Deploy to Vercel with secrets stored only in protected environment variables. Test health endpoint, auth rejection, durable state across restarts, and duplicate concurrent requests.
10. Keep Coinbase permissions read-only and never expose live order endpoints. Confirm with a test account and review audit logs.

This checklist is not evidence that these steps have been executed.
