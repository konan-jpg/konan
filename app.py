# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import glob
import os
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import FinanceDataReader as fdr
import yaml
from scanner_core import calculate_signals, score_stock

st.set_page_config(layout="wide", page_title="추세추종 스캐너 Pro")

# -----------------------------
# 1. 지수 및 종목 리스트 로딩 (안전장치)
# -----------------------------
@st.cache_data(ttl=600)
def get_market_status():
    """KOSPI, KOSDAQ 지수 20일선 판별 (네이버 차단 시 야후 우회)"""
    status = {}
    # (이름, 네이버코드, 야후코드)
    indices = [("KOSPI", "KS11", "^KS11"), ("KOSDAQ", "KQ11", "^KQ11")]
    
    for name, code_n, code_y in indices:
        df = None
        try:
            df = fdr.DataReader(code_n, datetime.now() - timedelta(days=60))
        except:
            pass
            
        if df is None or df.empty:
            try:
                # 네이버 차단 시 야후로 우회하여 데이터 확보
                df = fdr.DataReader(code_y, datetime.now() - timedelta(days=60), data_source='yahoo')
            except:
                pass
        
        if df is not None and len(df) > 20:
            last = df['Close'].iloc[-1]
            ma20 = df['Close'].rolling(20).mean().iloc[-1]
            prev = df['Close'].iloc[-2]
            status[name] = {
                "price": last,
                "change": (last - prev) / prev * 100,
                "is_bullish": last >= ma20 # 20일선 위/아래 판별
            }
        else:
            status[name] = None
    return status

@st.cache_data
def get_krx_codes():
    """종목 리스트 확보 (차단 대비 백업 로직 포함)"""
    try:
        df = fdr.StockListing("KRX")
        if not df.empty: return df[['Code', 'Name']]
    except:
        # 실시간 로딩 실패 시 백업용 CSV에서 읽어옴
        if os.path.exists("data/krx_backup.csv"):
            return pd.read_csv("data/krx_backup.csv", dtype={'Code': str})[['Code', 'Name']]
    return pd.DataFrame()

# -----------------------------
# 2. 상세 리포트 UI (기존 디자인 유지)
# -----------------------------
def display_stock_report(row):
    """선생님이 좋아하시던 상세 분석 리포트 화면"""
    st.divider()
    st.subheader(f"📊 {row['name']} ({row['code']}) 상세 분석")
    
    # 핵심 지표 카드
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("총점", f"{row['total_score']:.0f}점")
    c2.metric("현재가", f"{row['close']:,.0f}원")
    c3.metric("BB상단", f"{row['bb_upper']:,.0f}원")
    c4.metric("리스크", f"{row['risk_pct']:.1f}%")

    # 점수 구성
    st.markdown("#### 📈 점수 구성 (100점 만점)")
    sc1, sc2, sc3, sc4, sc5 = st.columns(5)
    sc1.metric("추세", f"{row['trend_score']:.0f}/25")
    sc2.metric("위치", f"{row['pattern_score']:.0f}/30")
    sc3.metric("거래량", f"{row['volume_score']:.0f}/20")
    sc4.metric("수급", f"{row['supply_score']:.0f}/15")
    sc5.metric("리스크", f"{row['risk_score']:.0f}/10")

    # 수급 정보 표시
    if 'foreign_consec_buy' in row:
        st.markdown("#### 💰 수급 현황")
        i1, i2, i3 = st.columns(3)
        i1.write(f"**외인 연속**: {int(row['foreign_consec_buy'])}일")
        i2.write(f"**외인 5일**: {row.get('foreign_net_5d', 0)/1e8:.1f}억")
        i3.write(f"**기관 5일**: {row.get('inst_net_5d', 0)/1e8:.1f}억")

    # 차트 (핵심 지표만 표시)
    df_chart = fdr.DataReader(row['code'], datetime.now() - timedelta(days=180))
    if df_chart is not None:
        fig = make_subplots(rows=2, cols=1, row_heights=[0.7, 0.3], shared_xaxes=True, vertical_spacing=0.05)
        fig.add_trace(go.Candlestick(x=df_chart.index, open=df_chart['Open'], high=df_chart['High'], low=df_chart['Low'], close=df_chart['Close'], name='Price'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['Close'].rolling(20).mean(), name='MA20', line=dict(color='orange')), row=1, col=1)
        
        # 거래량
        colors = ['red' if o <= c else 'blue' for o, c in zip(df_chart['Open'], df_chart['Close'])]
        fig.add_trace(go.Bar(x=df_chart.index, y=df_chart['Volume'], marker_color=colors, opacity=0.5), row=2, col=1)
        fig.update_layout(height=500, xaxis_rangeslider_visible=False, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

# -----------------------------
# 3. 메인 화면 구성
# -----------------------------
st.title("🚀 추세추종 스캐너 V2")

# 시장 지수 상태 표시 (최상단)
mkt_status = get_market_status()
if mkt_status:
    cols = st.columns(2)
    for idx, (name, data) in enumerate(mkt_status.items()):
        if data:
            icon = "🟢" if data['is_bullish'] else "🔴"
            cols[idx].metric(f"{icon} {name} (20일선)", f"{data['price']:,.2f}", f"{data['change']:+.2f}%")
else:
    st.error("지수 데이터 로딩 실패")

st.sidebar.header("메뉴")
mode = st.sidebar.radio("모드", ["📊 당일 시장 스캐너", "🔍 실시간 종목 진단"])

if mode == "📊 당일 시장 스캐너":
    st.subheader("📊 스캔 결과")
    # 최신 파일 로드 및 통합 로직
    files = glob.glob("data/scanner_output*.csv")
    if not files:
        st.warning("데이터가 없습니다.")
    else:
        latest = max(files, key=os.path.getctime)
        df_scan = pd.read_csv(latest, dtype={'code': str})
        
        # 테이블 표시
        min_score = st.slider("최소 점수", 0, 100, 70)
        filtered = df_scan[df_scan['total_score'] >= min_score].copy()
        
        # 순위 및 주요 컬럼 정리
        display_df = filtered[['name', 'code', 'close', 'total_score', 'tags']].copy()
        display_df.columns = ['종목명', '코드', '현재가', '총점', '태그']
        
        event = st.dataframe(display_df, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row")
        
        if event.selection and len(event.selection.rows) > 0:
            row_data = filtered.iloc[event.selection.rows[0]]
            display_stock_report(row_data)

elif mode == "🔍 실시간 종목 진단":
    st.subheader("🔍 실시간 진단")
    codes = get_krx_codes()
    if not codes.empty:
        # 검색창 복구
        name = st.selectbox("종목명 입력", codes['Name'])
        code = codes[codes['Name'] == name]['Code'].iloc[0]
        
        if st.button("지금 분석"):
            df_live = fdr.DataReader(code, datetime.now() - timedelta(days=400))
            cfg = yaml.safe_load(open("config.yaml", "r", encoding="utf-8"))
            sig = calculate_signals(df_live, cfg)
            res = score_stock(df_live, sig, cfg) # 실시간은 수급데이터 제외하고 계산 가능
            
            if res:
                res.update({'name': name, 'code': code})
                display_stock_report(pd.Series(res))
