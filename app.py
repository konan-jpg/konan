# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
from scanner_core import score_stock
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(layout="wide", page_title="모멘텀 스캐너")

# -----------------------------
# 데이터 로딩
# -----------------------------
@st.cache_data(ttl=300)
def load_stock_data(n_stocks=50):
    """종목 데이터 로딩 (캐시 5분)"""
    end = datetime.now()
    start = end - timedelta(days=400)
    
    try:
        kospi = fdr.StockListing("KOSPI")
        codes_info = kospi.sort_values("Marcap", ascending=False).head(n_stocks)[["Code", "Name"]]
    except:
        return {}, {}
    
    stocks = {}
    stock_names = {}
    
    for _, row in codes_info.iterrows():
        code = row["Code"]
        name = row["Name"]
        try:
            df = fdr.DataReader(code, start, end)
            if df is not None and len(df) >= 80:
                stocks[code] = df
                stock_names[code] = name
        except:
            continue
    
    return stocks, stock_names

@st.cache_data(ttl=300)
def load_market_indices():
    """시장 지수 로딩"""
    start = datetime.now() - timedelta(days=400)
    try:
        kospi = fdr.DataReader("KS11", start)
        kosdaq = fdr.DataReader("KQ11", start)
        return kospi, kosdaq
    except:
        return pd.DataFrame(), pd.DataFrame()

# 초기 로딩
if "stocks" not in st.session_state:
    with st.spinner("📥 종목 데이터 로딩 중..."):
        stocks, names = load_stock_data(50)
        st.session_state["stocks"] = stocks
        st.session_state["stock_names"] = names

kospi_df, kosdaq_df = load_market_indices()

# -----------------------------
# Helper Functions
# -----------------------------
def market_status(index_df, name):
    """시장 지수 상태 표시"""
    if index_df.empty or len(index_df) < 20:
        st.metric(name, "N/A", "데이터 없음")
        return
    
    close = index_df["Close"].iloc[-1]
    ma20 = index_df["Close"].rolling(20).mean().iloc[-1]
    status = "🟢 Above 20MA" if close > ma20 else "🔴 Below 20MA"
    st.metric(name, f"{int(close):,}", status)

def plot_chart(code, df, result):
    """차트 생성 (뉴스 제거 버전)"""
    chart_df = df.tail(120)  # 최근 120일
    
    # 이동평균선
    chart_df = chart_df.copy()
    chart_df['MA20'] = chart_df['Close'].rolling(20).mean()
    chart_df['MA60'] = chart_df['Close'].rolling(60).mean()
    
    # 볼린저밴드
    mid = chart_df['Close'].rolling(60).mean()
    std = chart_df['Close'].rolling(60).std()
    chart_df['BB_Upper'] = mid + 2 * std
    chart_df['BB_Lower'] = mid - 2 * std
    
    # 차트 생성
    fig = make_subplots(
        rows=2, cols=1, 
        row_heights=[0.7, 0.3],
        vertical_spacing=0.03,
        shared_xaxes=True
    )
    
    # 캔들스틱
    fig.add_trace(
        go.Candlestick(
            x=chart_df.index,
            open=chart_df['Open'],
            high=chart_df['High'],
            low=chart_df['Low'],
            close=chart_df['Close'],
            name='가격',
            increasing_line_color='red',
            decreasing_line_color='blue'
        ),
        row=1, col=1
    )
    
    # 이동평균선
    fig.add_trace(
        go.Scatter(
            x=chart_df.index, 
            y=chart_df['MA20'],
            mode='lines',
            name='MA20',
            line=dict(color='orange', width=1.5)
        ),
        row=1, col=1
    )
    
    fig.add_trace(
        go.Scatter(
            x=chart_df.index,
            y=chart_df['MA60'],
            mode='lines',
            name='MA60',
            line=dict(color='purple', width=1.5)
        ),
        row=1, col=1
    )
    
    # 볼린저밴드 상단
    fig.add_trace(
        go.Scatter(
            x=chart_df.index,
            y=chart_df['BB_Upper'],
            mode='lines',
            name='BB Upper',
            line=dict(color='gray', width=1, dash='dot')
        ),
        row=1, col=1
    )
    
    # 거래량
    colors = ['red' if o <= c else 'blue' for o, c in zip(chart_df['Open'], chart_df['Close'])]
    fig.add_trace(
        go.Bar(
            x=chart_df.index,
            y=chart_df['Volume'],
            name='거래량',
            marker_color=colors,
            opacity=0.5
        ),
        row=2, col=1
    )
    
    # 레이아웃
    fig.update_layout(
        title=f"{st.session_state['stock_names'].get(code, code)} 차트",
        xaxis_rangeslider_visible=False,
        height=500,
        showlegend=True,
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0)
    )
    
    return fig

