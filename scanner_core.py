import numpy as np
import pandas as pd

def bollinger_bands(close, n=20, k=2.0):
    """볼린저밴드 계산"""
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std(ddof=0)
    upper = mid + k * sd
    lower = mid - k * sd
    return mid, upper, lower

def bandwidth(mid, upper, lower):
    """밴드폭 계산 - NaN 처리"""
    result = (upper - lower) / mid.replace(0, np.nan)
    return result.fillna(0)

def percentile_rank(s, lookback):
    """백분위 순위 계산"""
    def pct(x):
        if len(x) < 2:
            return np.nan
        last = x[-1]
        return 100.0 * (np.sum(x <= last) - 1) / (len(x) - 1)
    return s.rolling(lookback).apply(pct, raw=True)

def adx(high, low, close, n=14):
    """ADX 지표 계산"""
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
    """거래량 급등 기준봉 감지"""
    vol = df[vol_col]
    vol_avg20 = vol.rolling(20).mean()
    is_climax = vol >= (mult * vol_avg20)
    climax_high = df["High"].where(is_climax)
    climax_low = df["Low"].where(is_climax)
    return climax_high.ffill(), climax_low.ffill(), is_climax

def detect_volume_dryup(df, cfg):
    """거래량 건조 감지"""
    vol = df["Volume"]
    close = df["Close"]
    
    threshold = cfg.get("volume_dryup", {}).get("threshold_pct", 0.7)
    lookback = cfg.get("volume_dryup", {}).get("lookback_days", 10)
    min_days = cfg.get("volume_dryup", {}).get("min_dryup_days", 3)
    
    vol_avg20 = vol.rolling(20).mean()
    is_dryup = vol < (threshold * vol_avg20)
    dryup_count = is_dryup.rolling(lookback).sum()
    
    is_down = close < close.shift(1)
    down_dryup = (is_down & is_dryup).rolling(lookback).sum()
    
    return {
        "is_dryup": is_dryup,
        "dryup_count": dryup_count,
        "down_dryup_count": down_dryup,
        "has_accumulation_signal": dryup_count >= min_days
    }

def detect_rebreakout(df, sig, lookback=60):
    """재돌파 패턴 감지"""
    close = df["Close"]
    upper = sig["upper"]
    
    past_breakout = (close > upper).rolling(lookback).max().fillna(0).astype(bool)
    ma20 = close.rolling(20).mean()
    near_ma20 = (close / ma20 - 1).abs() <= 0.03
    today_breakout = close > upper
    rebreakout = past_breakout.shift(1) & today_breakout
    
    return {
        "past_breakout": past_breakout,
        "near_ma20": near_ma20,
        "today_breakout": today_breakout,
        "rebreakout": rebreakout
    }

def calculate_signals(df, cfg):
    """기술적 지표 계산"""
    if df is None or len(df) < 60:
        return None
    
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    vol = df["Volume"]
    
    # 볼린저밴드 (60, 2)
    n = cfg.get("bollinger", {}).get("length", 60)
    k = cfg.get("bollinger", {}).get("stdev", 2.0)
    mid, upper, lower = bollinger_bands(close, n=n, k=k)
    bbw = bandwidth(mid, upper, lower)
    bbw_pct = percentile_rank(bbw, 60)
    
    adx_val = adx(high, low, close, n=cfg.get("trend", {}).get("adx_len", 14))
    climax_high, climax_low, is_climax = find_climax_bar(df, mult=cfg.get("volume", {}).get("climax_mult", 5.0))
    
    squeeze = bbw_pct <= 20  # 하위 20%
    expansion = bbw_pct >= 80
    
    breakout_60 = close > upper
    vol_confirm = vol >= 1.5 * vol.rolling(20).mean()
    adx_ok = adx_val >= cfg.get("trend", {}).get("adx_min", 20)
    
    setup_a = squeeze & breakout_60 & vol_confirm & adx_ok
    setup_b = (climax_high.notna()) & (close > climax_high) & vol_confirm
    
    ma20 = close.rolling(20).mean()
    ma20_crossover = (close > ma20) & (close.shift(1) <= ma20.shift(1))
    setup_c = ma20_crossover & vol_confirm & adx_ok
    
    dryup_info = detect_volume_dryup(df, cfg)
    
    sig_base = {
        "upper": upper,
        "lower": lower,
        "mid": mid,
        "bbw": bbw,
        "bbw_pct": bbw_pct,
        "adx": adx_val,
        "climax_high": climax_high,
        "climax_low": climax_low,
        "is_climax": is_climax,
        "setup_a": setup_a,
        "setup_b": setup_b,
        "setup_c": setup_c,
        "squeeze": squeeze,
        "expansion": expansion,
        "vol_confirm": vol_confirm,
        "ma20": ma20,
    }
    
    rebreakout_info = detect_rebreakout(df, sig_base)
    
    return {
        **sig_base,
        **dryup_info,
        **rebreakout_info,
    }

