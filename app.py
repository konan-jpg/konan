import glob, os
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import FinanceDataReader as fdr
from datetime import datetime, timedelta

st.set_page_config(page_title="추세추종 스캐너", layout="wide")
st.title("🔍 추세추종 스캐너 (일봉/장마감)")

@st.cache_data(ttl=600)
def list_result_files():
    files = sorted(glob.glob("data/scanner_output_*.csv"))
    files = [f for f in files if not f.endswith("scanner_output_latest.csv")]
    return files

@st.cache_data(ttl=600)
def load_results(path):
    return pd.read_csv(path)

@st.cache_data(ttl=3600)
def get_stock_data(code, days=180):
    end = datetime.now()
    start = end - timedelta(days=days)
    try:
        return fdr.DataReader(code, start, end)
    except Exception:
        return None

def plot_chart(df, name, stop=None):
    df = df.tail(180)

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7,0.3], vertical_spacing=0.03)
    
    fig.add_trace(go.Candlestick(
        x=df.index, 
        open=df["Open"], 
        high=df["High"], 
        low=df["Low"], 
        close=df["Close"], 
        name="Price"
    ), row=1, col=1)

    for p, color in [(20,"blue"), (50,"orange"), (200,"gray")]:
        ma = df["Close"].rolling(p).mean()
        fig.add_trace(go.Scatter(
            x=df.index, 
            y=ma, 
            name=f"MA{p}", 
            line=dict(color=color, width=1, dash="dot")
        ), row=1, col=1)

    if stop and stop > 0:
        fig.add_hline(
            y=float(stop), 
            line_dash="dash", 
            line_color="red", 
            annotation_text=f"STOP {float(stop):,.0f}",
            row=1, col=1
        )

    colors = ["red" if r.Open > r.Close else "green" for r in df.itertuples()]
    fig.add_trace(go.Bar(
        x=df.index, 
        y=df["Volume"], 
        marker_color=colors, 
        name="Vol"
    ), row=2, col=1)

    fig.update_layout(
        height=650, 
        xaxis_rangeslider_visible=False, 
        hovermode="x unified",
        title=f"{name} 차트"
    )
    return fig

files = list_result_files()
default_path = "data/scanner_output_latest.csv" if os.path.exists("data/scanner_output_latest.csv") else (files[-1] if files else None)

if default_path is None:
    st.warning("결과 파일이 없습니다. update_daily.py → merge_chunks.py 실행 후 생성됩니다.")
    st.stop()

options = []
if os.path.exists("data/scanner_output_latest.csv"):
    options.append(("최신", "data/scanner_output_latest.csv"))
for f in reversed(files):
    day = f.split("_")[-1].replace(".csv","")
    options.append((day, f))

label_to_path = {lbl: path for lbl, path in options}
selected_label = st.selectbox("📅 결과 날짜 선택", list(label_to_path.keys()), index=0)
results = load_results(label_to_path[selected_label])

st.caption(f"로딩 파일: {label_to_path[selected_label]} / 전체 rows={len(results)}")

top_n = st.slider("상위 몇 개만 볼까요?", min_value=10, max_value=50, value=20, step=5)
results_top = results.sort_values("total_score", ascending=False).head(top_n).reset_index(drop=True)

with st.expander("📊 랭킹 (점수 높은 순)", expanded=True):
    show = results_top[["name","total_score","setup","close","stop","risk_pct","adx","bbw_pct","keywords","news_count"]].copy()
    show.columns = ["종목","총점","셋업","현재가","손절가","리스크%","ADX","밴드%","키워드","뉴스수"]
    st.dataframe(show, use_container_width=True, hide_index=True)

st.subheader("📈 종목 상세 차트")
options2 = {f"{r['name']} (점수 {r['total_score']:.0f})": r["code"] for _, r in results_top.iterrows()}
sel = st.selectbox("종목 선택", list(options2.keys()))
code = options2[sel]
target = results_top[results_top["code"] == code].iloc[0]

st.info(f"💡 왜 뜨나(키워드): {target.get('keywords','없음')}")

df = get_stock_data(code)
if df is not None and len(df) > 0:
    st.plotly_chart(plot_chart(df, target["name"], stop=float(target.get("stop",0))), use_container_width=True)
else:
    st.warning("차트 데이터 로딩 실패")
