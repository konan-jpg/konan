import streamlit as st
import pandas as pd
import glob
import os
from datetime import datetime
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(layout="wide", page_title="추세추종 스캐너")

@st.cache_data(ttl=300)
def load_data():
    merged_files = glob.glob("data/scanner_output*.csv")
    merged_files = [f for f in merged_files if 'chunk' not in f]
    
    if merged_files:
        def extract_date(filename):
            try:
                parts = os.path.basename(filename).replace('.csv', '').split('_')
                if len(parts) >= 3:
                    return parts[-1]
                return '0000-00-00'
            except:
                return '0000-00-00'
        
        latest_file = max(merged_files, key=extract_date)
        df = pd.read_csv(latest_file, dtype={'code': str})
        return df, os.path.basename(latest_file)

    chunk_files = glob.glob("data/partial/scanner_output*chunk*.csv")
    
    if chunk_files:
        df_list = []
        for f in sorted(chunk_files):
            try:
                sub_df = pd.read_csv(f, dtype={'code': str})
                df_list.append(sub_df)
            except:
                continue
        
        if df_list:
            final_df = pd.concat(df_list, ignore_index=True)
            if 'code' in final_df.columns:
                final_df.drop_duplicates(subset=['code'], keep='first', inplace=True)
            return final_df, f"Merged from {len(df_list)} chunks"

    return None, None

def get_setup_explanations():
    return {
        'R': "🔥 재돌파 - 60일 내 BB(60,2) 돌파 후 눌림 → 재돌파 (가장 강력)",
        'B': "거래량 급등(5배) 후 고점 돌파 + 거래량 확인",
        'A': "BB(60,2) 상단 돌파 + 밴드폭 수축 + 거래량 + ADX",
        'C': "20일 이평선 돌파 + 거래량 + ADX",
        '-': "기본 조건만 충족"
    }

def get_score_explanations():
    return {
        'trend_score': {'name': '추세 (25)', 'desc': 'MA정렬+ADX'},
        'pattern_score': {'name': '패턴 (30)', 'desc': '재돌파+셋업'},
        'volume_score': {'name': '거래량 (20)', 'desc': '돌파거래량+건조'},
        'supply_score': {'name': '수급 (15)', 'desc': '외국인/기관'},
        'risk_score': {'name': '리스크 (10)', 'desc': '손절거리'}
    }

st.title("📊 추세추종 스캐너")

with st.expander("🎛️ 필터", expanded=False):
    min_score = st.slider("최소 점수", 0, 100, 50)

df, filename = load_data()

if df is None:
    st.error("❌ 결과 파일이 없습니다.")
    st.stop()

if 'code' in df.columns:
    df['code'] = df['code'].astype(str).str.zfill(6)

st.success(f"✅ {filename} ({len(df)}개)")

if 'total_score' in df.columns:
    df = df.sort_values(by='total_score', ascending=False).reset_index(drop=True)

filtered_df = df[df['total_score'] >= min_score].copy()

st.subheader(f"🏆 상위 종목 ({len(filtered_df)}개)")
st.caption("👆 행 클릭 → 상세 분석")

# 레거시 호환
if 'pattern_score' not in filtered_df.columns and 'trigger_score' in filtered_df.columns:
    filtered_df['pattern_score'] = filtered_df['trigger_score']
if 'volume_score' not in filtered_df.columns and 'liq_score' in filtered_df.columns:
    filtered_df['volume_score'] = filtered_df['liq_score']
if 'supply_score' not in filtered_df.columns:
    filtered_df['supply_score'] = 0

display_cols = ['code', 'name', 'close', 'total_score', 'setup', 'trend_score', 'pattern_score', 'volume_score', 'supply_score']
display_cols = [col for col in display_cols if col in filtered_df.columns]

display_df = filtered_df[display_cols].copy()
display_df.insert(0, '순위', range(1, len(display_df) + 1))

rename_map = {
    'code': '코드', 'name': '종목명', 'close': '현재가',
    'total_score': '총점', 'setup': '셋업', 'trend_score': '추세',
    'pattern_score': '패턴', 'volume_score': '거래량', 'supply_score': '수급'
}
display_df = display_df.rename(columns=rename_map)

event = st.dataframe(
    display_df, use_container_width=True, height=400,
    hide_index=True, on_select="rerun", selection_mode="single-row"
)

selected_code = None
if event.selection and len(event.selection.rows) > 0:
    selected_idx = event.selection.rows[0]
    selected_code = filtered_df.iloc[selected_idx]['code']

