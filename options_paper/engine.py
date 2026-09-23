"""Educational long-option proposal engine. No network or broker access."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json


def money(value):
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("Invalid numeric value") from exc
    if not number.is_finite():
        raise ValueError("Values must be finite")
    return number


def propose(snapshot, now=None, demo=False):
    """Return a proposal or a rejection reason for a single snapshot."""
    now = now or datetime.now(timezone.utc)
    observed = datetime.fromisoformat(snapshot["as_of"].replace("Z", "+00:00"))
    if observed.tzinfo is None:
        raise ValueError("as_of must include a timezone")
    age = now - observed
    if not demo and (age < timedelta(0) or age > timedelta(minutes=15)):
        return {"rejected": "Snapshot is future-dated or more than 15 minutes old"}
    closes = [money(x) for x in snapshot["closes"]]
    if len(closes) < 11 or any(x <= 0 for x in closes):
        return {"rejected": "Need at least 11 positive daily closes"}
    short = sum(closes[-5:]) / 5
    long = sum(closes[-10:]) / 10
    if short <= long or closes[-1] <= closes[-2]:
        return {"rejected": "No bullish trend and momentum signal"}
    equity = money(snapshot["paper_equity"])
    if equity <= 0:
        return {"rejected": "Paper equity must be positive"}
    candidates = []
    for item in snapshot["options"]:
        if item.get("right") != "call" or item.get("underlying") != snapshot["symbol"]:
            continue
        try:
            expiry = date.fromisoformat(item["expiry"])
            days = (expiry - observed.date()).days
            bid, ask = money(item["bid"]), money(item["ask"])
            delta = money(item["delta"])
            multiplier = int(item.get("multiplier", 100))
            volume, open_interest = int(item["volume"]), int(item["open_interest"])
            strike = money(item["strike"])
        except (KeyError, ValueError, TypeError):
            continue
        if not (21 <= days <= 45 and bid > 0 and ask >= bid and ask > 0
                and Decimal("0.35") <= delta <= Decimal("0.65")
                and (ask - bid) / ask <= Decimal("0.10")
                and volume >= 100 and open_interest >= 500
                and multiplier == 100 and strike > 0):
            continue
        if ask * multiplier > min(equity * Decimal("0.02"), Decimal("200")):
            continue
        candidates.append((abs(delta - Decimal("0.50")), (ask - bid) / ask, item["symbol"], item, ask, bid))
    if not candidates:
        return {"rejected": "No liquid, affordable long call matches the sample rules"}
    _, _, _, contract, ask, bid = min(candidates, key=lambda x: x[:3])
    proposal_id = hashlib.sha256((snapshot["as_of"] + "|" + contract["symbol"]).encode()).hexdigest()[:12]
    return {
        "id": proposal_id, "snapshot_as_of": snapshot["as_of"],
        "underlying": snapshot["symbol"], "contract": contract["symbol"],
        "action": "buy_to_open", "quantity": 1, "limit_price": str(ask),
        "illustrative_fill": str(ask), "estimated_entry_cost": str(ask * 100),
        "max_premium_loss": str(ask * 100), "bid_at_snapshot": str(bid),
        "estimated_immediate_liquidation_value": str(bid * 100),
        "reason": "5-day average above 10-day average and latest close rising; sample filters passed",
        "demo": demo,
    }


def record_approval(proposal, journal_path, typed_contract):
    """Append one simulated buy; explicit contract confirmation and duplicate guard."""
    if typed_contract != proposal["contract"]:
        raise ValueError("Contract confirmation did not match; nothing recorded")
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    # An exclusive lock prevents two local processes from recording the same idea.
    import fcntl
    with journal_path.open("a+", encoding="utf-8") as journal:
        fcntl.flock(journal, fcntl.LOCK_EX)
        journal.seek(0)
        if any(json.loads(line)["proposal_id"] == proposal["id"] for line in journal if line.strip()):
            raise ValueError("This proposal has already been recorded")
        event = {
            "event": "simulated_buy", "proposal_id": proposal["id"],
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "contract": proposal["contract"], "quantity": 1,
            "fill_price": proposal["illustrative_fill"],
            "premium_paid": proposal["estimated_entry_cost"],
            "snapshot_as_of": proposal["snapshot_as_of"],
            "demo": proposal["demo"],
        }
        journal.write(json.dumps(event) + "\n")
        journal.flush()
        return event
