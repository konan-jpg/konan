# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import glob
import os
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from news_analyzer import search_naver_news
import FinanceDataReader as fdr
import yaml
from scanner_core import calculate_signals, score_stock
from image_analysis import analyze_chart_image
st.set_page_config(layout="wide", page_title="추세추종 스캐너")
# ---------------------------------------------------
# Helper Functions
# ---------------------------------------------------
@st.cache_data(ttl=300)
def load_config():
    """Load configuration from config.yaml"""
    cfg_path = "config.yaml"
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}
@st.cache_data(ttl=300)
def load_data():
    """Load scanner result and sector ranking data"""
    df = None
    filename = None
    # 1. merged daily result
    merged_files = glob.glob("data/scanner_output*.csv")
    merged_files = [f for f in merged_files if "chunk" not in f]
    if merged_files:
        def extract_date(fn):
            try:
                parts = os.path.basename(fn).replace('.csv', '').split('_')
                if len(parts) >= 3:
                    return parts[-1]
                return '0000-00-00'
            except Exception:
                return '0000-00-00'
        latest_file = max(merged_files, key=extract_date)
        df = pd.read_csv(latest_file, dtype={'code': str})
        filename = os.path.basename(latest_file)
    else:
        # fallback: merge partial chunks
        chunk_files = glob.glob("data/partial/scanner_output*chunk*.csv")
        if chunk_files:
            df_list = []
            for f in sorted(chunk_files):
                try:
                    sub_df = pd.read_csv(f, dtype={'code': str})
                    df_list.append(sub_df)
                except Exception:
                    continue
            if df_list:
                df = pd.concat(df_list, ignore_index=True)
                if 'code' in df.columns:
                    df.drop_duplicates(subset=['code'], keep='first', inplace=True)
                filename = f"Merged from {len(df_list)} chunks"
    # sector rankings
    sector_df = None
    if os.path.exists("data/sector_rankings.csv"):
        sector_df = pd.read_csv("data/sector_rankings.csv")
    return df, sector_df, filename
@st.cache_data
def get_krx_codes():
    """Return DataFrame with KRX stock codes and names"""
    try:
        df = fdr.StockListing("KRX")
        if df is None or df.empty:
            raise ValueError("Empty KRX data")
        return df[['Code', 'Name']]
    except Exception as e:
        # 1. Try static file fallback
        try:
            if os.path.exists("data/krx_tickers.csv"):
                df_static = pd.read_csv("data/krx_tickers.csv", dtype={'Code': str})
                return df_static[['Code', 'Name']]
        except Exception:
            pass
        # 2. Fallback using scanner data
        df_scan, _, _ = load_data()
        if df_scan is not None and not df_scan.empty:
            fallback = df_scan[['code', 'name']].rename(columns={'code': 'Code', 'name': 'Name'})
            return fallback.drop_duplicates()
        return pd.DataFrame({'Code':[], 'Name':[]})
def get_setup_explanations():
    return {
        'R': "🔥 재돌파 패턴 - 60일 내 BB 60-2 돌파 후 눌림 → 재돌파 (가장 강력)",
        'B': "거래량 급등(평균 5배) 후 고점 돌파 + 거래량 재확인",
        'A': "볼린저밴드(60,2) 상단 돌파 + 밴드폭 수축 + ADX 강세",
        'C': "20일 이평선 돌파 + 거래량 증가 + ADX 상승 추세",
        '-': "기본 추세 및 유동성 기준만 충족",
    }
def get_score_explanations():
    return {
        'trend_score': {
            'name': '추세 점수 (25점)',
            'description': '이동평균선 정렬과 ADX 추세 강도',
            'components': [
                '현재가 > 20일선: +5점',
                '현재가 > 50일선: +5점',
                '현재가 > 200일선: +5점',
                'MA 정렬 (20>50, 50>200): +5점',
                'ADX 강도: +2~5점'
            ]
        },
        'pattern_score': {
            'name': '패턴 점수 (30점)',
            'description': '매수 타이밍 신호 (재돌파, VCP 특성)',
            'components': [
                '재돌파 패턴 (Setup R): +15',
                '기준봉 돌파 (Setup B): +10',
                '스퀴즈 돌파 (Setup A): +8',
                'MA20 돌파 (Setup C): +5',
                '스퀴즈 상태: +5'
            ]
        },
        'volume_score': {
            'name': '거래량 점수 (20점)',
            'description': '거래량 급등 및 건조 신호',
            'components': [
                '거래량 확인: +8',
                '거래량 건조: +7/5',
                '하락 시 거래량 감소: +5'
            ]
        },
        'supply_score': {
            'name': '수급 점수 (15점)',
            'description': '외국인/기관 연속 매수',
            'components': [
                '외국인 연속 매수 5일+: +8',
                '외국인 연속 매수 3일+: +5',
                '기관 5일 순매수: +4',
                '외국인 5일 순매수: +3'
            ]
        },
        'risk_score': {
            'name': '리스크 점수 (10점)',
            'description': '손절가 거리 기반 리스크',
            'components': [
                '리스크 5% 이하: 10점',
                '리스크 5~8%: -1점',
                '리스크 8~10%: -3점',
                '리스크 10%+: -5점'
            ]
        }
    }
