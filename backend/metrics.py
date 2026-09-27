"""Explicit sample metrics, with missing/constant-series results left null."""
import math
from statistics import mean, pstdev


def corr(a, b):
    if len(a) < 3:
        return None
    ma, mb = mean(a), mean(b)
    denom = math.sqrt(sum((x-ma)**2 for x in a)*sum((y-mb)**2 for y in b))
    return sum((x-ma)*(y-mb) for x,y in zip(a,b))/denom if denom > 1e-12 else None


def ranks(a):
    return [1 + sum(y < x for y in a) + (sum(y == x for y in a)-1)/2 for x in a]


def sign(x):
    return 1 if x > 0 else -1 if x < 0 else 0


def metrics(points, benchmark, peers):
    n = len(points)
    if not n:
        return dict(n=0,direction_accuracy=None,mae=None,rmse=None,rank_ic=None,brier=None,
                    calibration_ece=None,calibration_bins=[],stability=None,incremental_contribution=None,
                    diversity=None,paired_n=0,adjusted_mae=None,human_mae_improvement=None)
    x = [p['original'] for p in points]
    y = [p['value'] for p in points]
    errors = [abs(a-b) for a,b in zip(x,y)]
    bins=[]
    for idx in range(5):
        lo=idx/5
        group = [p for p in points if min(4,int(p['probability_up']*5))==idx]
        if group:
            bins.append(dict(lower=lo,n=len(group),predicted=mean(p['probability_up'] for p in group),observed=mean(p['value']>0 for p in group)))
    paired = [(p, benchmark[p['issued_at']]) for p in points if p['issued_at'] in benchmark]
    paired_baseline = mean(abs(b['original']-b['value']) for _,b in paired) if paired else 0
    incremental = (1-mean(abs(p['original']-p['value']) for p,_ in paired)/paired_baseline) if paired_baseline > 1e-12 else None
    correlations=[]
    for peer in peers:
        common=[(p['original'],peer[p['issued_at']]['original']) for p in points if p['issued_at'] in peer]
        c=corr([a for a,b in common],[b for a,b in common])
        if c is not None:
            correlations.append(abs(c))
    half=n//2
    stability = 1-abs(mean(sign(p['original'])==sign(p['value']) for p in points[:half])-mean(sign(p['original'])==sign(p['value']) for p in points[half:])) if n>=8 else None
    mae=mean(errors)
    adjusted_mae=mean(abs(p['adjusted']-p['value']) for p in points)
    return dict(n=n,direction_accuracy=mean(sign(a)==sign(b) for a,b in zip(x,y)),mae=mae,
                rmse=math.sqrt(mean(e*e for e in errors)),rank_ic=corr(ranks(x),ranks(y)),
                brier=mean((p['probability_up']-int(p['value']>0))**2 for p in points),
                adjusted_brier=mean((p['adjusted_probability_up']-int(p['value']>0))**2 for p in points),
                calibration_ece=sum(b['n']/n*abs(b['predicted']-b['observed']) for b in bins),
                calibration_bins=bins,stability=stability,incremental_contribution=incremental,
                diversity=1-mean(correlations) if correlations else None,paired_n=len(paired),
                adjusted_mae=adjusted_mae,human_mae_improvement=mae-adjusted_mae)


def score(m):
    if m['n'] < 8:
        return None
    # Return scale cancels via paired benchmark improvement. No cross-asset ranking.
    ic = m['rank_ic'] if m['rank_ic'] is not None else 0
    inc = max(-1,min(1,m['incremental_contribution'] or 0))
    return round(.35*m['direction_accuracy']+.20*(ic+1)/2+.15*(1-m['brier'])+
                 .15*(inc+1)/2+.10*(m['stability'] or 0)+.05*(m['diversity'] or 0),6)
