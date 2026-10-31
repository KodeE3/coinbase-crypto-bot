// FX AutoTrader v2.2 — DEMO-ONLY autonomous scanner and EA
// No live-account override exists. Compile and test in MetaEditor before use.
#property strict
#property version "2.20"
#property description "Nine-pair hybrid scanner; DEMO-only auto execution; fail-closed risk gates"

input bool EnableDemoAutoTrading = false;  // explicit opt-in AFTER demo testing
input bool EmergencyKillSwitch = true;     // true = block all new orders
input bool CalendarCheckedAndClear = false;// false = fail closed; no automatic news feed
input datetime CalendarClearUntilUTC = 0;  // expires; maximum 24 hours from current UTC
input bool AllowFreshQuotes = true;
input double RiskPercent = 0.50;
input int MinimumExecutionScore = 80;
input double MaxSpreadPips = 2.50;
input double RewardRiskRatio = 2.0;
input int MaxOpenPositions = 2;
input double DailyEquityLossLimitPercent = 2.0;
input int MaxConsecutiveLosses = 3;
input int CooldownMinutes = 240;
input int MaxQuoteAgeSeconds = 180;
input int MagicNumber = 26102821;
input int SlippagePoints = 20;
input int ScanEverySeconds = 30;

string Pairs[9] = {"EURUSD","GBPUSD","USDJPY","AUDUSD","USDCAD","NZDUSD","EURJPY","GBPJPY","EURGBP"};
datetime LastSignalBar[9];
datetime LastScan=0;
double SessionEquity=0;
int SessionDay=-1;
bool Halted=false;
double OwnerToken=0;
string WorkerLock="";
bool OwnsLock=false;
datetime LastServerTime=0;
uint LastServerAdvance=0;
bool ServerAdvanced=false;

string Scope() {return (IsTesting()?"FXAT_TEST_":"FXAT_")+IntegerToString(AccountNumber());}
string SignalKey(string pair) {return Scope()+"_SIGNAL_"+pair;}
string PendingKey() {return Scope()+"_PENDING";}
bool CalendarClear() {
 datetime now=TimeGMT();
 return CalendarCheckedAndClear && CalendarClearUntilUTC>now && CalendarClearUntilUTC-now<=86400;
}
bool FeedAlive() {
 datetime server=TimeCurrent();
 if(server>LastServerTime) {LastServerTime=server;LastServerAdvance=GetTickCount();ServerAdvanced=true;}
 else if(server<LastServerTime) {SetKill();return false;}
 // TimeCurrent can freeze when quotes stop. Measure elapsed time on a separate clock.
 return IsConnected() && ServerAdvanced && (uint)(GetTickCount()-LastServerAdvance)<=(uint)MaxQuoteAgeSeconds*1000;
}
void Heartbeat(string state) {
 if(!OwnsLock) return;
 GlobalVariableSet(Scope()+"_HEARTBEAT_UTC",(double)TimeGMT());
 Comment("FXAT 2.2 DEMO ONLY | ",state," | UTC ",TimeToString(TimeGMT(),TIME_DATE|TIME_SECONDS));
}

