"""Credential-free Coinbase Exchange data; fixed GET endpoint allowlist."""
import json
import time
from datetime import datetime,timezone,timedelta
from urllib.parse import urlencode
from urllib.request import Request,build_opener
from prediction_paper.providers import NoRedirect,DataError
from coinbase_paper.gate import money,parse_time,fresh_quote


class SpotData:
    PAIRS=('BTC-USD','ETH-USD','SOL-USD')
    def __init__(self,opener=None): self.opener=opener or build_opener(NoRedirect())

    def _get(self,pair,resource,params=None):
        if pair not in self.PAIRS or resource not in ('ticker','candles'):
            raise DataError('unapproved market-data endpoint')
        url='https://api.exchange.coinbase.com/products/'+pair+'/'+resource
        if params: url+='?'+urlencode(params)
        try:
            started=time.monotonic()
            with self.opener.open(Request(url,method='GET',headers={'Accept':'application/json','Cache-Control':'no-cache','User-Agent':'paper-operations/0.1'}),timeout=10) as r:
                if r.status!=200 or not 0<=int(r.headers.get('Age','0'))<=15:
                    raise DataError('non-200 or stale market response')
                raw=r.read(2000001)
            if len(raw)>2000000 or time.monotonic()-started>10: raise DataError('market response limit exceeded')
            def unique(pairs):
                out={}
                for key,value in pairs:
                    if key in out: raise ValueError('duplicate JSON field')
                    out[key]=value
                return out
            def invalid(value): raise ValueError('nonfinite JSON value')
            return json.loads(raw,object_pairs_hook=unique,parse_constant=invalid)
        except (OSError,ValueError) as exc:
            raise DataError('market data unavailable or malformed') from None

    def quote(self,pair):
        data=self._get(pair,'ticker')
        bid,ask=money(data['bid']),money(data['ask'])
        if not 0<bid<=ask or (ask-bid)/ask>money('0.005'):
            raise DataError('invalid or wide spot quote')
        fresh_quote(data['time'],datetime.now(timezone.utc))
        return {'bid':str(bid),'ask':str(ask),'at':data['time'],
                'time_basis':'ticker_last_trade_time; not an independent quote timestamp'}

    def completed_candle(self,pair):
        now=datetime.now(timezone.utc)
        end=now.replace(hour=0,minute=0,second=0,microsecond=0)
        rows=self._get(pair,'candles',{'granularity':86400,'start':(end-timedelta(days=3)).isoformat(),'end':end.isoformat()})
        if not isinstance(rows,list) or not rows or len(rows)>300: raise DataError('invalid candles')
        times=set()
        for row in rows:
            if not isinstance(row,list) or len(row)!=6: raise DataError('malformed daily candle')
            start=money(row[0]); low,high,open_,close,volume=map(money,row[1:])
            if start!=start.to_integral_value() or int(start)%86400 or start in times:
                raise DataError('duplicate or unaligned daily candle')
            if not 0<low<=min(open_,close)<=max(open_,close)<=high or volume<0:
                raise DataError('invalid daily OHLCV')
            times.add(start)
        expected=int(end.timestamp())-86400
        if expected not in times: raise DataError('latest completed daily candle missing')
        return end.isoformat()
