import numpy as np
import pandas as pd

def bollinger_bands(close, n=20, k=2.0):
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std(ddof=0)
    upper = mid + k * sd
    lower = mid - k * sd
    return mid, upper, lower

def bandwidth(mid, upper, lower):
    return (upper - lower) / mid.replace(0, np.nan)

def percentile_rank(s, lookback):
    def pct(x):
        if len(x) < 2:
            return np.nan
        last = x[-1]
        return 100.0 * (np.sum(x <= last) - 1) / (len(x) - 1)
    return s.rolling(lookback).apply(pct, raw=True)

def adx(high, low, close, n=14):
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)

    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.rolling(n).mean()
    plus_di = 100 * pd.Series(plus_dm, index=high.index).rolling(n).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=high.index).rolling(n).mean() / atr
    denom = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / denom
    return dx.rolling(n).mean()

def find_climax_bar(df, vol_col="Volume", mult=5.0):
    vol = df[vol_col]
    vol_avg20 = vol.rolling(20).mean()
    is_climax = vol >= (mult * vol_avg20)

    climax_high = df["High"].where(is_climax)
    climax_low = df["Low"].where(is_climax)

    climax_high_ffill = climax_high.ffill()
    climax_low_ffill = climax_low.ffill()

    return climax_high_ffill, climax_low_ffill, is_climax

def calculate_signals(df, cfg):
    if df is None or len(df) < 200:
        return None

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    vol = df["Volume"]

    n = cfg["bollinger"]["length"]
    k = cfg["bollinger"]["stdev"]
    mid, upper, lower = bollinger_bands(close, n=n, k=k)
    bbw = bandwidth(mid, upper, lower)
    bbw_pct = percentile_rank(bbw, cfg["bollinger"]["bandwidth_lookback"])

    adx_val = adx(high, low, close, n=cfg["trend"]["adx_len"])
    climax_high, climax_low, is_climax = find_climax_bar(df, mult=cfg["volume"]["climax_mult"])

    squeeze = bbw_pct <= cfg["bollinger"]["squeeze_percentile_max"]
    expansion = bbw_pct >= cfg["bollinger"]["expansion_percentile_min"]

    breakout_60 = close > upper
    vol_confirm = vol >= cfg["volume"]["vol_confirm_mult"] * vol.rolling(20).mean()
    adx_ok = adx_val >= cfg["trend"]["adx_min"]

    setup_a = squeeze & breakout_60 & vol_confirm & adx_ok
    setup_b = (climax_high.notna()) & (close > climax_high) & vol_confirm

    return {
        "upper": upper,
        "bbw_pct": bbw_pct,
        "adx": adx_val,
        "climax_high": climax_high,
        "climax_low": climax_low,
        "is_climax": is_climax,
        "setup_a": setup_a,
        "setup_b": setup_b,
        "squeeze": squeeze,
        "expansion": expansion,
        "vol_confirm": vol_confirm,
    }

def score_stock(df, sig, cfg, mktcap=None):
    if sig is None:
        return None

    last = df.index[-1]
    close = float(df.loc[last, "Close"])
    mas = {p: float(df["Close"].rolling(p).mean().loc[last]) for p in cfg["trend"]["ma_periods"]}

    trend_score = 0
    if close > mas[20]:  trend_score += 10
    if close > mas[50]:  trend_score += 10
    if close > mas[200]: trend_score += 10
    if mas[20] > mas[50]:  trend_score += 3
    if mas[50] > mas[200]: trend_score += 2
    
    adx_val = float(sig["adx"].loc[last])
    if adx_val >= 40:     adx_score = 15
    elif adx_val >= 30:   adx_score = 12
    elif adx_val >= 25:   adx_score = 8
    elif adx_val >= 20:   adx_score = 5
    else:                 adx_score = 0
    
    trend_score += adx_score
    trend_score = min(trend_score, 50)

    trigger_score = 0
    if bool(sig["setup_a"].loc[last]): 
        trigger_score = max(trigger_score, 20)
    if bool(sig["setup_b"].loc[last]): 
        trigger_score = max(trigger_score, 25)
    if bool(sig["squeeze"].loc[last]): 
        trigger_score += 5
    if bool(sig["expansion"].loc[last]): 
        trigger_score -= 10
    trigger_score = float(np.clip(trigger_score, 0, 30))

    adv20 = float((df["Close"] * df["Volume"]).rolling(20).mean().loc[last])
    
    if adv20 < 5_000_000_000:
        return None
    
    if mktcap and mktcap > 0:
        turnover = adv20 / mktcap
        if turnover >= 0.03:      liq_score = 20
        elif turnover >= 0.02:    liq_score = 18
        elif turnover >= 0.015:   liq_score = 16
        elif turnover >= 0.01:    liq_score = 14
        elif turnover >= 0.005:   liq_score = 12
        else:                     liq_score = 10
    else:
        if adv20 >= 300_000_000_000:    liq_score = 20
        elif adv20 >= 150_000_000_000:  liq_score = 18
        elif adv20 >= 100_000_000_000:  liq_score = 16
        elif adv20 >= 50_000_000_000:   liq_score = 14
        else:                           liq_score = 10

    if bool(sig["setup_b"].loc[last]) and pd.notna(sig["climax_low"].loc[last]):
        stop = float(sig["climax_low"].loc[last])
    else:
        stop = float(df["Low"].tail(10).min())

    if stop <= 0:
        return None
    risk = (close - stop) / close
    if risk <= 0 or risk > cfg["risk"]["hard_stop_pct"]:
        return None

    total = float(trend_score + trigger_score + liq_score)
    setup = "B" if bool(sig["setup_b"].loc[last]) else ("A" if bool(sig["setup_a"].loc[last]) else "-")

    return {
        "close": close,
        "trend_score": float(trend_score),
        "trigger_score": float(trigger_score),
        "liq_score": float(liq_score),
        "total_score": total,
        "stop": stop,
        "risk_pct": float(risk * 100),
        "bbw_pct": float(sig["bbw_pct"].loc[last]),
        "adx": adx_val,
        "setup": setup,
    }