bool IsDemo() { return AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO; }
string FlagName() { return (IsTesting()?"FXAT_TEST_KILL_":"FXAT_KILL_")+IntegerToString(AccountNumber()); }
bool Killed() { return EmergencyKillSwitch || Halted || (GlobalVariableCheck(FlagName()) && GlobalVariableGet(FlagName())>0); }
void SetKill() { GlobalVariableSet(FlagName(),1); GlobalVariablesFlush(); Halted=true; Print("FXAT emergency kill latched: no new orders"); }
int OnInit() {
  if(!IsDemo()) { Print("FXAT blocked: DEMO accounts only"); return INIT_FAILED; }
  if(AccountNumber()<=0) return INIT_FAILED;
  if(RiskPercent<=0 || RiskPercent>0.5 || MinimumExecutionScore<80 || MaxOpenPositions<1 || MaxOpenPositions>2 || RewardRiskRatio<2.0 || DailyEquityLossLimitPercent<=0 || DailyEquityLossLimitPercent>2.0) return INIT_PARAMETERS_INCORRECT;
  if(!MathIsValidNumber(RiskPercent) || !MathIsValidNumber(RewardRiskRatio) || !MathIsValidNumber(MaxSpreadPips) || !MathIsValidNumber(DailyEquityLossLimitPercent)) return INIT_PARAMETERS_INCORRECT;
  if(MinimumExecutionScore>100 || MaxSpreadPips<=0 || MaxSpreadPips>2.5 || MaxQuoteAgeSeconds<1 || MaxQuoteAgeSeconds>180 || MaxConsecutiveLosses<1 || MaxConsecutiveLosses>3 || CooldownMinutes<240 || ScanEverySeconds<10 || ScanEverySeconds>180 || SlippagePoints<0 || SlippagePoints>100 || MagicNumber<=0) return INIT_PARAMETERS_INCORRECT;
  WorkerLock=Scope()+"_LOCK22";OwnerToken=(double)ChartID();
  if(OwnerToken<=0 || OwnerToken>9007199254740991.0 || !GlobalVariableTemp(WorkerLock)) return INIT_FAILED;
  if(!GlobalVariableSetOnCondition(WorkerLock,OwnerToken,0)) {Print("FXAT blocked: another v2.2 instance owns this demo account");return INIT_FAILED;}
  OwnsLock=true;
  LastServerTime=TimeCurrent();LastServerAdvance=GetTickCount();ServerAdvanced=false;
  for(int i=0;i<9;i++) {
   string key=SignalKey(Pairs[i]);
   LastSignalBar[i]=GlobalVariableCheck(key)?(datetime)GlobalVariableGet(key):0;
  }
  if(GlobalVariableCheck(PendingKey()) && GlobalVariableGet(PendingKey())>0) {
   SetKill();Print("FXAT unresolved prior submission; reconcile broker history before manually clearing pending and kill flags");
  }
  if(!EventSetTimer(ScanEverySeconds)) {GlobalVariableSetOnCondition(WorkerLock,0,OwnerToken);OwnsLock=false;return INIT_FAILED;}
  Print("FXAT v2.2 loaded DEMO ONLY; orders default OFF; calendar requires expiring UTC clearance");
  return INIT_SUCCEEDED;
}
void OnDeinit(const int reason) {
 EventKillTimer();
 if(OwnsLock) {GlobalVariableSetOnCondition(WorkerLock,0,OwnerToken);OwnsLock=false;}
 Comment("");
}
void OnTick() {} // timer scans all nine pairs from a single chart
string Resolve(string base) {
  // exact symbol preferred; suffix/prefix accepted only when unique
  if(MarketInfo(base,MODE_POINT)>0) return base;
  string result=""; int count=0;
  for(int i=0;i<SymbolsTotal(false);i++) { string s=SymbolName(i,false); if(StringFind(s,base)>=0) {result=s;count++;} }
  if(count==1) return result;
  return "";
}
double Pip(string sym) { double pt=MarketInfo(sym,MODE_POINT); int digits=(int)MarketInfo(sym,MODE_DIGITS); return (digits==3||digits==5)?pt*10:pt; }
double Ema(string sym,int tf,int period,int shift) {return iMA(sym,tf,period,0,MODE_EMA,PRICE_CLOSE,shift);}
double Atr(string sym,int tf,int period) {return iATR(sym,tf,period,1);}
int CountPositions() {
 int n=0;
 for(int i=OrdersTotal()-1;i>=0;i--) if(OrderSelect(i,SELECT_BY_POS,MODE_TRADES) && OrderMagicNumber()==MagicNumber && (OrderType()==OP_BUY||OrderType()==OP_SELL)) n++;
 return n;
}
bool HasPairExposure(string sym) {
 for(int i=OrdersTotal()-1;i>=0;i--) if(OrderSelect(i,SELECT_BY_POS,MODE_TRADES) && OrderType()>=OP_BUY && OrderType()<=OP_SELLSTOP) {
  if(OrderSymbol()==sym) return true;
  // Conservative portfolio filter: avoid any shared base/quote currency, including manual trades
  string a="",b="";
  for(int k=0;k<9;k++) if(StringFind(sym,Pairs[k])>=0) {a=StringSubstr(Pairs[k],0,3);b=StringSubstr(Pairs[k],3,3);break;}
  if(a=="" || b=="") return true;
  string other=OrderSymbol();
  if(StringFind(other,a)>=0 || StringFind(other,b)>=0) return true;
 }
 return false;
}
int ConsecutiveLosses(datetime &latestLoss) {
 int n=0; latestLoss=0;
 // Gather most recent 3 closed EA orders by close timestamp, not history list position
 datetime cursor=TimeCurrent()+1;int cursorTicket=2147483647;
 for(int k=0;k<MaxConsecutiveLosses;k++) {
  int found=-1,bestTicket=-1; datetime best=0;
  for(int i=0;i<OrdersHistoryTotal();i++) if(OrderSelect(i,SELECT_BY_POS,MODE_HISTORY) && OrderMagicNumber()==MagicNumber && (OrderType()==OP_BUY||OrderType()==OP_SELL) && OrderCloseTime()>0) {
   datetime closed=OrderCloseTime();int ticket=OrderTicket();
   if((closed<cursor || (closed==cursor && ticket<cursorTicket)) && (closed>best || (closed==best && ticket>bestTicket))) {best=closed;bestTicket=ticket;found=i;}
  }
  if(found<0 || !OrderSelect(found,SELECT_BY_POS,MODE_HISTORY)) break;
  if(OrderProfit()+OrderSwap()+OrderCommission()>=0) break;
  if(n==0) latestLoss=best;
  n++;cursor=best;cursorTicket=bestTicket;
 }
 return n;
}
void ResetDailyAnchor() {
 int d=TimeYear(TimeCurrent())*1000+TimeDayOfYear(TimeCurrent());
 if(d!=SessionDay) {
  SessionDay=d;string key=(IsTesting()?"FXAT_TEST_DAY_":"FXAT_DAY_")+IntegerToString(AccountNumber())+"_"+IntegerToString(d);
  if(!GlobalVariableCheck(key)) {if(GlobalVariableSet(key,AccountEquity())==0) {SetKill();return;}GlobalVariablesFlush();}
  SessionEquity=GlobalVariableGet(key);
 }
}
bool Gates() {
 if(!OwnsLock || !GlobalVariableCheck(WorkerLock) || GlobalVariableGet(WorkerLock)!=OwnerToken) return false;
 if(!IsDemo() || !EnableDemoAutoTrading || Killed() || !CalendarClear() || !AllowFreshQuotes || !FeedAlive() || !IsTradeAllowed()) return false;
 if(GlobalVariableCheck(PendingKey()) && GlobalVariableGet(PendingKey())>0) {SetKill();return false;}
 ResetDailyAnchor();
 if(SessionEquity<=0 || AccountEquity() <= SessionEquity*(1.0-DailyEquityLossLimitPercent/100.0)) {SetKill();return false;}
 datetime lastLoss=0;int losses=ConsecutiveLosses(lastLoss);
 if(losses>=MaxConsecutiveLosses && TimeCurrent()-lastLoss<CooldownMinutes*60) return false;
 if(CountPositions()>=MaxOpenPositions) return false;
 return true;
}
int ScoreSignal(string sym,int &direction,string &strategy,datetime &barTime,double &atrValue) {
 direction=0;strategy="";
 if(iBars(sym,PERIOD_D1)<205 || iBars(sym,PERIOD_H4)<205 || iBars(sym,PERIOD_H1)<205 || iBars(sym,PERIOD_M15)<205 || iBars(sym,PERIOD_M5)<205) return 0;
 barTime=iTime(sym,PERIOD_M5,1); if(barTime<=0 || TimeCurrent()-iTime(sym,PERIOD_M5,0)>MaxQuoteAgeSeconds+300) return 0;
 double fast=Ema(sym,PERIOD_D1,50,1),slow=Ema(sym,PERIOD_D1,200,1),dc=iClose(sym,PERIOD_D1,1);
 if(dc>fast && fast>slow) direction=1;
 else if(dc<fast && fast<slow) direction=-1;
 else return 0;
 bool h4align=(iClose(sym,PERIOD_H4,1)-Ema(sym,PERIOD_H4,20,1))*direction>0;
 bool h1align=(iClose(sym,PERIOD_H1,1)-Ema(sym,PERIOD_H1,20,1))*direction>0;
 double prevHigh=-1e10,prevLow=1e10;
 for(int k=2;k<=21;k++) {prevHigh=MathMax(prevHigh,iHigh(sym,PERIOD_M15,k));prevLow=MathMin(prevLow,iLow(sym,PERIOD_M15,k));}
 bool breakout=(direction==1 && iClose(sym,PERIOD_M15,1)>prevHigh)||(direction==-1 && iClose(sym,PERIOD_M15,1)<prevLow);
 bool pullback=(iClose(sym,PERIOD_M15,2)-Ema(sym,PERIOD_M15,20,2))*direction<=0 && (iClose(sym,PERIOD_M15,1)-Ema(sym,PERIOD_M15,20,1))*direction>0;
 double sweepHigh=-1e10,sweepLow=1e10;
 for(int j=2;j<=11;j++) {sweepHigh=MathMax(sweepHigh,iHigh(sym,PERIOD_M15,j));sweepLow=MathMin(sweepLow,iLow(sym,PERIOD_M15,j));}
 bool sweep=(direction==1 && iLow(sym,PERIOD_M15,1)<sweepLow && iClose(sym,PERIOD_M15,1)>iClose(sym,PERIOD_M15,2)) || (direction==-1 && iHigh(sym,PERIOD_M15,1)>sweepHigh && iClose(sym,PERIOD_M15,1)<iClose(sym,PERIOD_M15,2));
 bool m5confirm=(iClose(sym,PERIOD_M5,1)-iOpen(sym,PERIOD_M5,1))*direction>0;
 if(!m5confirm || !(breakout||pullback||sweep)) return 0;
 strategy=breakout?"breakout":pullback?"pullback":"liquidity_sweep";
 atrValue=Atr(sym,PERIOD_H1,14);if(atrValue<=0) return 0;
 double point=MarketInfo(sym,MODE_POINT),pip=Pip(sym),spread=(MarketInfo(sym,MODE_ASK)-MarketInfo(sym,MODE_BID))/pip;
 if(point<=0 || pip<=0 || spread<0 || spread>MaxSpreadPips) return 0;
 return 25+(h4align?15:0)+(h1align?15:0)+20+10+(spread<=1.5?10:0)+(atrValue/pip>=5?5:0);
}
double LotsForRisk(string sym,double entry,double stop) {
 double tickValue=SymbolInfoDouble(sym,SYMBOL_TRADE_TICK_VALUE),tickSize=SymbolInfoDouble(sym,SYMBOL_TRADE_TICK_SIZE),step=MarketInfo(sym,MODE_LOTSTEP),minLot=MarketInfo(sym,MODE_MINLOT),maxLot=MarketInfo(sym,MODE_MAXLOT);
 if(tickValue<=0||tickSize<=0||step<=0||minLot<=0||maxLot<=0||MathAbs(entry-stop)<=0) return 0;
 double perLot=(MathAbs(entry-stop)+SlippagePoints*MarketInfo(sym,MODE_POINT))/tickSize*tickValue;
 if(perLot<=0) return 0;
 double raw=AccountEquity()*RiskPercent/100.0/perLot;
 double lots=NormalizeDouble(MathFloor(MathMin(raw,maxLot)/step)*step,8);
 if(lots<minLot || lots*perLot>AccountEquity()*RiskPercent/100.0+0.00001) return 0;
 return lots;
}
void OnTimer() {
 FeedAlive();
 if(!Gates()) {Heartbeat("BLOCKED: inspect demo, kill, calendar, feed and risk gates");return;}
 Heartbeat("SCANNING");
 for(int i=0;i<9;i++) {
  if(!Gates()) return;
  string sym=Resolve(Pairs[i]); if(sym=="") continue;
  if(!SymbolSelect(sym,true)) continue;
  datetime tickTime=(datetime)MarketInfo(sym,MODE_TIME);
  if(tickTime<=0 || TimeCurrent()-tickTime>MaxQuoteAgeSeconds || tickTime>TimeCurrent()+5) continue;
  if(HasPairExposure(sym)) continue;
  int dir=0;string strategy="";datetime bar=0;double a=0;
  int score=ScoreSignal(sym,dir,strategy,bar,a);
  if(score<MinimumExecutionScore || dir==0 || bar<=0 || LastSignalBar[i]==bar) continue;
  double pip=Pip(sym),point=MarketInfo(sym,MODE_POINT),bid=MarketInfo(sym,MODE_BID),ask=MarketInfo(sym,MODE_ASK);
  if(pip<=0 || point<=0 || ask<=bid || bid<=0) continue;
  double spread=(ask-bid)/pip;
  if(spread>MaxSpreadPips) continue;
  double entry=dir==1?ask:bid;
  double distance=MathMax(a*1.5,2*spread*pip);
  double minStop=(MarketInfo(sym,MODE_STOPLEVEL)+2)*point;
  distance=MathMax(distance,minStop+spread*pip);
  int digits=(int)MarketInfo(sym,MODE_DIGITS);
  double sl=NormalizeDouble(entry-dir*distance,digits),tp=NormalizeDouble(entry+dir*distance*RewardRiskRatio,digits);
  double lots=LotsForRisk(sym,entry,sl);
  if(lots<=0) {Print("FXAT skip: min lot exceeds risk budget for ",sym);continue;}
  int cmd=dir==1?OP_BUY:OP_SELL;
  if(AccountFreeMarginCheck(sym,cmd,lots)<=0) continue;
  if(!Gates() || Killed() || HasPairExposure(sym)) return;
  // Persist intent BEFORE submission. Never automatically retry an uncertain result.
  if(GlobalVariableSet(SignalKey(Pairs[i]),(double)bar)==0 || GlobalVariableSet(PendingKey(),(double)bar)==0) {SetKill();return;}
  LastSignalBar[i]=bar;GlobalVariablesFlush();
  ResetLastError();
  int ticket=OrderSend(sym,cmd,lots,entry,SlippagePoints,sl,tp,"FXAT22 "+strategy,MagicNumber,0,clrNONE);
  if(ticket>0 && OrderSelect(ticket,SELECT_BY_TICKET) && OrderStopLoss()>0 && OrderTakeProfit()>0) {
   double ts=SymbolInfoDouble(sym,SYMBOL_TRADE_TICK_SIZE),tv=SymbolInfoDouble(sym,SYMBOL_TRADE_TICK_VALUE);
   if(ts<=0 || tv<=0 || MathAbs(OrderOpenPrice()-OrderStopLoss())/ts*tv*OrderLots()>AccountEquity()*RiskPercent/100.0+0.00001) {
    SetKill();Print("FXAT post-fill risk mismatch; inspect existing demo position. No automatic close.");return;
   }
   if(GlobalVariableSet(PendingKey(),0)==0) {SetKill();return;}
   GlobalVariablesFlush();Print("FXAT DEMO order ",ticket," ",sym," score=",score," lots=",lots);
  } else {int error=GetLastError();SetKill();Print("FXAT submission unresolved; no retry. Ticket=",ticket," error=",error);return;}
 }
}
