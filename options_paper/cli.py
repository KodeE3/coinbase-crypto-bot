"""Paper-only commands; python -m options_paper.cli --demo starts the sample."""
import argparse
import json
import sqlite3
from datetime import timedelta
from pathlib import Path
from .account import Account, FEE
from .engine import propose, timestamp


def display(state):
    print(f"Mode: {state['mode']}")
    print(f"Cash: ${state['cash_cents']/100:,.2f} | Realized P/L: ${state['realized_pnl_cents']/100:,.2f}")
    print(f"Open position cost (not current market value): ${state['open_cost_cents']/100:,.2f}")
    for position in state['positions']:
        print(f"  1 x {position['contract']} | entry cost including fee: ${position['cost']/100:.2f}")
    if not state['positions']:
        print('No open positions.')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Paper-only options account; no real orders')
    parser.add_argument('--demo', action='store_true', help='use fictional data and a separate demo account')
    parser.add_argument('--account', type=Path, help='persistent SQLite account file')
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--snapshot', type=Path)
    actions.add_argument('--status', action='store_true')
    actions.add_argument('--history', action='store_true')
    actions.add_argument('--close', metavar='CONTRACT')
    parser.add_argument('--bid', help='illustrative exit bid, dollars per option share')
    parser.add_argument('--as-of', help='exit quote timestamp including timezone')
    args = parser.parse_args(argv)
    if args.demo and args.snapshot:
        parser.error('--demo cannot be combined with --snapshot')
    if (args.bid is not None or args.as_of) and not args.close:
        parser.error('--bid and --as-of require --close')
    if args.close and (args.bid is None or (not args.demo and not args.as_of)):
        parser.error('--close requires --bid and, outside demo mode, --as-of')
    if not any([args.demo, args.snapshot, args.status, args.history, args.close]):
        parser.error('Choose --demo, --snapshot, --status, --history, or --close')
    account = None
    try:
        source = Path(__file__).with_name('sample_snapshot.json')
        sample = json.loads(source.read_text(encoding='utf-8'))
        path = args.account or Path('paper_data/demo.sqlite3' if args.demo else 'paper_data/snapshots.sqlite3')
        account = Account(path, demo=args.demo)
        if args.status:
            display(account.status())
        elif args.history:
            print(json.dumps(account.history(), indent=2))
        elif args.close:
            as_of = args.as_of or (timestamp(sample['as_of']) + timedelta(days=1)).isoformat()
            print(f'SIMULATED SELL: 1 x {args.close} at bid ${args.bid}; fee ${FEE/100:.2f}; quote {as_of}')
            confirmation = input('Type the full contract symbol to confirm, or Enter to skip: ').strip()
            if not confirmation:
                print('Skipped.')
                return 0
            display(account.sell(args.close, args.bid, as_of, confirmation))
        else:
            snapshot = sample if args.demo else json.loads(args.snapshot.read_text(encoding='utf-8'))
            proposal = propose(snapshot, demo=args.demo)
            if 'rejected' in proposal:
                print('Rejected:', proposal['rejected'])
                return 1
            print(f"SIMULATED BUY: 1 x {proposal['contract']} at ask ${proposal['ask_cents']/100:.2f}")
            print(f"Entry cost including ${FEE/100:.2f} fee: ${(proposal['premium_cents']+FEE)/100:.2f}")
            print('Sample rule:', proposal['reason'])
            print('Quotes are supplied snapshots; no live quote refresh or real orders.')
            confirmation = input('Type the full contract symbol to confirm, or Enter to skip: ').strip()
            if not confirmation:
                print('Skipped.')
                return 0
            display(account.buy(proposal, confirmation))
        return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f'Unable to complete: {exc}')
        return 1
    except (EOFError, KeyboardInterrupt):
        print('\nCancelled; no pending trade recorded.')
        return 1
    finally:
        if account:
            account.close()


if __name__ == '__main__':
    raise SystemExit(main())
