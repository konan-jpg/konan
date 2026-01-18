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
    """데이터 로드"""
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

def explain_setup(setup_type):
    """셋업 타입 설명"""
    explanations = {
        'A': "볼린저밴드(60,2) 상단 돌파 + 밴드폭 수축 구간 + 거래량 확인 + ADX 강세",
        'B': "거래량 급등(평균 5배) 후 고점 돌파 + 거래량 재확인",
        '-': "기본 추세 및 유동성 기준만 충족"
    }
    return explanations.get(setup_type, "알 수 없음")

def explain_scores(row):
    """점수 구성 설명"""
    explanations = []
    
    # 추세 점수 설명
    trend_details = []
    if row.get('close', 0) > row.get('ma20', 0):
        trend_details.append("현재가 > MA20 (+10)")
    if row.get('close', 0) > row.get('ma60', 0):
        trend_details.append("현재가 > MA60 (+10)")
    
    adx = row.get('adx', 0)
    if adx >= 40:
        trend_details.append(f"ADX {adx:.0f} 강세 (+15)")
    elif adx >= 30:
        trend_details.append(f"ADX {adx:.0f} 중강 (+12)")
    elif adx >= 25:
        trend_details.append(f"ADX {adx:.0f} 중립 (+8)")
    elif adx >= 20:
        trend_details.append(f"ADX {adx:.0f} 약세 (+5)")
    
    explanations.append(("추세 점수", row.get('trend_score', 0), ", ".join(trend_details)))
    
    # 트리거 점수
    trigger_detail = f"Setup {row.get('setup', '-')} 발동"
    explanations.append(("트리거 점수", row.get('trigger_score', 0), trigger_detail))
    
    # 유동성 점수
    liq_detail = "거래대금 및 회전율 기준"
    explanations.append(("유동성 점수", row.get('liq_score', 0), liq_detail))
    
    return explanations

# 메인 앱
st.title("🔍 추세추종 스캐너 (일봉/장마감)")

# 상단 필터 (모바일 친화적)
with st.expander("🎛️ 필터 설정", expanded=False):
    min_score = st.slider("최소 점수", 0, 100, 50)

df, filename = load_data()

if df is None:
    st.error("❌ 결과 파일이 없습니다.")
    st.stop()

if 'code' in df.columns:
    df['code'] = df['code'].astype(str).str.zfill(6)

st.success(f"✅ 데이터 로드: {filename} (총 {len(df)}개)")

if 'total_score' in df.columns:
    df = df.sort_values(by='total_score', ascending=False).reset_index(drop=True)

filtered_df = df[df['total_score'] >= min_score].copy()

# 표 표시
st.subheader(f"🏆 상위 랭킹 종목 ({len(filtered_df)}개)")

# 표시할 컬럼에 유동성 점수 추가
display_cols = ['code', 'name', 'close', 'total_score', 'trend_score', 'trigger_score', 'liq_score']
display_cols = [col for col in display_cols if col in filtered_df.columns]

display_df = filtered_df[display_cols].copy()
display_df.insert(0, '순위', range(1, len(display_df) + 1))

# 컬럼명 한글화
rename_map = {
    '순위': '순위',
    'code': '종목코드',
    'name': '종목명',
    'close': '현재가',
    'total_score': '총점',
    'trend_score': '추세',
    'trigger_score': '트리거',
    'liq_score': '유동성'
}
display_df = display_df.rename(columns=rename_map)

# 세션 상태로 선택된 종목 관리
if 'selected_code' not in st.session_state:
    st.session_state.selected_code = None

# 표 표시 및 클릭 이벤트
event = st.dataframe(
    display_df,
    use_container_width=True,
    height=400,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row"
)

# 선택된 행 처리
if event.selection and len(event.selection.rows) > 0:
    selected_idx = event.selection.rows[0]
    st.session_state.selected_code = filtered_df.iloc[selected_idx]['code']