# ---------------------------------------------------
# UI Rendering for a single stock (used by all modes)
# ---------------------------------------------------
def display_stock_report(row, sector_df=None, rs_3m=None, rs_6m=None):
    """Render detailed analysis for a given stock row (Series)."""
    st.markdown("---")
    st.subheader(f"📊 {row.get('name', 'N/A')} ({row.get('code', '')}) 상세 분석")
    # RS display (optional)
    if rs_3m is not None:
        st.metric("3개월 RS", f"{rs_3m}")
    if rs_6m is not None:
        st.metric("6개월 RS", f"{rs_6m}")
    # sector badge
    stock_sector = row.get('sector', '기타')
    is_leader_sector = False
    if sector_df is not None:
        market_leaders = sector_df.head(5)['Sector'].tolist()
        is_leader_sector = stock_sector in market_leaders
    if is_leader_sector:
        st.success(f"🏆 **주도 섹터**: {stock_sector} ← 시장 상위 5개 업종에 속함!")
    else:
        st.info(f"📌 **업종**: {stock_sector}")
    # basic info grid
    foreign = row.get('foreign_consec_buy', 0)
    inst_net = row.get('inst_net_5d', 0)
    risk_pct = row.get('risk_pct', 0)
    st.markdown(f"""
    <style>
    .info-grid {{
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 5px;
        margin-bottom: 10px;
    }}
    .info-box {{
        background-color: #f0f2f6;
        padding: 8px;
        border-radius: 5px;
        text-align: center;
    }}
    .info-label {{ font-size: 11px; color: #666; }}
    .info-value {{ font-size: 14px; font-weight: bold; margin-top: 2px; }}
    @media (max-width: 600px) {{ .info-grid {{ grid-template-columns: repeat(3, 1fr); }} .info-value {{ font-size: 13px; }} }}
    </style>
    <div class="info-grid">
        <div class="info-box"><div class="info-label">현재가</div><div class="info-value">{row['close']:,.0f}원</div></div>
        <div class="info-box"><div class="info-label">총점</div><div class="info-value">{row['total_score']:.0f}점</div></div>
        <div class="info-box"><div class="info-label">셋업</div><div class="info-value">{row.get('setup', '-')}</div></div>
        <div class="info-box"><div class="info-label">리스크</div><div class="info-value">{risk_pct:.1f}%</div></div>
        <div class="info-box"><div class="info-label">외인연속</div><div class="info-value">{int(foreign)}일</div></div>
        <div class="info-box"><div class="info-label">기관5일</div><div class="info-value">{inst_net/1e8:,.0f}억</div></div>
    </div>
    """, unsafe_allow_html=True)
    # setup explanation
    setup_type = row.get('setup', '-')
    with st.expander(f"ℹ️ 셋업 설명 (현재: Setup {setup_type})", expanded=False):
        setup_explanations = get_setup_explanations()
        for stype, desc in setup_explanations.items():
            if stype == setup_type:
                st.success(f"**▶ Setup {stype}** (현재): {desc}")
            else:
                st.write(f"**Setup {stype}**: {desc}")
    st.markdown("---")
    # score breakdown
    st.markdown("#### 📈 점수 구성 상세 (100점 만점)")
    
    # Calculate RS Bonus for display
    rs3_bonus = 0
    rs6_bonus = 0
    # Assuming standard weight 5 if not in row (fallback)
    if rs_3m is not None and rs_3m >= 80: rs3_bonus = 5
    if rs_6m is not None and rs_6m >= 80: rs6_bonus = 5
    rs_total_bonus = rs3_bonus + rs6_bonus
    score_info = get_score_explanations()
    score_data = {
        '추세': row.get('trend_score', 0),
        '패턴': row.get('pattern_score', row.get('trigger_score', 0)),
        '거래량': row.get('volume_score', row.get('liq_score', 0)),
        '수급': row.get('supply_score', 0),
        '리스크': row.get('risk_score', 10)
    }
    
    # Adjust pattern score display to separate RS if needed, or just show it being added
    # Here we just show the metric clearly
    
    max_scores = [25, 30, 20, 15, 10]
    cols = st.columns(5) # Back to 5 columns to match Total Score components
    
    with cols[0]: st.metric("추세", f"{score_data['추세']:.0f}/25")
    
    # Pattern Score specialized display
    pat_str = f"{score_data['패턴']:.0f}/30"
    with cols[1]: 
        st.metric("패턴 (RS포함)", pat_str, delta=f"+RS {rs_total_bonus}" if rs_total_bonus > 0 else None)
        
    with cols[2]: st.metric("거래량", f"{score_data['거래량']:.0f}/20")
    with cols[3]: st.metric("수급", f"{score_data['수급']:.0f}/15")
    with cols[4]: st.metric("리스크", f"{score_data['리스크']:.0f}/10")
    for key, info in score_info.items():
        with st.expander(f"🔹 {info['name']}", expanded=False):
            st.markdown(f"**{info['description']}**")
            for comp in info['components']:
                st.write(f"• {comp}")
            if key == 'pattern_score':
                st.info(f"💡 **RS 가산점 적용**: 3개월/6개월 RS가 80점 이상이면 각각 가산점 부여")
    # supply info if exists
    if 'foreign_net_5d' in row or 'inst_net_5d' in row:
        st.markdown("---")
        st.markdown("#### 💰 최근 수급 현황")
        sup_cols = st.columns(3)
        with sup_cols[0]:
            foreign_consec = row.get('foreign_consec_buy', 0)
            if pd.notna(foreign_consec):
                st.write(f"**외국인 연속 매수**: {int(foreign_consec)}일")
        with sup_cols[1]:
            foreign_net = row.get('foreign_net_5d', 0)
            if pd.notna(foreign_net):
                st.write(f"**외국인 5일 순매수**: {foreign_net/1e8:,.1f}억")
        with sup_cols[2]:
            inst_net = row.get('inst_net_5d', 0)
            if pd.notna(inst_net):
                st.write(f"**기관 5일 순매수**: {inst_net/1e8:,.1f}억")
    # 전략 추천
    st.markdown("---")
    st.markdown("#### 🎯 매수 전략 추천")
    try:
        import textwrap
        current_price = row['close']
        ma20 = row.get('ma20', current_price)
        base_stop = row.get('stop', current_price * 0.92)
        # Pullback
        pullback_price = ma20
        pullback_stop = max(pullback_price * 0.97, base_stop)
        risk_pullback = (pullback_price - pullback_stop) / pullback_price * 100
        # Breakout
        bb_upper = row.get('bb_upper', current_price * 1.05)
        breakout_price = bb_upper if bb_upper > current_price else current_price * 1.02
        breakout_stop = breakout_price * 0.95
        risk_breakout = (breakout_price - breakout_stop) / breakout_price * 100
        # O'Neil
        oneil_price = 0
        oneil_stop = 0
        oneil_risk = 0
        oneil_setup_name = "-"
        oneil_msg = "패턴 형성 대기중"
        try:
            sub_df = fdr.DataReader(row['code'], datetime.now() - timedelta(days=60), datetime.now())
            if sub_df is not None and len(sub_df) >= 2:
                today = sub_df.iloc[-1]
                prev = sub_df.iloc[-2]
                ma20_chart = sub_df['Close'].rolling(20).mean().iloc[-1]
                vol_ma = sub_df['Volume'].rolling(20).mean().iloc[-1]
                if today['High'] < prev['High'] and today['Low'] > prev['Low']:
                    oneil_price = today['High']
                    oneil_setup_name = "Inside Day"
                    oneil_msg = f"고가({int(today['High']):,}원) 돌파 시"
                elif today['Open'] < prev['Low'] and today['Close'] > prev['Low'] and today['Close'] > ma20_chart:
                    oneil_price = today['Close']
                    oneil_setup_name = "Oops Reversal"
                    oneil_msg = "반전 확인. 종가/익일시가"
                elif today['Volume'] > vol_ma * 2.5 and today['Close'] > prev['Close'] * 1.04:
                    oneil_price = today['Close']
                    oneil_setup_name = "Pocket Pivot"
                    oneil_msg = "거래량 급등. 매수 유효"
                if oneil_price > 0:
                    oneil_stop = oneil_price * 0.93
                    oneil_risk = (oneil_price - oneil_stop) / oneil_price * 100
        except Exception:
            pass
        # ranking
        strategies = [
            ("💎 오닐/미너비니", 100 if oneil_price > 0 else 30, oneil_msg if oneil_price > 0 else "패턴 대기중"),
            ("📉 눌림목", 95 if -2 <= (current_price - ma20)/ma20*100 <= 4 else 70 if -5 <= (current_price - ma20)/ma20*100 <= 6 else 50, "MA20 지지선 근접"),
            ("🚀 추세 돌파", 90 if current_price >= bb_upper*0.98 else 75 if current_price >= bb_upper*0.95 else 55, "볼린저밴드 상단 접근")
        ]
        strategies.sort(key=lambda x: x[1], reverse=True)
        st.markdown("**🎯 매수 전략 우선순위**")
        for rank, (name, score, reason) in enumerate(strategies, 1):
            if rank == 1:
                st.success(f"🥇 **{rank}순위**: {name} - {reason}")
            elif rank == 2:
                st.info(f"🥈 **{rank}순위**: {name} - {reason}")
            else:
                st.warning(f"🥉 **{rank}순위**: {name} - {reason}")
        # Card UI
        col_sc1, col_sc2, col_sc3 = st.columns(3)
        with col_sc1:
            html_1 = f'<div style="background-color:rgba(0,255,0,0.1); padding:10px; border-radius:10px;">' \
                   f'<strong>📉 눌림목</strong><br>진입: <strong>{pullback_price:,.0f}원</strong><br>손절: {pullback_stop:,.0f}원<br>' \
                   f'<span style="font-size:0.8em; color:#666;">리스크: {risk_pullback:.1f}%</span></div>'
            st.markdown(html_1, unsafe_allow_html=True)
        with col_sc2:
            html_2 = f'<div style="background-color:rgba(255,165,0,0.1); padding:10px; border-radius:10px;">' \
                   f'<strong>🚀 추세 돌파</strong><br>진입: <strong>{breakout_price:,.0f}원</strong><br>손절: {breakout_stop:,.0f}원<br>' \
                   f'<span style="font-size:0.8em; color:#666;">리스크: {risk_breakout:.1f}%</span></div>'
            st.markdown(html_2, unsafe_allow_html=True)
        with col_sc3:
            bg = "rgba(138,43,226,0.1)" if oneil_price > 0 else "rgba(128,128,128,0.1)"
            content = f'진입: <strong>{oneil_price:,.0f}원</strong><br>손절: {oneil_stop:,.0f}원<br>' \
                      f'<span style="font-size:0.8em; color:#666;">리스크: {oneil_risk:.1f}%</span>' if oneil_price > 0 else f'<span style="color:gray;">{oneil_msg}</span><br><span style="font-size:0.8em;">패턴이 나타나면 추천됩니다</span>'
            html_3 = f'<div style="background-color:{bg}; padding:10px; border-radius:10px;">' \
                   f'<strong>💎 오닐/미너비니</strong><br><span style="font-size:0.8em; color:#999;">({oneil_setup_name})</span><br>{content}</div>'
            st.markdown(html_3, unsafe_allow_html=True)
        st.caption(f"⚠️ 기본 손절가: {base_stop:,.0f}원 | 전략별 손절가는 진입가 기준으로 동적 계산됩니다.")
    except Exception as e:
        st.warning(f"매수 전략 계산 오류: {e}")
    # Technical indicators
    st.markdown("---")
    st.markdown("#### 📊 기술적 지표")
    ind_cols = st.columns(4)
    with ind_cols[0]:
        if 'ma20' in row and pd.notna(row['ma20']):
            st.write(f"**20일선**: {row['ma20']:,.0f}원")
    with ind_cols[1]:
        if 'ma60' in row and pd.notna(row['ma60']):
            st.write(f"**60일선**: {row['ma60']:,.0f}원")
    with ind_cols[2]:
        if 'adx' in row and pd.notna(row['adx']):
            st.write(f"**ADX**: {row['adx']:.1f}")
    with ind_cols[3]:
        if 'stop' in row and pd.notna(row['stop']):
            st.write(f"**최종 손절가격**: {row['stop']:,.0f}원")
    # News
    st.markdown("---")
    st.markdown("#### 📰 최신 뉴스")
    try:
        client_id = os.environ.get("NAVER_CLIENT_ID", "")
        client_secret = os.environ.get("NAVER_CLIENT_SECRET", "")
        if client_id and client_secret:
            news_list = search_naver_news(row['name'], client_id, client_secret, display=5)
            if news_list:
                for news in news_list:
                    title = news.get('title', '')
                    link = news.get('link', '')
                    pub_date = news.get('pubDate', '')[:16]
                    st.markdown(f"- [{title}]({link}) ({pub_date})")
            else:
                st.caption("관련 뉴스가 없습니다.")
        else:
            st.caption("네이버 API 키가 설정되지 않았습니다. (Streamlit Cloud 환경변수 필요)")
    except Exception as e:
        st.caption(f"뉴스 로드 오류: {e}")
    # Chart
    st.markdown("---")
    st.markdown("#### 📉 가격 차트 (최근 6개월)")
    try:
        chart_df = fdr.DataReader(row['code'], datetime.now() - timedelta(days=180), datetime.now())
        if chart_df is not None and len(chart_df) > 0:
            chart_df['MA20'] = chart_df['Close'].rolling(20).mean()
            chart_df['MA60'] = chart_df['Close'].rolling(60).mean()
            mid = chart_df['Close'].rolling(60).mean()
            std = chart_df['Close'].rolling(60).std()
            chart_df['BB_Upper'] = mid + 2 * std
            chart_df['BB_Lower'] = mid - 2 * std
            fig = make_subplots(rows=2, cols=1, row_heights=[0.75, 0.25], vertical_spacing=0.03, shared_xaxes=True)
            # Candlestick
            fig.add_trace(go.Candlestick(x=chart_df.index, open=chart_df['Open'], high=chart_df['High'], low=chart_df['Low'], close=chart_df['Close'], name=f'가격 {row["close"]:,.0f}', increasing_line_color='red', decreasing_line_color='blue'), row=1, col=1)
            # MA lines
            fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['MA20'], mode='lines', name=f'MA20 ({chart_df["MA20"].iloc[-1]:,.0f})', line=dict(color='orange', width=1.5)), row=1, col=1)
            fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['MA60'], mode='lines', name=f'MA60 ({chart_df["MA60"].iloc[-1]:,.0f})', line=dict(color='purple', width=1.5)), row=1, col=1)
            # BB Upper
            fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['BB_Upper'], mode='lines', name=f'BB상단 ({chart_df["BB_Upper"].iloc[-1]:,.0f})', line=dict(color='gray', width=1, dash='dot')), row=1, col=1)
            # Stop loss line
            if 'stop' in row and pd.notna(row['stop']):
                stop_price = row['stop']
                fig.add_trace(go.Scatter(x=[chart_df.index[0], chart_df.index[-1]], y=[stop_price, stop_price], mode='lines', name=f'손절 {stop_price:,.0f}', line=dict(color='red', width=1.5, dash='dash'), hoverinfo='name+y'), row=1, col=1)
            
            # 장대양봉 + 대량거래 감지 (O'Neil Pocket Pivot 등)
            vol_ma20 = chart_df['Volume'].rolling(20).mean()
            big_bullish_volume = []
            for i in range(1, len(chart_df)):
                curr = chart_df.iloc[i]
                prev = chart_df.iloc[i-1]
                body_size = abs(curr['Close'] - curr['Open'])
                candle_range = curr['High'] - curr['Low']
                is_bullish = curr['Close'] > curr['Open']
                is_big_body = body_size > candle_range * 0.6 if candle_range > 0 else False
                is_high_vol = curr['Volume'] > vol_ma20.iloc[i] * 2.0 if pd.notna(vol_ma20.iloc[i]) else False
                is_up_day = curr['Close'] > prev['Close'] * 1.03
                if is_bullish and is_big_body and is_high_vol and is_up_day:
                    big_bullish_volume.append((chart_df.index[i], curr['High']))
            
            # 장대양봉+대량거래 마커 표시
            if big_bullish_volume:
                marker_dates = [x[0] for x in big_bullish_volume]
                marker_prices = [x[1] * 1.02 for x in big_bullish_volume]  # 약간 위에 표시
                fig.add_trace(go.Scatter(x=marker_dates, y=marker_prices, mode='markers+text', name='🔥 장대양봉+대량거래', marker=dict(symbol='triangle-up', size=12, color='red'), text=['🔥' for _ in marker_dates], textposition='top center', hoverinfo='name'), row=1, col=1)
            
            # O'Neil lines (if any)
            try:
                if len(chart_df) >= 2:
                    today_c = chart_df.iloc[-1]
                    prev_c = chart_df.iloc[-2]
                    ma20_chart = chart_df['MA20'].iloc[-1]
                    vol_ma_chart = chart_df['Volume'].rolling(20).mean().iloc[-1]
                    oneil_entry = 0
                    oneil_sl = 0
                    oneil_label = ""
                    if today_c['High'] < prev_c['High'] and today_c['Low'] > prev_c['Low']:
                        oneil_entry = today_c['High']
                        oneil_sl = oneil_entry * 0.93
                        oneil_label = "Inside Day"
                    elif today_c['Open'] < prev_c['Low'] and today_c['Close'] > prev_c['Low'] and today_c['Close'] > ma20_chart:
                        oneil_entry = today_c['Close']
                        oneil_sl = oneil_entry * 0.93
                        oneil_label = "Oops"
                    elif today_c['Volume'] > vol_ma_chart * 2.5 and today_c['Close'] > prev_c['Close'] * 1.04:
                        oneil_entry = today_c['Close']
                        oneil_sl = oneil_entry * 0.93
                        oneil_label = "Pocket Pivot"
                    if oneil_entry > 0:
                        fig.add_trace(go.Scatter(x=[chart_df.index[0], chart_df.index[-1]], y=[oneil_entry, oneil_entry], mode='lines', name=f'💎진입 {oneil_entry:,.0f}', line=dict(color='purple', width=1.5, dash='dot'), hoverinfo='name+y'), row=1, col=1)
                        fig.add_trace(go.Scatter(x=[chart_df.index[0], chart_df.index[-1]], y=[oneil_sl, oneil_sl], mode='lines', name=f'💎손절 {oneil_sl:,.0f}', line=dict(color='violet', width=1, dash='dash'), hoverinfo='name+y'), row=1, col=1)
                        fig.add_annotation(x=chart_df.index[-1], y=oneil_entry, text=f"💎{oneil_label}", showarrow=True, arrowhead=2, arrowcolor='purple', ax=40, ay=-20, bgcolor='rgba(138,43,226,0.2)', bordercolor='purple', font=dict(size=10, color='purple'), row=1, col=1)
            except Exception:
                pass
            # Volume bar
            colors = ['red' if o <= c else 'blue' for o, c in zip(chart_df['Open'], chart_df['Close'])]
            fig.add_trace(go.Bar(x=chart_df.index, y=chart_df['Volume'], name='거래량', marker_color=colors, opacity=0.5), row=2, col=1)
            
            # 차트 레이아웃 설정: 범례 상단, rangeslider 비활성화
            fig.update_layout(
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0),
                xaxis_rangeslider_visible=False,
                height=500,
                margin=dict(l=50, r=50, t=50, b=30)
            )
            fig.update_xaxes(rangeslider_visible=False, row=1, col=1)
            st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.warning(f"차트 생성 오류: {e}")
