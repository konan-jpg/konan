import numpy as np
import pandas as pd

# -----------------------------
# Indicator Utils
# -----------------------------
def bollinger_bands(close, n=60, k=2):
    """볼린저밴드 계산"""
    mid = close.rolling(n).mean()
    std = close.rolling(n).std(ddof=0)
    return mid, mid + k * std, mid - k * std

def bandwidth(mid, upper, lower):
    """밴드폭 계산 (0 방어 + NaN 제거)"""
    result = (upper - lower) / mid.replace(0, np.nan)
    return result.fillna(0)

# -----------------------------
# Core Scoring (30점 체계)
# -----------------------------
def score_stock(df, mode="realtime"):
    """
    30점 만점 패턴 스코어링
    
    Args:
        df: OHLCV DataFrame
        mode: "realtime" | "image" | "daily"
    
    Returns:
        dict: 점수 및 메타데이터
    """
    
    if df is None or len(df) < 80:
        return None
    
    close = df["Close"]
    vol = df["Volume"]
    
    # 볼린저밴드 계산
    mid, upper, lower = bollinger_bands(close, 60, 2)
    bbw = bandwidth(mid, upper, lower)
    
    last = df.index[-1]
    
    score = 0
    tags = []
    
    # ---------------------------------
    # 1. Door Knock (10점)
    # ---------------------------------
    door_low = upper.loc[last] * 0.95
    door_high = upper.loc[last] * 1.02
    if door_low <= close.loc[last] <= door_high:
        score += 10
        tags.append("🚪 Door")
    
    # ---------------------------------
    # 2. Volatility Squeeze (10점)
    # ---------------------------------
    bbw_rank = bbw.rank(pct=True)
    if bbw_rank.loc[last] <= 0.20:
        score += 10
        tags.append("🧘 Squeeze")
    
    # ---------------------------------
    # 3. Memory (10점)
    # ---------------------------------
    vol_lookback = df.iloc[-60:]  # 최근 60일
    max_vol_idx = vol_lookback["Volume"].idxmax()
    memory_price = vol_lookback.loc[max_vol_idx, "Close"]
    
    if abs(upper.loc[last] / memory_price - 1) <= 0.05:
        score += 10
        tags.append("🧠 Memory")
    
    # ---------------------------------
    # 4. Volume Logic (mode dependent)
    # ---------------------------------
    vol_ma20 = vol.rolling(20).mean().loc[last]
    vol_ratio = vol.loc[last] / vol_ma20 if vol_ma20 > 0 else 0
    
    if mode in ["realtime", "image"]:
        # 과열 감점 (선취매 전략)
        if vol_ratio > 2.5:
            score -= 5
            tags.append("🔥 Overheat")
    
    elif mode == "daily":
        # 돌파 확인 보조 가점 (장마감 스캐너)
        if vol_ratio >= 3.0 and close.loc[last] > upper.loc[last] * 1.01:
            score += 5
            tags.append("🚀 Breakout+")
        elif vol_ratio >= 2.0 and close.loc[last] >= upper.loc[last]:
            score += 3
            tags.append("📈 Breakout")
    
    # ---------------------------------
    # 5. 추가 메타데이터
    # ---------------------------------
    ma20 = close.rolling(20).mean().loc[last]
    ma60 = close.rolling(60).mean().loc[last]
    
    return {
        "score": float(score),
        "close": float(close.loc[last]),
        "bb_upper": float(upper.loc[last]),
        "bb_mid": float(mid.loc[last]),
        "memory_price": float(memory_price),
        "vol_ratio": round(float(vol_ratio), 2),
        "ma20": float(ma20),
        "ma60": float(ma60),
        "tags": " | ".join(tags) if tags else "-",
        "mode": mode
    }


# -----------------------------
# Legacy Compatibility Functions
# (update_daily.py 호환용)
# -----------------------------
def calculate_signals(df, cfg):
    """
    기존 100점 체계용 시그널 계산 (update_daily.py 호환)
    30점 체계와는 별도로 유지
    """
    if df is None or len(df) < 60:
        return None
    
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    vol = df["Volume"]
    
    # 볼린저밴드
    n = cfg.get("bollinger", {}).get("length", 60)
    k = cfg.get("bollinger", {}).get("stdev", 2.0)
    mid, upper, lower = bollinger_bands(close, n, k)
    bbw = bandwidth(mid, upper, lower)
    
    # 기본 시그널 (기존 로직 유지)
    return {
        "upper": upper,
        "lower": lower,
        "mid": mid,
        "bbw": bbw,
        "squeeze": pd.Series([False] * len(df), index=df.index),
        "vol_confirm": pd.Series([False] * len(df), index=df.index),
    }