# 종목 상세 분석
if st.session_state.selected_code:
    matching = df[df['code'] == st.session_state.selected_code]
    
    if len(matching) > 0:
        row = matching.iloc[0]
        
        st.markdown("---")
        st.subheader(f"📊 {row['name']} ({row['code']}) 상세 분석")
        
        # 메트릭
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("현재가", f"{row['close']:,.0f}원")
        with col2:
            st.metric("총점", f"{row['total_score']:.0f}점")
        with col3:
            setup_type = row.get('setup', '-')
            st.metric("셋업", setup_type)
        with col4:
            if 'risk_pct' in row and pd.notna(row['risk_pct']):
                st.metric("리스크", f"{row['risk_pct']:.1f}%")
        
        # 셋업 설명
        st.info(f"**Setup {setup_type}**: {explain_setup(setup_type)}")
        
        # 점수 상세 설명
        col_left, col_right = st.columns(2)
        
        with col_left:
            st.markdown("#### 📈 점수 구성 상세")
            score_explanations = explain_scores(row)
            for name, score, detail in score_explanations:
                st.write(f"**{name}** ({score:.0f}점): {detail}")
        
        with col_right:
            st.markdown("#### 📊 기술적 지표")
            if 'ma20' in row and pd.notna(row['ma20']):
                st.write(f"**20일 이평선**: {row['ma20']:,.0f}원")
            if 'ma60' in row and pd.notna(row['ma60']):
                st.write(f"**60일 이평선**: {row['ma60']:,.0f}원")
            if 'adx' in row and pd.notna(row['adx']):
                st.write(f"**ADX**: {row['adx']:.1f} (추세 강도)")
            if 'bbw_pct' in row and pd.notna(row['bbw_pct']):
                st.write(f"**밴드폭 백분위**: {row['bbw_pct']:.0f}%")
            if 'stop' in row and pd.notna(row['stop']):
                st.write(f"**손절가**: {row['stop']:,.0f}원")
        
        # 차트
        st.markdown("#### 📉 가격 차트 (최근 6개월)")
        
        try:
            import FinanceDataReader as fdr
            from datetime import timedelta
            import numpy as np
            
            end_date = datetime.now()
            start_date = end_date - timedelta(days=180)
            
            chart_df = fdr.DataReader(row['code'], start_date, end_date)
            
            if chart_df is not None and len(chart_df) > 0:
                # 이동평균 및 볼린저밴드 계산
                chart_df['MA20'] = chart_df['Close'].rolling(20).mean()
                chart_df['MA60'] = chart_df['Close'].rolling(60).mean()
                
                # 볼린저밴드 (60, 2)
                bb_mid = chart_df['Close'].rolling(60).mean()
                bb_std = chart_df['Close'].rolling(60).std()
                chart_df['BB_Upper'] = bb_mid + (2 * bb_std)
                chart_df['BB_Lower'] = bb_mid - (2 * bb_std)
                
                # 거래량 급등 감지
                vol_ma = chart_df['Volume'].rolling(20).mean()
                chart_df['Vol_Spike'] = chart_df['Volume'] > vol_ma * 2
                
                # 장대양봉/음봉 감지
                body = abs(chart_df['Close'] - chart_df['Open'])
                avg_body = body.rolling(20).mean()
                chart_df['Big_Candle'] = body > avg_body * 1.5
                
                # Subplot 생성 (가격 + 거래량)
                fig = make_subplots(
                    rows=2, cols=1,
                    row_heights=[0.7, 0.3],
                    vertical_spacing=0.05,
                    subplot_titles=(f"{row['name']} ({row['code']})", "거래량")
                )
                
                # 캔들스틱
                fig.add_trace(
                    go.Candlestick(
                        x=chart_df.index,
                        open=chart_df['Open'],
                        high=chart_df['High'],
                        low=chart_df['Low'],
                        close=chart_df['Close'],
                        name='가격'
                    ),
                    row=1, col=1
                )
                
                # 이동평균선
                fig.add_trace(
                    go.Scatter(x=chart_df.index, y=chart_df['MA20'],
                              mode='lines', name='MA20',
                              line=dict(color='orange', width=1)),
                    row=1, col=1
                )
                fig.add_trace(
                    go.Scatter(x=chart_df.index, y=chart_df['MA60'],
                              mode='lines', name='MA60',
                              line=dict(color='blue', width=1)),
                    row=1, col=1
                )
                
                # 볼린저밴드 상단
                fig.add_trace(
                    go.Scatter(x=chart_df.index, y=chart_df['BB_Upper'],
                              mode='lines', name='BB 상단',
                              line=dict(color='purple', width=1, dash='dot')),
                    row=1, col=1
                )
                
                # 손절가 라인
                if 'stop' in row and pd.notna(row['stop']):
                    fig.add_hline(
                        y=row['stop'], line_dash="dash", line_color="red",
                        annotation_text=f"손절: {row['stop']:,.0f}원",
                        row=1, col=1
                    )
                
                # 주요 이벤트 표시
                for idx in chart_df.index[-60:]:  # 최근 60일만
                    if chart_df.loc[idx, 'Vol_Spike'] and chart_df.loc[idx, 'Big_Candle']:
                        candle_type = "양봉" if chart_df.loc[idx, 'Close'] > chart_df.loc[idx, 'Open'] else "음봉"
                        fig.add_annotation(
                            x=idx, y=chart_df.loc[idx, 'High'],
                            text=f"장대{candle_type}+거래량",
                            showarrow=True, arrowhead=2,
                            arrowcolor="red" if candle_type == "양봉" else "blue",
                            row=1, col=1
                        )
                
                # 거래량 바
                colors = ['red' if chart_df.loc[i, 'Close'] >= chart_df.loc[i, 'Open'] 
                         else 'blue' for i in chart_df.index]
                
                fig.add_trace(
                    go.Bar(x=chart_df.index, y=chart_df['Volume'],
                          name='거래량', marker_color=colors),
                    row=2, col=1
                )
                
                # 레이아웃
                fig.update_layout(
                    height=700,
                    xaxis_rangeslider_visible=False,
                    hovermode='x unified',
                    showlegend=True
                )
                
                fig.update_xaxes(title_text="날짜", row=2, col=1)
                fig.update_yaxes(title_text="가격 (원)", row=1, col=1)
                fig.update_yaxes(title_text="거래량", row=2, col=1)
                
                st.plotly_chart(fig, use_container_width=True)
                
            else:
                st.warning("차트 데이터를 불러올 수 없습니다.")
                
        except Exception as e:
            st.error(f"차트 생성 중 에러: {e}")

else:
    st.info("👆 위 표에서 종목을 클릭하면 상세 차트가 표시됩니다.")

st.markdown("---")
st.caption(f"업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {filename}")