# ---------------------------------------------------
# Main App UI
# ---------------------------------------------------
st.sidebar.title("메뉴")
mode = st.sidebar.radio("모드 선택", ["🔍 실시간 종목 진단", "📊 당일 시장 스캐너", "🖼️ 차트 이미지 분석"])
# Refresh button (common)
if st.sidebar.button("🔄 데이터/캐시 새로고침", help="스캔된 최신 데이터를 불러오고 화면을 갱신합니다."):
    st.cache_data.clear()
    st.rerun()
if mode == "📊 당일 시장 스캐너":
    # 기존 스캐너 UI (필터, 테이블, 선택)
    min_score = st.slider("최소 점수", 0, 100, 50, key='min_score_slider')
    df, sector_df, filename = load_data()
    if df is None:
        st.error("❌ 결과 파일이 없습니다.")
        st.stop()
    df['code'] = df['code'].astype(str).str.zfill(6)
    st.success(f"✅ 데이터 로드: {filename} (총 {len(df)}개)")
    # Market leader panel (unchanged)
    st.markdown("### 🧭 시장 주도 섹터 분석")
    col_a, col_b = st.columns(2)
    with col_a:
        st.info("📊 시장 주도 섹터 (Top-Down)")
        if sector_df is not None and len(sector_df) > 0:
            valid_sector_df = sector_df[sector_df['Sector'] != '기타']
            if len(valid_sector_df) > 0:
                top_sectors = valid_sector_df.head(5)[['Sector', 'AvgReturn_3M', 'StockCount']]
                st.dataframe(top_sectors.style.format({'AvgReturn_3M': '{:.1f}%'}), use_container_width=True, hide_index=True)
            else:
                st.caption("⚠️ 유효한 섹터 데이터가 없습니다.")
        else:
            st.caption("⚠️ 섹터 랭킹 파일(`sector_rankings.csv`)이 없습니다.")
    with col_b:
        st.success("🎯 스캐너 포착 섹터")
        if 'sector' in df.columns:
            valid_sectors = df[df['sector'] != '기타']['sector']
            if len(valid_sectors) > 0:
                scanner_sectors = valid_sectors.value_counts().head(5).reset_index()
                scanner_sectors.columns = ['Sector', 'Count']
                if sector_df is not None:
                    market_leaders = sector_df[sector_df['Sector'] != '기타'].head(5)['Sector'].tolist()
                    scanner_sectors['일치'] = scanner_sectors['Sector'].apply(lambda x: "✅" if x in market_leaders else "-")
                st.dataframe(scanner_sectors, use_container_width=True, hide_index=True)
            else:
                st.caption("⚠️ 섹터 정보가 '기타'만 있습니다.")
        else:
            st.caption("⚠️ 섹터 컬럼이 없습니다.")
    st.markdown("---")
    if 'total_score' in df.columns:
        df = df.sort_values(by='total_score', ascending=False).reset_index(drop=True)
    filtered_df = df[df['total_score'] >= min_score].copy()
    st.subheader(f"🏆 상위 랭킹 종목 ({len(filtered_df)}개)")
    with st.popover("ℹ️ 점수 구성 설명", use_container_width=True):
        st.markdown("""### 📊 점수 체계 (100점 만점)
**🔹 추세 (25점)**: MA20/50/200 정렬 + ADX 강도
**🔹 패턴 (30점)**: 재돌파(R)+15, 기준봉(B)+10, 스퀴즈(A)+8
**🔹 거래량 (20점)**: 돌파 시 거래량 확인 + 건조 신호
**🔹 수급 (15점)**: 외국인/기관 연속 매수
**🔹 리스크 (10점)**: 손절가 거리 기반 리스크
""")
    st.caption("👆 행 클릭 → 상세 분석 | ℹ️ 터치 → 점수 설명")
    display_cols = ['name', 'sector', 'close', 'total_score', 'setup', 'trend_score', 'pattern_score', 'volume_score', 'supply_score']
    display_cols = [c for c in display_cols if c in filtered_df.columns]
    display_df = filtered_df[display_cols].copy()
    display_df.insert(0, '순위', range(1, len(display_df)+1))
    rename_map = {'순위':'순위','name':'종목명','sector':'업종','close':'현재가','total_score':'총점','setup':'셋업','trend_score':'추세','pattern_score':'패턴','volume_score':'거래량','supply_score':'수급'}
    display_df = display_df.rename(columns=rename_map)
    event = st.dataframe(display_df, use_container_width=True, height=400, hide_index=True, on_select="rerun", selection_mode="single-row")
    selected_code = None
    if event.selection and len(event.selection.rows) > 0:
        selected_idx = event.selection.rows[0]
        selected_code = filtered_df.iloc[selected_idx]['code']
    if selected_code:
        row = df[df['code'] == selected_code].iloc[0]
        display_stock_report(row, sector_df)
