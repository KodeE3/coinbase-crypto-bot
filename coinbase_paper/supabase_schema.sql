-- Deployment candidate. Apply only after selecting and reviewing a Supabase project.
-- No client Data API grants; all tables live in an unexposed private schema.
BEGIN;
CREATE SCHEMA IF NOT EXISTS paper_gate;
REVOKE ALL ON SCHEMA paper_gate FROM PUBLIC, anon, authenticated;
CREATE TABLE IF NOT EXISTS paper_gate.proposals (
 id text PRIMARY KEY,
 pair text NOT NULL CHECK (pair IN ('BTC-USD','ETH-USD','SOL-USD')),
 entry numeric(38,18) NOT NULL CHECK (entry>0),
 stop numeric(38,18) NOT NULL CHECK (stop>0),
 target numeric(38,18) NOT NULL CHECK (target>0),
 quantity numeric(38,18) NOT NULL CHECK (quantity>0),
 expires_at timestamptz NOT NULL,
 status text NOT NULL DEFAULT 'Pending' CHECK (status IN ('Pending','Approved','Rejected','Expired','Open','Closed')),
 created_at timestamptz NOT NULL DEFAULT now(),
 CHECK (entry>stop AND target>entry)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_paper_position ON paper_gate.proposals ((true)) WHERE status='Open';
CREATE TABLE IF NOT EXISTS paper_gate.paper_fills (
 proposal_id text PRIMARY KEY REFERENCES paper_gate.proposals(id),
 fill_price numeric(38,18) NOT NULL CHECK(fill_price>0),
 quantity numeric(38,18) NOT NULL CHECK(quantity>0),
 fee_usd numeric(38,18) NOT NULL CHECK(fee_usd>=0),
 filled_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS paper_gate.coinbase_fills (
 source_portfolio text NOT NULL,
 product_id text NOT NULL,
 trade_id text NOT NULL,
 order_id text,
 side text NOT NULL CHECK (side IN ('BUY','SELL')),
 trade_time timestamptz NOT NULL,
 raw_size numeric(38,18) NOT NULL CHECK(raw_size>0),
 size_in_quote boolean NOT NULL,
 base_quantity numeric(38,18) NOT NULL CHECK(base_quantity>0),
 price numeric(38,18) NOT NULL CHECK(price>0),
 commission numeric(38,18),
 commission_currency text,
 payload_hash text NOT NULL,
 imported_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(source_portfolio,product_id,trade_id)
);
CREATE TABLE IF NOT EXISTS paper_gate.events (
 event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 proposal_id text,
 event_type text NOT NULL,
 occurred_at timestamptz NOT NULL DEFAULT now(),
 details jsonb NOT NULL DEFAULT '{}'::jsonb
);
ALTER TABLE paper_gate.proposals ENABLE ROW LEVEL SECURITY;
ALTER TABLE paper_gate.paper_fills ENABLE ROW LEVEL SECURITY;
ALTER TABLE paper_gate.coinbase_fills ENABLE ROW LEVEL SECURITY;
ALTER TABLE paper_gate.events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON ALL TABLES IN SCHEMA paper_gate FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA paper_gate FROM PUBLIC, anon, authenticated;
COMMIT;