if selected_code:
    matching = df[df['code'] == selected_code]
    
    if len(matching) > 0:
        row = matching.iloc[0]
        
        st.markdown("---")
        st.subheader(f"📊 {row['name']} ({row['code']})")
        
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1: st.metric("현재가", f"{row['close']:,.0f}원")
        with col2: st.metric("총점", f"{row['total_score']:.0f}점")
        with col3: st.metric("셋업", row.get('setup', '-'))
        with col4:
            if 'risk_pct' in row and pd.notna(row['risk_pct']):
                st.metric("리스크", f"{row['risk_pct']:.1f}%")
        with col5:
            foreign = row.get('foreign_consec_buy', 0)
            if pd.notna(foreign) and foreign > 0:
                st.metric("외국인연속", f"{int(foreign)}일")
        
        setup_type = row.get('setup', '-')
        with st.expander(f"ℹ️ 셋업 설명 ({setup_type})", expanded=False):
            for s, desc in get_setup_explanations().items():
                if s == setup_type:
                    st.success(f"▶ {s}: {desc}")
                else:
                    st.write(f"{s}: {desc}")
        
        st.markdown("---")
        st.markdown("#### 📈 점수 구성")
        
        scores = {
            '추세': row.get('trend_score', 0),
            '패턴': row.get('pattern_score', row.get('trigger_score', 0)),
            '거래량': row.get('volume_score', row.get('liq_score', 0)),
            '수급': row.get('supply_score', 0),
            '리스크': row.get('risk_score', 10)
        }
        maxs = [25, 30, 20, 15, 10]
        
        cols = st.columns(5)
        for i, (label, score) in enumerate(scores.items()):
            with cols[i]:
                st.metric(label, f"{score:.0f}/{maxs[i]}")
        
        if 'foreign_net_5d' in row or 'inst_net_5d' in row:
            st.markdown("---")
            st.markdown("#### 💰 수급")
            c1, c2, c3 = st.columns(3)
            with c1:
                fc = row.get('foreign_consec_buy', 0)
                if pd.notna(fc): st.write(f"외국인 연속: {int(fc)}일")
            with c2:
                fn = row.get('foreign_net_5d', 0)
                if pd.notna(fn): st.write(f"외국인 5일: {fn/1e8:,.1f}억")
            with c3:
                ins = row.get('inst_net_5d', 0)
                if pd.notna(ins): st.write(f"기관 5일: {ins/1e8:,.1f}억")
        
        st.markdown("---")
        st.markdown("#### 📊 지표")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            if 'ma20' in row and pd.notna(row['ma20']):
                st.write(f"20일선: {row['ma20']:,.0f}")
        with c2:
            if 'ma60' in row and pd.notna(row['ma60']):
                st.write(f"60일선: {row['ma60']:,.0f}")
        with c3:
            if 'adx' in row and pd.notna(row['adx']):
                st.write(f"ADX: {row['adx']:.1f}")
        with c4:
            if 'stop' in row and pd.notna(row['stop']):
                st.write(f"손절: {row['stop']:,.0f}")
        
        st.markdown("---")
        st.markdown("#### 📉 차트")
        
        try:
            import FinanceDataReader as fdr
            from datetime import timedelta
            
            end_date = datetime.now()
            start_date = end_date - timedelta(days=180)
            
            chart_df = fdr.DataReader(row['code'], start_date, end_date)
            
            if chart_df is not None and len(chart_df) > 0:
                chart_df['MA20'] = chart_df['Close'].rolling(20).mean()
                chart_df['MA60'] = chart_df['Close'].rolling(60).mean()
                
                bb_mid = chart_df['Close'].rolling(60).mean()
                bb_std = chart_df['Close'].rolling(60).std()
                chart_df['BB_Upper'] = bb_mid + (2 * bb_std)
                
                fig = make_subplots(rows=2, cols=1, row_heights=[0.75, 0.25], vertical_spacing=0.03)
                
                fig.add_trace(go.Candlestick(
                    x=chart_df.index, open=chart_df['Open'], high=chart_df['High'],
                    low=chart_df['Low'], close=chart_df['Close'], name='가격',
                    increasing_line_color='red', increasing_fillcolor='red',
                    decreasing_line_color='blue', decreasing_fillcolor='blue'
                ), row=1, col=1)
                
                fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['MA20'],
                    mode='lines', name='MA20', line=dict(color='orange', width=1.5)), row=1, col=1)
                fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['MA60'],
                    mode='lines', name='MA60', line=dict(color='purple', width=1.5)), row=1, col=1)
                fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['BB_Upper'],
                    mode='lines', name='BB상단', line=dict(color='gray', width=1, dash='dot')), row=1, col=1)
                
                if 'stop' in row and pd.notna(row['stop']):
                    fig.add_hline(y=row['stop'], line_dash="dash", line_color="red", row=1, col=1)
                
                colors = ['red' if chart_df.loc[i, 'Close'] >= chart_df.loc[i, 'Open'] else 'blue' for i in chart_df.index]
                fig.add_trace(go.Bar(x=chart_df.index, y=chart_df['Volume'],
                    marker_color=colors, showlegend=False), row=2, col=1)
                
                fig.update_layout(
                    height=500, xaxis_rangeslider_visible=False, hovermode='x unified',
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
                    margin=dict(l=5, r=5, t=40, b=5)
                )
                fig.update_xaxes(showticklabels=False, row=1, col=1)
                fig.update_yaxes(title_text="", row=1, col=1)
                fig.update_yaxes(title_text="", row=2, col=1)
                
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("차트 데이터 없음")
        except Exception as e:
            st.error(f"차트 에러: {e}")

else:
    st.info("👆 테이블에서 종목을 클릭하세요")

st.markdown("---")
st.caption(f"{datetime.now().strftime('%Y-%m-%d %H:%M')} | {filename}")
