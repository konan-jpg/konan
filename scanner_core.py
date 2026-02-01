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

def score_stock(df, sig, cfg, mktcap=None, investor_data=None, rs_3m=0, rs_6m=0, index_above_ma20=True):
    """
    종합 점수 계산 (100점 만점)
    - 추세: 25점, 위치: 30점, 거래량: 20점, 수급: 15점, 리스크: 10점
    - index_above_ma20: 지수가 20일선 위에 있으면 True (리스크 감점 적음)
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
    
    # 5. 리스크 점수 (10점) - 지수 20일선 위/아래에 따라 감점 다르게 적용
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
    
    # 리스크 감점 테이블 (지수 20일선 위/아래)
    # 지수 아래: 2배 감점 (시장 상황 안좋음)
    risk_pct_pct = risk_pct * 100  # 0.06 -> 6
    
    if index_above_ma20:  # 지수가 20일선 위 (기본)
        if risk_pct_pct <= 5: deduction = 0      # 10점
        elif risk_pct_pct <= 6: deduction = 1    # 9점
        elif risk_pct_pct <= 7: deduction = 2    # 8점
        elif risk_pct_pct <= 8: deduction = 3    # 7점
        elif risk_pct_pct <= 9: deduction = 5    # 5점
        elif risk_pct_pct <= 10: deduction = 7   # 3점
        elif risk_pct_pct <= 11: deduction = 9   # 1점
        else: deduction = 10  # 0점 (제외)
    else:  # 지수가 20일선 아래 (2배 감점)
        if risk_pct_pct <= 5: deduction = 0      # 10점
        elif risk_pct_pct <= 6: deduction = 2    # 8점
        elif risk_pct_pct <= 7: deduction = 4    # 6점
        elif risk_pct_pct <= 8: deduction = 6    # 4점
        else: deduction = 10  # 0점 (9% 이상은 제외)
    
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


def calculate_strategies(df, sig, cfg):
    """
    3개 전략별 진입가/손절가/리스크 계산 및 우선순위 결정
    기존 점수체계와 별개로 작동
    """
    if df is None or sig is None or len(df) < 20:
        return None
    
    last = df.index[-1]
    close = float(df.loc[last, "Close"])
    
    def safe_get(series, idx, default=0):
        try:
            val = series.loc[idx]
            return float(val) if pd.notna(val) else default
        except: return default
    
    # 기본값 추출
    ma20 = safe_get(sig["ma20"], last, close)
    ma10 = df["Close"].rolling(10).mean().iloc[-1] if len(df) >= 10 else close
    bb_upper = safe_get(sig["upper"], last, close * 1.05)
    climax_low = safe_get(sig["climax_low"], last, 0)
    
    # ATR(20) 계산
    tr = pd.concat([
        df['High'] - df['Low'],
        (df['High'] - df['Close'].shift(1)).abs(),
        (df['Low'] - df['Close'].shift(1)).abs()
    ], axis=1).max(axis=1)
    atr20 = tr.rolling(20).mean().iloc[-1] if len(df) >= 20 else close * 0.02
    
    # 최근 10일 최저가 (climax_low 없을 때 사용)
    swing_low = df["Low"].tail(10).min()
    base_stop = climax_low if climax_low > 0 else swing_low
    
    strategies = []
    
    # ═══════════════════════════════════════════════════
    # 전략 1: Pullback (눌림목)
    # Entry: 20MA, Stop: max(climax_low, entry - 1.2*ATR)
    # ═══════════════════════════════════════════════════
    pullback_entry = ma20
    pullback_stop = max(base_stop, pullback_entry - 1.2 * atr20)
    if pullback_stop >= pullback_entry:
        pullback_stop = pullback_entry * 0.95
    pullback_risk = (pullback_entry - pullback_stop) / pullback_entry * 100 if pullback_entry > 0 else 99
    
    # 눌림목 적합성 체크 (과거 폭발 + 현재가 > 20MA 또는 근접)
    is_pullback_candidate = (close >= ma20 * 0.97) and (close <= ma20 * 1.05) and (climax_low > 0)
    
    strategies.append({
        'type': 'pullback', 'name': '눌림목', 
        'entry': pullback_entry, 'stop': pullback_stop, 
        'risk': pullback_risk, 'candidate': is_pullback_candidate
    })
    
    # ═══════════════════════════════════════════════════
    # 전략 2: Breakout (돌파) - Hybrid Squeeze Breakout
    # Entry: BB 상단 돌파 (장중) or 밴드 근접 (종가 50%)
    # Logic: Squeeze(응축) + Trend(추세) + Volume(거래량)
    # ═══════════════════════════════════════════════════
    
    # 1. 기본 진입가 설정
    # 장중 확 돌파했으면 그 가격, 아니면 밴드 상단을 진입가로 잡음
    breakout_entry = close if close > bb_upper else bb_upper
    
    # 2. 손절가 (Scanner용 Hard Stop)
    # 진입가 - 1.5 * ATR (기존 유지)
    breakout_stop = breakout_entry - 1.5 * atr20
    if breakout_stop >= breakout_entry:
        breakout_stop = breakout_entry * 0.95
    breakout_risk = (breakout_entry - breakout_stop) / breakout_entry * 100 if breakout_entry > 0 else 99
    
    # 3. 적합성 판단 (Candidate Selection)
    # A. Squeeze Context: 밴드폭 하위 30% (힘이 응축됨)
    bbw_pct = safe_get(sig.get("bbw_pct", pd.Series()), last, 50)
    is_squeeze = (bbw_pct <= 30)
    
    # B. Active Breakout: 이미 밴드 상단을 뚫었거나, 97% 수준까지 근접 (Door Knock)
    is_breaking_out = (close >= bb_upper * 0.97)
    
    # C. Trend Filter: 정배열 또는 횡보 (하락추세만 배제)
    # - 정배열: MA20 > MA50
    # - 횡보 허용: MA20과 MA50 차이가 3% 이내면 횡보로 간주
    ma50 = safe_get(sig.get("ma50", pd.Series()), last, close)
    ma_diff_pct = abs(ma20 - ma50) / ma50 * 100 if ma50 > 0 else 0
    is_trend_aligned = (ma20 > ma50)
    is_sideways = (ma_diff_pct <= 5)  # 5% 이내면 횡보
    is_trend_ok = is_trend_aligned or is_sideways  # 정배열이거나 횡보면 OK
    
    # D. Volume Filter: 거래량이 너무 죽지 않았는지 (20일 평균의 70% 이상)
    vol_ma20_val = safe_get(sig.get("vol_ma20", pd.Series()), last, 0)
    has_volume = (df.iloc[-1]["Volume"] >= vol_ma20_val * 0.7) if vol_ma20_val > 0 else True
    
    # 최종 조건: 
    # (돌파중임) AND (스퀴즈 상태임 OR 정배열/횡보 상태임) AND (거래량 받쳐줌)
    # 사용자 피드백: "스퀴즈 -> 돌파 -> 슈팅" 패턴 선호
    # 횡보 허용: MA20과 MA50 차이 3% 이내
    is_breakout_candidate = is_breaking_out and (is_squeeze or is_trend_ok) and has_volume
    
    strategies.append({
        'type': 'breakout', 'name': 'Squeeze돌파',
        'entry': breakout_entry, 'stop': breakout_stop,
        'risk': breakout_risk, 'candidate': is_breakout_candidate
    })
    
    # ═══════════════════════════════════════════════════
    # 전략 3: O'Neil (Pocket Pivot)
    # Entry: 당일 종가, Stop: max(10MA, entry - ATR)
    # ═══════════════════════════════════════════════════
    oneil_entry = close
    oneil_stop = max(ma10, close - atr20)
    if oneil_stop >= oneil_entry:
        oneil_stop = oneil_entry * 0.94
    oneil_risk = (oneil_entry - oneil_stop) / oneil_entry * 100 if oneil_entry > 0 else 99
    
    # 오닐 패턴 적합성 체크
    is_oneil_candidate = False
    oneil_pattern = ""
    if len(df) >= 2:
        today = df.iloc[-1]
        prev = df.iloc[-2]
        vol_ma = df['Volume'].rolling(20).mean().iloc[-1] if len(df) >= 20 else df['Volume'].mean()
        
        # Inside Day
        if today['High'] < prev['High'] and today['Low'] > prev['Low']:
            is_oneil_candidate = True
            oneil_pattern = "Inside Day"
        # Oops Reversal
        elif today['Open'] < prev['Low'] and today['Close'] > prev['Low']:
            is_oneil_candidate = True
            oneil_pattern = "Oops Reversal"
        # Pocket Pivot
        elif today['Volume'] > vol_ma * 2 and today['Close'] > today['Open']:
            is_oneil_candidate = True
            oneil_pattern = "Pocket Pivot"
    
    strategies.append({
        'type': 'oneil', 'name': oneil_pattern if oneil_pattern else '오닐',
        'entry': oneil_entry, 'stop': oneil_stop,
        'risk': oneil_risk, 'candidate': is_oneil_candidate
    })
    
    # ═══════════════════════════════════════════════════
    # 우선순위 결정: candidate가 True인 것 우선, 그 중 리스크 낮은 순
    # ═══════════════════════════════════════════════════
    strategies.sort(key=lambda x: (not x['candidate'], x['risk']))
    
    # 순위 부여
    for i, s in enumerate(strategies):
        s['rank'] = i + 1
    
    return {
        'strategies': strategies,
        # 1순위 전략 정보 (CSV 저장용)
        'strat1_type': strategies[0]['type'],
        'strat1_name': strategies[0]['name'],
        'strat1_entry': strategies[0]['entry'],
        'strat1_stop': strategies[0]['stop'],
        'strat1_risk': strategies[0]['risk'],
        # 2순위
        'strat2_type': strategies[1]['type'],
        'strat2_name': strategies[1]['name'],
        'strat2_entry': strategies[1]['entry'],
        'strat2_stop': strategies[1]['stop'],
        'strat2_risk': strategies[1]['risk'],
        # 3순위
        'strat3_type': strategies[2]['type'],
        'strat3_name': strategies[2]['name'],
        'strat3_entry': strategies[2]['entry'],
        'strat3_stop': strategies[2]['stop'],
        'strat3_risk': strategies[2]['risk'],
    }