def score_stock(df, sig, cfg, mktcap=None, investor_data=None, rs_3m=0, rs_6m=0):
    """
    100점 만점 - 통계적 표준 구조
    
    ① 추세 (25점)
    ② 위치 - Door/Squeeze/Memory (30점) 
    ③ 거래량 - 3단계 구조 (20점)
    ④ 수급 (15점)
    ⑤ 리스크 (10점)
    """
    if sig is None:
        return None
    
    last = df.index[-1]
    close = float(df.loc[last, "Close"])
    high = df["High"]
    low = df["Low"]
    vol = df["Volume"]
    
    mas = {p: float(df["Close"].rolling(p).mean().loc[last]) for p in cfg.get("trend", {}).get("ma_periods", [20, 50, 200])}
    
    weights = cfg.get("scoring", {})
    
    # ========== 1. 추세 점수 (25점) ==========
    trend_score = 0
    if close > mas.get(20, 0):  trend_score += 5
    if close > mas.get(50, 0):  trend_score += 5
    if close > mas.get(200, 0): trend_score += 5
    if mas.get(20, 0) > mas.get(50, 0):  trend_score += 3
    if mas.get(50, 0) > mas.get(200, 0): trend_score += 2
    
    adx_val = float(sig["adx"].loc[last])
    if adx_val >= 40:     trend_score += 5
    elif adx_val >= 30:   trend_score += 4
    elif adx_val >= 25:   trend_score += 3
    elif adx_val >= 20:   trend_score += 2
    
    trend_score = min(trend_score, 25)
    
    # ========== 2. 위치 점수 (30점) - VCP 핵심 ==========
    location_score = 0
    tags = []
    
    bb_upper = float(sig["upper"].loc[last])
    bb_mid = float(sig["mid"].loc[last])
    
    # A. Door Knock (10점): 60BB 상단 95~102%
    door_low = bb_upper * 0.95
    door_high = bb_upper * 1.02
    if door_low <= close <= door_high:
        location_score += 10
        tags.append("🚪Door")
    
    # B. Squeeze (10점): Bandwidth 하위 20%
    bbw_rank = float(sig["bbw_pct"].loc[last])
    if bbw_rank <= 20:
        location_score += 10
        tags.append("🧘Squeeze")
    
    # C. Memory (10점): 과거 기준봉 종가 ±5%
    vol_lookback = df.iloc[-60:]  # 최근 60일
    max_vol_idx = vol_lookback["Volume"].idxmax()
    memory_price = float(vol_lookback.loc[max_vol_idx, "Close"])
    
    if abs(close / memory_price - 1) <= 0.05:
        location_score += 10
        tags.append("🧠Memory")
    
    location_score = min(location_score, 30)
    
    # ========== 3. 거래량 점수 (20점) - 3단계 구조 ==========
    volume_score = 0
    
    # 3-1. 과거 폭발 (5점): 60일 내 3배 이상
    vol_past_60 = df["Volume"].iloc[-61:-1]
    vol_ma20_past = vol.rolling(20).mean().iloc[-61:-1]
    if (vol_past_60 >= vol_ma20_past * 3.0).any():
        volume_score += 5
        tags.append("🔥Past")
    
    # 3-2. 수축 (7점): 최근 10일 중 3일 이상 70% 이하
    dryup_count = float(sig.get("dryup_count", pd.Series([0])).loc[last])
    if dryup_count >= 5:
        volume_score += 7
        tags.append("💧Dry+")
    elif dryup_count >= 3:
        volume_score += 5
        tags.append("💧Dry")
    
    # 3-3. 현재/최근 활성화 (8점): 당일 거래량
    vol_now = float(vol.loc[last])
    vol_ma_now = float(vol.rolling(20).mean().loc[last])
    vol_ratio = vol_now / vol_ma_now if vol_ma_now > 0 else 0
    
    if 1.2 <= vol_ratio <= 2.0:
        volume_score += 5
        tags.append("🚀Pivot")
    elif 2.0 < vol_ratio <= 3.0:
        volume_score += 8
        tags.append("🚀Pivot+")
    elif vol_ratio > 3.0:
        volume_score += 3
        tags.append("⚠️Hot")
    
    volume_score = min(volume_score, 20)
    
    # ========== 4. 수급 점수 (15점) ==========
    supply_score = 0
    
    if investor_data:
        foreign_consec = investor_data.get("foreign_consecutive_buy", 0)
        if foreign_consec >= 5:
            supply_score += 8
        elif foreign_consec >= 3:
            supply_score += 5
        elif foreign_consec >= 1:
            supply_score += 2
        
        inst_net = investor_data.get("inst_net_buy_5d", 0)
        if inst_net > 0:
            supply_score += 4
        
        foreign_net = investor_data.get("foreign_net_buy_5d", 0)
        if foreign_net > 0:
            supply_score += 3
    
    supply_score = min(supply_score, 15)
    
    # ========== 5. 리스크 점수 (10점) ==========
    risk_score = 10
    
    if bool(sig["setup_b"].loc[last]) and pd.notna(sig["climax_low"].loc[last]):
        stop = float(sig["climax_low"].loc[last])
    else:
        stop = float(df["Low"].tail(10).min())
    
    if stop <= 0:
        stop = close * 0.92
    
    risk_pct = (close - stop) / close
    
    if risk_pct <= 0 or risk_pct > 0.15:
        risk_pct = 0.08
        stop = close * 0.92
    
    if risk_pct > 0.10:
        risk_score -= 5
    elif risk_pct > 0.08:
        risk_score -= 3
    elif risk_pct > 0.05:
        risk_score -= 1
    
    risk_score = max(0, risk_score)
    
    # ========== 총점 ==========
    total_score = trend_score + location_score + volume_score + supply_score + risk_score
    
    # Setup 태그 (참고용)
    if bool(sig.get("rebreakout", pd.Series([False])).loc[last]):
        setup = "R"
    elif bool(sig["setup_b"].loc[last]):
        setup = "B"
    elif bool(sig["setup_a"].loc[last]):
        setup = "A"
    elif bool(sig.get("setup_c", pd.Series([False])).loc[last]):
        setup = "C"
    else:
        setup = "-"
    
    return {
        "close": close,
        "trend_score": float(trend_score),
        "pattern_score": float(location_score),  # UI 호환
        "volume_score": float(volume_score),
        "supply_score": float(supply_score),
        "risk_score": float(risk_score),
        "total_score": float(total_score),
        "stop": stop,
        "risk_pct": float(risk_pct * 100),
        "bbw_pct": bbw_rank,
        "adx": adx_val,
        "setup": setup,
        "ma20": mas.get(20, 0),
        "ma60": mas.get(50, 0),
        "bb_upper": bb_upper,
        "memory_price": memory_price,
        "vol_ratio": round(vol_ratio, 2),
        "tags": " ".join(tags) if tags else "-",
        "dryup_count": int(dryup_count),
        "rebreakout": bool(sig.get("rebreakout", pd.Series([False])).loc[last]),
        "foreign_consec_buy": investor_data.get("foreign_consecutive_buy", 0) if investor_data else 0,
        "foreign_net_5d": investor_data.get("foreign_net_buy_5d", 0) if investor_data else 0,
        "inst_net_5d": investor_data.get("inst_net_buy_5d", 0) if investor_data else 0,
        # Legacy 호환
        "trigger_score": float(location_score),
        "liq_score": float(volume_score),
    }
