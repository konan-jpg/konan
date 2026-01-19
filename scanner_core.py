# -*- coding: utf-8 -*-
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
        if len(x) < 2: return np.nan
        return 100.0 * (np.sum(x <= x[-1]) - 1) / (len(x) - 1)
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
    climax_high = df["High"].where(is_climax).ffill()
    climax_low = df["Low"].where(is_climax).ffill()
    return climax_high, climax_low, is_climax

def calculate_signals(df, cfg):
    if df is None or len(df) < 60:
        return None
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    vol = df["Volume"]
    
    n = cfg.get("bollinger", {}).get("length", 60)
    k = cfg.get("bollinger", {}).get("stdev", 2)
    mid, upper, lower = bollinger_bands(close, n=n, k=k)
    bbw = bandwidth(mid, upper, lower)
    lookback = cfg.get("bollinger", {}).get("bandwidth_lookback", 60)
    bbw_pct = percentile_rank(bbw, lookback)
    adx_len = cfg.get("trend", {}).get("adx_len", 14)
    adx_val = adx(high, low, close, n=adx_len)
    
    ma20 = close.rolling(20).mean()
    ma50 = close.rolling(50).mean()
    ma200 = close.rolling(200).mean()
    vol_ma20 = vol.rolling(20).mean()
    
    climax_mult = cfg.get("volume", {}).get("climax_mult", 5.0)
    climax_high, climax_low, is_climax = find_climax_bar(df, mult=climax_mult)
    
    # Door Knock: BB상단의 95%~102%
    door_knock = (close >= upper * 0.95) & (close <= upper * 1.02)
    
    # Squeeze: 밴드폭 하위 20%
    squeeze = bbw_pct <= 20
    
    # 거래량 관련
    vol_confirm_mult = cfg.get("volume", {}).get("vol_confirm_mult", 1.5)
    vol_confirm = vol >= vol_confirm_mult * vol_ma20
    vol_explosion = vol >= vol_ma20 * 3
    vol_dryup = vol < vol_ma20 * 0.7
    vol_dryup_count = vol_dryup.rolling(15).sum()
    
    # Setup 정의
    adx_min = cfg.get("trend", {}).get("adx_min", 20)
    adx_ok = adx_val >= adx_min
    breakout_60 = close > upper
    setup_a = squeeze & breakout_60 & vol_confirm & adx_ok
    setup_b = (climax_high.notna()) & (close > climax_high) & vol_confirm
    ma20_crossover = (close > ma20) & (close.shift(1) <= ma20.shift(1))
    setup_c = ma20_crossover & vol_confirm & adx_ok
    
    return {
        "upper": upper, "lower": lower, "mid": mid,
        "bbw_pct": bbw_pct, "adx": adx_val,
        "ma20": ma20, "ma50": ma50, "ma200": ma200,
        "vol_ma20": vol_ma20, "vol_confirm": vol_confirm,
        "climax_high": climax_high, "climax_low": climax_low, "is_climax": is_climax,
        "door_knock": door_knock, "squeeze": squeeze,
        "vol_explosion": vol_explosion, "vol_dryup_count": vol_dryup_count,
        "setup_a": setup_a, "setup_b": setup_b, "setup_c": setup_c,
    }