# -----------------------------
# Main UI
# -----------------------------
st.title("📊 모멘텀 스캐너 (30점 체계)")

# 시장 현황
col1, col2 = st.columns(2)
with col1:
    market_status(kospi_df, "KOSPI")
with col2:
    market_status(kosdaq_df, "KOSDAQ")

st.divider()

# 모드 선택
mode_map = {
    "📡 실시간": "realtime",
    "🖼 이미지": "image",
    "📊 당일 스캐너": "daily"
}

ui_mode = st.radio("모드 선택", list(mode_map.keys()), horizontal=True)
mode = mode_map[ui_mode]

mode_desc = {
    "realtime": "**출발 직전 선취매** - 거래량 과열 종목 제외",
    "image": "**차트 평가** - 실시간과 동일한 점수체계",
    "daily": "**돌파 확인 매매** - 거래량 돌파 종목 가점"
}
st.caption(mode_desc[mode])

st.divider()

# 최소 점수 필터
min_score = st.slider("최소 점수", 0, 30, 15, help="30점 만점 기준")

# 스캔 실행
stocks = st.session_state["stocks"]
stock_names = st.session_state["stock_names"]

if not stocks:
    st.error("❌ 로딩된 종목이 없습니다. 새로고침을 시도하세요.")
    st.stop()

results = []

with st.spinner(f"🔍 {len(stocks)}개 종목 스캔 중..."):
    for code, df in stocks.items():
        res = score_stock(df, mode=mode)
        if res and res["score"] >= min_score:
            results.append({
                "종목코드": code,
                "종목명": stock_names.get(code, code),
                "점수": res["score"],
                "현재가": int(res["close"]),
                "BB상단": int(res["bb_upper"]),
                "태그": res["tags"],
                "거래량배율": res["vol_ratio"],
                "_result": res,  # 차트용
                "_df": df  # 차트용
            })

if not results:
    st.warning(f"⚠️ {min_score}점 이상 종목이 없습니다. 최소 점수를 낮춰보세요.")
    st.stop()

# 결과 정렬
df_result = pd.DataFrame(results).sort_values("점수", ascending=False)
df_result.insert(0, "순위", range(1, len(df_result) + 1))

# 표시용 DataFrame (차트용 컬럼 제외)
display_cols = ["순위", "종목명", "점수", "현재가", "BB상단", "태그", "거래량배율"]
display_df = df_result[display_cols].copy()

# 포맷팅
display_df["현재가"] = display_df["현재가"].apply(lambda x: f"{x:,}원")
display_df["BB상단"] = display_df["BB상단"].apply(lambda x: f"{x:,}원")

st.subheader(f"🏆 상위 종목 ({len(df_result)}개)")

# 테이블 표시
event = st.dataframe(
    display_df,
    use_container_width=True,
    height=400,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row"
)

# 선택된 종목 상세
if event.selection and len(event.selection.rows) > 0:
    selected_idx = event.selection.rows[0]
    selected_row = df_result.iloc[selected_idx]
    
    st.divider()
    st.subheader(f"📊 {selected_row['종목명']} 상세 분석")
    
    # 점수 정보
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("총점", f"{selected_row['점수']:.0f}/30")
    with col2:
        st.metric("현재가", f"{selected_row['현재가']:,}원")
    with col3:
        st.metric("BB상단", f"{selected_row['BB상단']:,}원")
    with col4:
        st.metric("거래량배율", f"{selected_row['거래량배율']:.1f}x")
    
    # 태그
    st.info(f"**패턴 태그**: {selected_row['태그']}")
    
    # 차트
    fig = plot_chart(selected_row['종목코드'], selected_row['_df'], selected_row['_result'])
    st.plotly_chart(fig, use_container_width=True)

# 통계
st.divider()
st.subheader("📊 점수 분포")
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("평균 점수", f"{df_result['점수'].mean():.1f}점")
with col2:
    st.metric("최고 점수", f"{df_result['점수'].max():.0f}점")
with col3:
    st.metric("20점 이상", f"{len(df_result[df_result['점수'] >= 20])}개")

# 패턴 태그 통계
st.divider()
st.subheader("🏷️ 패턴 태그 통계")
tag_counts = {}
for tags in df_result["태그"]:
    if tags == "-":
        continue
    for tag in tags.split(" | "):
        tag_counts[tag] = tag_counts.get(tag, 0) + 1

if tag_counts:
    tag_df = pd.DataFrame(list(tag_counts.items()), columns=["패턴", "개수"])
    tag_df = tag_df.sort_values("개수", ascending=False)
    st.dataframe(tag_df, use_container_width=True, hide_index=True)
else:
    st.caption("패턴 태그가 없습니다.")

# 새로고침 버튼
st.divider()
if st.button("🔄 데이터 새로고침"):
    st.cache_data.clear()
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()
