# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd

def bollinger_bands(close, n=60, k=2.0):
    mid = close.rolling(n).mean()
    std = close.rolling(n).std(ddof=0)
    return mid, mid + k * std, mid - k * std

def bandwidth(mid, upper, lower):
    return (upper - lower) / mid.replace(0, np.nan)

def adx(high, low, close, n=14):
    up = high.diff(); down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(n).mean()
    plus_di = 100 * pd.Series(plus_dm, index=high.index).rolling(n).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=high.index).rolling(n).mean() / atr
    denom = (plus_di + minus_di).replace(0, np.nan)
    return (100 * (plus_di - minus_di).abs() / denom).rolling(n).mean()

def calculate_signals(df, cfg):
    """기존 지표 계산 로직 유지"""
    close = df["Close"]; high = df["High"]; low = df["Low"]; vol = df["Volume"]
    mid, upper, lower = bollinger_bands(close, cfg["bollinger"]["length"], cfg["bollinger"]["stdev"])
    bbw = bandwidth(mid, upper, lower)
    bbw_rank = bbw.rolling(120).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1])
    adx_val = adx(high, low, close, cfg["trend"]["adx_len"])
    
    return {
        "upper": upper, "lower": lower, "mid": mid, "bbw_rank": bbw_rank, "adx": adx_val
    }

def score_stock(df, sig, cfg, investor_data=None):
    """[최종 합의 버전] 통계적 표준 100점 체계"""
    if sig is None: return None
    last = df.index[-1]
    close = float(df.loc[last, "Close"])
    vol = df["Volume"]
    
    # 1. 추세 점수 (25점)
    trend_score = 0
    ma20 = float(df["Close"].rolling(20).mean().loc[last])
    ma50 = float(df["Close"].rolling(50).mean().loc[last])
    ma200 = float(df["Close"].rolling(200).mean().loc[last])
    if close > ma20: trend_score += 5
    if close > ma50: trend_score += 5
    if close > ma200: trend_score += 5
    if ma20 > ma50 > ma200: trend_score += 5 # 정배열
    if float(sig["adx"].loc[last]) >= 20: trend_score += 5
    
    # 2. 위치 점수 (Location - 30점)
    location_score = 0
    upper = float(sig["upper"].loc[last])
    # A. Door Knock (10점)
    if upper * 0.95 <= close <= upper * 1.05: location_score += 10
    # B. Squeeze (10점)
    if float(sig["bbw_rank"].loc[last]) <= 0.20: location_score += 10
    # C. Memory (10점)
    vol_lookback = df.iloc[-60:]
    memory_price = vol_lookback.loc[vol_lookback["Volume"].idxmax(), "Close"]
    if abs(close / memory_price - 1) <= 0.05: location_score += 10
    
    # 3. 거래량 점수 (Volume - 20점)
    volume_score = 0
    vol_ma20 = vol.rolling(20).mean()
    # 1단계: 과거 폭발 (5점)
    if (vol.iloc[-60:-1] >= vol_ma20.iloc[-60:-1] * 3.0).any(): volume_score += 5
    # 2단계: 수축 (7점)
    dry_days = (vol.iloc[-15:-1] < vol_ma20.iloc[-15:-1] * 0.7).sum()
    if dry_days >= 3: volume_score += 7
    # 3단계: 오늘 활성화 (8점)
    vol_ratio = vol.loc[last] / vol_ma20.loc[last]
    if 1.2 <= vol_ratio <= 2.0: volume_score += 5
    elif 2.0 < vol_ratio <= 3.0: volume_score += 8
    elif vol_ratio > 3.0: volume_score += 3 # 과열
    
    # 4. 수급 점수 (15점)
    supply_score = 0
    if investor_data:
        fc = investor_data.get("foreign_consecutive_buy", 0)
        if fc >= 5: supply_score += 8
        elif fc >= 3: supply_score += 5
        elif fc >= 1: supply_score += 2
        if investor_data.get("inst_net_buy_5d", 0) > 0: supply_score += 4
        if investor_data.get("foreign_net_buy_5d", 0) > 0: supply_score += 3
    
    # 5. 리스크 점수 (10점)
    risk_score = 10
    stop = float(df["Low"].tail(10).min())
    risk_pct = (close - stop) / close
    if risk_pct > 0.10: risk_score -= 5
    elif risk_pct > 0.05: risk_score -= 2
    
    total = trend_score + location_score + volume_score + supply_score + risk_score
    return {
        "total_score": float(total), "close": close, "vol_ratio": vol_ratio,
        "trend_score": trend_score, "pattern_score": location_score, "volume_score": volume_score,
        "supply_score": supply_score, "risk_score": risk_score, "stop": stop, "risk_pct": risk_pct * 100,
        "ma20": ma20, "bb_upper": upper, "memory_price": memory_price, "tags": ""
    }