def score_stock(df, sig, cfg, mktcap=None, investor_data=None, rs_3m=0, rs_6m=0):
    """
    종합 점수 계산 (100점 만점)
    - 추세: 25점, 위치: 30점, 거래량: 20점, 수급: 15점, 리스크: 10점
    """
    if sig is None:
        return None
    
    last = df.index[-1]
    close = float(df.loc[last, "Close"])
    vol = float(df.loc[last, "Volume"])
    
    def safe_get(series, idx, default=0):
        try:
            val = series.loc[idx]
            return float(val) if pd.notna(val) else default
        except: return default
    
    def safe_bool(series, idx):
        try:
            val = series.loc[idx]
            return bool(val) if pd.notna(val) else False
        except: return False
    
    ma20 = safe_get(sig["ma20"], last, close)
    ma50 = safe_get(sig["ma50"], last, close)
    ma200 = safe_get(sig["ma200"], last, close)
    adx_val = safe_get(sig["adx"], last, 0)
    vol_ma20 = safe_get(sig["vol_ma20"], last, 1)
    
    # 상세 점수 기록용
    details = {}

    # 1. 추세 점수 (25점)
    trend_score = 0
    if close > ma20: trend_score += 5; details['trend_ma20'] = 5
    if close > ma50: trend_score += 5; details['trend_ma50'] = 5
    if close > ma200: trend_score += 5; details['trend_ma200'] = 5
    if ma20 > ma50: trend_score += 3; details['trend_align_20_50'] = 3
    if ma50 > ma200: trend_score += 2; details['trend_align_50_200'] = 2
    
    adx_score = 0
    if adx_val >= 40: adx_score = 5
    elif adx_val >= 30: adx_score = 4
    elif adx_val >= 25: adx_score = 3
    elif adx_val >= 20: adx_score = 2
    if adx_score > 0:
        trend_score += adx_score
        details['trend_adx'] = adx_score
        
    trend_score = min(trend_score, 25)
    
    # 2. 위치/패턴 점수 (30점)
    pattern_score = 0
    door_knock = safe_bool(sig["door_knock"], last)
    squeeze = safe_bool(sig["squeeze"], last)
    setup_a = safe_bool(sig["setup_a"], last)
    setup_b = safe_bool(sig["setup_b"], last)
    setup_c = safe_bool(sig.get("setup_c", pd.Series([False])), last)
    
    if door_knock: pattern_score += 10; details['pat_door_knock'] = 10
    if squeeze: pattern_score += 10; details['pat_squeeze'] = 10
    
    setup_pts = 0
    if setup_b: setup_pts = 5; details['pat_setup_b'] = 5
    elif setup_a: setup_pts = 4; details['pat_setup_a'] = 4
    elif setup_c: setup_pts = 3; details['pat_setup_c'] = 3
    pattern_score += setup_pts
    
    # RS 가산점
    rs_pts = 0
    if rs_3m >= 80: rs_pts += 5; details['pat_rs_3m'] = 5
    if rs_6m >= 80: rs_pts += 5; details['pat_rs_6m'] = 5
    pattern_score += rs_pts
    
    pattern_score = min(pattern_score, 30)
    
    # 3. 거래량 점수 (20점)
    volume_score = 0
    vol_ratio = vol / vol_ma20 if vol_ma20 > 0 else 0
    vol_confirm = safe_bool(sig["vol_confirm"], last)
    
    # 과거 대량거래 (5점)
    if sig["vol_explosion"].tail(60).any(): 
        volume_score += 5
        details['vol_explosion'] = 5
    
    # 거래량 수축 (7점)
    dryup_count = safe_get(sig["vol_dryup_count"], last, 0)
    dryup_pts = 0
    if dryup_count >= 5: dryup_pts = 7
    elif dryup_count >= 3: dryup_pts = 5
    elif dryup_count >= 1: dryup_pts = 3
    if dryup_pts > 0:
        volume_score += dryup_pts
        details['vol_dryup'] = dryup_pts
    
    # 당일 거래량 (8점)
    vol_today_pts = 0
    if vol_confirm: vol_today_pts = 8
    elif 1.2 <= vol_ratio < 2.0: vol_today_pts = 5
    elif vol_ratio >= 1.0: vol_today_pts = 3
    if vol_today_pts > 0:
        volume_score += vol_today_pts
        details['vol_today'] = vol_today_pts
    
    volume_score = min(volume_score, 20)
    
    # 4. 수급 점수 (15점)
    supply_score = 0
    if investor_data:
        fc = investor_data.get("foreign_consecutive_buy", 0)
        f_pts = 0
        if fc >= 5: f_pts = 8
        elif fc >= 3: f_pts = 5
        elif fc >= 1: f_pts = 2
        if f_pts > 0:
            supply_score += f_pts
            details['sup_foreign_consec'] = f_pts
            
        if investor_data.get("inst_net_buy_5d", 0) > 0: 
            supply_score += 4
            details['sup_inst_net'] = 4
        if investor_data.get("foreign_net_buy_5d", 0) > 0: 
            supply_score += 3
            details['sup_foreign_net'] = 3
            
    supply_score = min(supply_score, 15)
    
    # 5. 리스크 점수 (10점)
    risk_score = 10
    if setup_b and pd.notna(sig["climax_low"].loc[last]):
        stop = float(sig["climax_low"].loc[last])
    else:
        stop = float(df["Low"].tail(10).min())
    if stop <= 0: stop = close * 0.92
    risk_pct = (close - stop) / close
    if risk_pct <= 0 or risk_pct > 0.15:
        risk_pct = 0.08
        stop = close * 0.92
        
    deduction = 0
    if risk_pct > 0.10: deduction = 5
    elif risk_pct > 0.08: deduction = 3
    elif risk_pct > 0.05: deduction = 1
    
    risk_score -= deduction
    if deduction > 0: details['risk_deduction'] = -deduction
    else: details['risk_safe'] = 10
    
    risk_score = max(0, risk_score)
    
    total_score = trend_score + pattern_score + volume_score + supply_score + risk_score
    
    # 셋업 결정
    if setup_b: setup = "B"
    elif setup_a: setup = "A"
    elif setup_c: setup = "C"
    elif door_knock and squeeze: setup = "R"
    else: setup = "-"
    
    return {
        "close": close, "stop": stop,
        "trend_score": float(trend_score),
        "pattern_score": float(pattern_score),
        "volume_score": float(volume_score),
        "supply_score": float(supply_score),
        "risk_score": float(risk_score),
        "total_score": float(total_score),
        "risk_pct": float(risk_pct * 100),
        "bbw_pct": safe_get(sig["bbw_pct"], last, 0),
        "adx": adx_val, "setup": setup,
        "ma20": ma20, "ma60": ma50,
        "bb_upper": safe_get(sig["upper"], last, close),
        "door_knock": door_knock, "squeeze": squeeze,
        "score_details": details
    }