elif mode == "🔍 실시간 종목 진단":
    st.subheader("🔍 실시간 종목 진단")
    stock_df = get_krx_codes()
    selected_name = st.selectbox("종목명 선택 (오타 자동완성)", stock_df['Name'])
    selected_code = stock_df[stock_df['Name'] == selected_name]['Code'].iloc[0]
    # RS inputs
    rs_3m = st.number_input("3개월 RS (0-100)", min_value=0, max_value=100, value=0, step=1)
    rs_6m = st.number_input("6개월 RS (0-100)", min_value=0, max_value=100, value=0, step=1)
    # fetch recent data (60 days)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365)
    df_stock = fdr.DataReader(selected_code, start_date, end_date)
    if df_stock is not None and len(df_stock) > 0:
        cfg = load_config()
        sig = calculate_signals(df_stock, cfg)
        # RS SCORE LOGIC FIX: Pass RS values to score_stock
        result = score_stock(df_stock, sig, cfg, rs_3m=rs_3m, rs_6m=rs_6m)
        
        if result:
            row = pd.Series(result)
            row['name'] = selected_name
            row['code'] = selected_code
            row['sector'] = ''
            
            # Explicitly add RS info to row for display if not present
            if 'rs_3m' not in row: row['rs_3m'] = rs_3m
            if 'rs_6m' not in row: row['rs_6m'] = rs_6m
            
            display_stock_report(row, sector_df=None, rs_3m=rs_3m, rs_6m=rs_6m)
        else:
            st.error("점수 계산에 실패했습니다.")
    else:
        st.error("데이터를 불러올 수 없습니다.")
