# -*- coding: utf-8 -*-
"""
기존 GitHub 코드 유지 + 뉴스만 제거 + KOSPI/KOSDAQ 상단 표시
"""
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

st.set_page_config(layout="wide", page_title="추세추종 스캐너")

# ========== Helper Functions ==========
@st.cache_data(ttl=300)
def load_config():
    if os.path.exists("config.yaml"):
        with open("config.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}

@st.cache_data(ttl=300)
def load_data():
    df = None
    filename = None
    merged_files = glob.glob("data/scanner_output*.csv")
    merged_files = [f for f in merged_files if "chunk" not in f]
    if merged_files:
        latest_file = max(merged_files, key=lambda x: os.path.basename(x))
        df = pd.read_csv(latest_file, dtype={'code': str})
        filename = os.path.basename(latest_file)
    
    sector_df = None
    if os.path.exists("data/sector_rankings.csv"):
        sector_df = pd.read_csv("data/sector_rankings.csv")
    return df, sector_df, filename

@st.cache_data
def get_krx_codes():
    try:
        df = fdr.StockListing("KRX")
        return df[['Code', 'Name']]
    except:
        return pd.DataFrame({'Code':[], 'Name':[]})

@st.cache_data(ttl=300)
def load_market_indices():
    start = datetime.now() - timedelta(days=60)
    try:
        kospi = fdr.DataReader("KS11", start)
        kosdaq = fdr.DataReader("KQ11", start)
        return kospi, kosdaq
    except:
        return pd.DataFrame(), pd.DataFrame()

def display_stock_report(row, sector_df=None, rs_3m=None, rs_6m=None):
    """기존 로직 유지 - 뉴스 섹션만 제거"""
    st.markdown("---")
    st.subheader(f"📊 {row.get('name', 'N/A')} ({row.get('code', '')}) 상세 분석")
    
    st.markdown(f"""
    <div style="display:grid; grid-template-columns:repeat(3,1fr); gap:10px;">
        <div style="background:#f0f2f6; padding:10px; border-radius:5px; text-align:center;">
            <div style="font-size:11px; color:#666;">현재가</div>
            <div style="font-size:14px; font-weight:bold;">{row['close']:,.0f}원</div>
        </div>
        <div style="background:#f0f2f6; padding:10px; border-radius:5px; text-align:center;">
            <div style="font-size:11px; color:#666;">총점</div>
            <div style="font-size:14px; font-weight:bold;">{row['total_score']:.0f}점</div>
        </div>
        <div style="background:#f0f2f6; padding:10px; border-radius:5px; text-align:center;">
            <div style="font-size:11px; color:#666;">셋업</div>
            <div style="font-size:14px; font-weight:bold;">{row.get('setup', '-')}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # 차트
    st.markdown("#### 📉 가격 차트")
    try:
        chart_df = fdr.DataReader(row['code'], datetime.now() - timedelta(days=180))
        if chart_df is not None:
            fig = go.Figure(data=[go.Candlestick(
                x=chart_df.index,
                open=chart_df['Open'],
                high=chart_df['High'],
                low=chart_df['Low'],
                close=chart_df['Close']
            )])
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)
    except:
        st.warning("차트를 불러올 수 없습니다.")

# ========== Main UI ==========
st.title("📊 추세추종 스캐너")

# KOSPI/KOSDAQ 상단 표시
kospi_df, kosdaq_df = load_market_indices()
col1, col2 = st.columns(2)

with col1:
    if not kospi_df.empty:
        close = kospi_df['Close'].iloc[-1]
        ma20 = kospi_df['Close'].rolling(20).mean().iloc[-1]
        status = "🟢 Above" if close > ma20 else "🔴 Below"
        st.metric("KOSPI", f"{int(close):,}", status)
    else:
        st.metric("KOSPI", "N/A")

with col2:
    if not kosdaq_df.empty:
        close = kosdaq_df['Close'].iloc[-1]
        ma20 = kosdaq_df['Close'].rolling(20).mean().iloc[-1]
        status = "🟢 Above" if close > ma20 else "🔴 Below"
        st.metric("KOSDAQ", f"{int(close):,}", status)
    else:
        st.metric("KOSDAQ", "N/A")

st.divider()

# 모드 선택
st.sidebar.title("메뉴")
mode = st.sidebar.radio("모드", ["🔍 실시간", "📊 스캐너", "🖼️ 이미지"])

if mode == "🔍 실시간":
    st.subheader("🔍 실시간 종목 진단")
    
    stock_df = get_krx_codes()
    if stock_df.empty:
        st.error("종목 리스트 로딩 실패")
        st.stop()
    
    selected_name = st.selectbox("종목명 검색", stock_df['Name'])
    selected_code = stock_df[stock_df['Name'] == selected_name]['Code'].iloc[0]
    
    rs_3m = st.number_input("3개월 RS", 0, 100, 0)
    rs_6m = st.number_input("6개월 RS", 0, 100, 0)
    
    if st.button("분석"):
        df = fdr.DataReader(selected_code, datetime.now() - timedelta(days=365))
        if df is not None:
            cfg = load_config()
            sig = calculate_signals(df, cfg)
            result = score_stock(df, sig, cfg, rs_3m=rs_3m, rs_6m=rs_6m)
            if result:
                row = pd.Series(result)
                row['name'] = selected_name
                row['code'] = selected_code
                display_stock_report(row, rs_3m=rs_3m, rs_6m=rs_6m)

elif mode == "📊 스캐너":
    st.subheader("📊 당일 시장 스캐너")
    
    df, sector_df, filename = load_data()
    if df is None:
        st.error("스캔 데이터 없음")
        st.stop()
    
    min_score = st.slider("최소 점수", 0, 100, 50)
    filtered = df[df['total_score'] >= min_score]
    
    st.dataframe(filtered, use_container_width=True)
    
    if st.button("상세 보기"):
        if len(filtered) > 0:
            display_stock_report(filtered.iloc[0], sector_df)

elif mode == "🖼️ 이미지":
    st.subheader("🖼️ 이미지 분석")
    uploaded = st.file_uploader("차트 업로드", type=['png','jpg'])
    if uploaded:
        st.image(uploaded)
        st.info("이미지 분석 기능 준비중")