elif mode == "🖼️ 차트 이미지 분석":
    st.subheader("🖼️ 차트 이미지 분석 (베타)")
    uploaded = st.file_uploader("차트 이미지 업로드", type=["png","jpg","jpeg"])
    if uploaded:
        st.image(uploaded, caption="업로드된 차트", use_column_width=True)
        
        # Analyze image
        with st.spinner("이미지 분석 중... (OCR 및 패턴 인식)"):
            # Pillow image conversion if needed, but analyze_chart_image stub handles raw BytesIO for now or we might need PIL
            from PIL import Image
            img = Image.open(uploaded)
            analysis_result = analyze_chart_image(img)
        
        # Display analysis results
        if analysis_result:
            with st.expander("🔍 이미지 분석 결과 (베타)", expanded=True):
                col_i1, col_i2 = st.columns(2)
                with col_i1:
                    st.markdown("**📝 텍스트 인식 (OCR)**")
                    for line in analysis_result.get("ocr_text", []):
                        st.caption(f"- {line}")
                with col_i2:
                    st.markdown("**🧩 감지된 패턴**")
                    for pat in analysis_result.get("patterns", []):
                        st.success(f"{pat['name']} (신뢰도: {pat['confidence']*100:.0f}%)")
        
        # After image, still need stock selection & RS
        stock_df = get_krx_codes()
        selected_name = st.selectbox("종목명 선택 (오타 자동완성)", stock_df['Name'], key='img_name')
        selected_code = stock_df[stock_df['Name'] == selected_name]['Code'].iloc[0]
        rs_3m = st.number_input("3개월 RS (0-100)", min_value=0, max_value=100, value=0, step=1, key='img_rs3')
        rs_6m = st.number_input("6개월 RS (0-100)", min_value=0, max_value=100, value=0, step=1, key='img_rs6')
        # Fetch investor data from cached scanner results (to fix 0 supply score)
        investor_data = {}
        df_scan, _, _ = load_data()
        if df_scan is not None:
             # Ensure code matching
             scan_row = df_scan[df_scan['code'].astype(str).str.zfill(6) == str(selected_code).zfill(6)]
             if not scan_row.empty:
                 scan_row = scan_row.iloc[0]
                 investor_data = {
                     'foreign_consecutive_buy': scan_row.get('foreign_consec_buy', 0),
                     'inst_net_buy_5d': scan_row.get('inst_net_5d', 0),
                     'foreign_net_buy_5d': scan_row.get('foreign_net_5d', 0),
                 }
        if df_stock is not None and len(df_stock) > 0:
            cfg = load_config()
            sig = calculate_signals(df_stock, cfg)
            # RS SCORE LOGIC FIX: Pass RS values to score_stock
            result = score_stock(df_stock, sig, cfg, rs_3m=rs_3m, rs_6m=rs_6m, investor_data=investor_data)
            
            if result:
                row = pd.Series(result)
                row['name'] = selected_name
                row['code'] = selected_code
                row['sector'] = ''
                
                # Explicitly add RS info to row for display if not present
                if 'rs_3m' not in row: row['rs_3m'] = rs_3m
                if 'rs_6m' not in row: row['rs_6m'] = rs_6m
                
                # Inject investor data for display (Recent Supply Status section)
                # Look for standardized keys from scanner_core first, then fallback to internal dict keys
                if 'foreign_consec_buy' not in row and 'foreign_consecutive_buy' in investor_data:
                    row['foreign_consec_buy'] = investor_data['foreign_consecutive_buy']
                if 'foreign_net_5d' not in row and 'foreign_net_buy_5d' in investor_data:
                    row['foreign_net_5d'] = investor_data['foreign_net_buy_5d']
                if 'inst_net_5d' not in row and 'inst_net_buy_5d' in investor_data:
                    row['inst_net_5d'] = investor_data['inst_net_buy_5d']
                
                display_stock_report(row, sector_df=None, rs_3m=rs_3m, rs_6m=rs_6m)
            else:
                st.error("점수 계산에 실패했습니다.")
        else:
            st.error("데이터를 불러올 수 없습니다.")
