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

def get_setup_explanations():
    """셋업 타입 전체 설명"""
    return {
        'A': "볼린저밴드(60,2) 상단 돌파 + 밴드폭 수축 구간 + 거래량 확인 + ADX 강세",
        'B': "거래량 급등(평균 5배) 후 고점 돌파 + 거래량 재확인",
        'C': "20일 이평선 돌파 + 거래량 증가 + ADX 상승 추세",
        '-': "기본 추세 및 유동성 기준만 충족 (특정 셋업 미해당)"
    }

def explain_setup(setup_type):
    """셋업 타입 설명"""
    return get_setup_explanations().get(setup_type, "알 수 없음")

def get_score_explanations():
    """점수 구성요소 설명"""
    return {
        'trend_score': {
            'name': '추세 점수',
            'description': '주가의 추세 강도를 측정합니다.',
            'components': [
                '현재가 > 20일 이평선: +10점',
                '현재가 > 60일 이평선: +10점',
                'ADX 40 이상 (강세): +15점',
                'ADX 30~39 (중강): +12점',
                'ADX 25~29 (중립): +8점',
                'ADX 20~24 (약세): +5점'
            ]
        },
        'trigger_score': {
            'name': '트리거 점수',
            'description': '매수 신호 발생 조건 충족도를 측정합니다.',
            'components': [
                'Setup A 발동: +25점',
                'Setup B 발동: +25점',
                'Setup C 발동: +20점',
                '셋업 미해당: +0점'
            ]
        },
        'liq_score': {
            'name': '유동성 점수',
            'description': '거래 활성도와 유동성을 측정합니다.',
            'components': [
                '일평균 거래대금 기준',
                '회전율 기준',
                '거래량 증가율 반영'
            ]
        }
    }

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
st.caption("👆 테이블에서 행을 클릭하면 상세 분석이 표시됩니다")

# 표시할 컬럼에 셋업 추가
display_cols = ['code', 'name', 'close', 'total_score', 'setup', 'trend_score', 'trigger_score', 'liq_score']
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
    'setup': '셋업',
    'trend_score': '추세',
    'trigger_score': '트리거',
    'liq_score': '유동성'
}
display_df = display_df.rename(columns=rename_map)

# 테이블 클릭으로 종목 선택 (Streamlit 1.35+)
event = st.dataframe(
    display_df,
    use_container_width=True,
    height=400,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row"
)

# 선택된 행 처리
selected_code = None
if event.selection and len(event.selection.rows) > 0:
    selected_idx = event.selection.rows[0]
    selected_code = filtered_df.iloc[selected_idx]['code']

# 종목 상세 분석
if selected_code:
    matching = df[df['code'] == selected_code]
    
    if len(matching) > 0:
        row = matching.iloc[0]
        
        st.markdown("---")
        st.subheader(f"📊 {row['name']} ({row['code']}) 상세 분석")
        
        # 메트릭 (4열 → 모바일에서 자동 조정)
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
        
        # 셋업 설명 (클릭/터치로 펼침)
        with st.expander(f"ℹ️ 셋업 설명 보기 (현재: Setup {setup_type})", expanded=False):
            st.markdown("**📋 셋업 종류 및 설명**")
            setup_explanations = get_setup_explanations()
            for stype, desc in setup_explanations.items():
                if stype == setup_type:
                    st.success(f"**▶ Setup {stype}** (현재): {desc}")
                else:
                    st.write(f"**Setup {stype}**: {desc}")
        
        st.markdown("---")
        
        # 점수 구성 상세 (세로 배치 - 모바일 최적화)
        st.markdown("#### 📈 점수 구성 상세")
        
        score_info = get_score_explanations()
        
        # 추세 점수
        trend_score = row.get('trend_score', 0)
        with st.expander(f"🔹 추세 점수: {trend_score:.0f}점", expanded=False):
            st.markdown(f"**{score_info['trend_score']['description']}**")
            st.markdown("**구성 요소:**")
            for comp in score_info['trend_score']['components']:
                st.write(f"• {comp}")
            st.markdown("---")
            st.markdown("**현재 종목 분석:**")
            if row.get('close', 0) > row.get('ma20', 0):
                st.write("✅ 현재가 > MA20 (+10)")
            if row.get('close', 0) > row.get('ma60', 0):
                st.write("✅ 현재가 > MA60 (+10)")
            adx = row.get('adx', 0)
            if adx >= 40:
                st.write(f"✅ ADX {adx:.0f} 강세 (+15)")
            elif adx >= 30:
                st.write(f"✅ ADX {adx:.0f} 중강 (+12)")
            elif adx >= 25:
                st.write(f"✅ ADX {adx:.0f} 중립 (+8)")
            elif adx >= 20:
                st.write(f"✅ ADX {adx:.0f} 약세 (+5)")
        
        # 트리거 점수
        trigger_score = row.get('trigger_score', 0)
        with st.expander(f"🔹 트리거 점수: {trigger_score:.0f}점", expanded=False):
            st.markdown(f"**{score_info['trigger_score']['description']}**")
            st.markdown("**구성 요소:**")
            for comp in score_info['trigger_score']['components']:
                st.write(f"• {comp}")
            st.markdown("---")
            st.markdown("**현재 종목 분석:**")
            st.write(f"✅ Setup {row.get('setup', '-')} 발동")
        
        # 유동성 점수
        liq_score = row.get('liq_score', 0)
        with st.expander(f"🔹 유동성 점수: {liq_score:.0f}점", expanded=False):
            st.markdown(f"**{score_info['liq_score']['description']}**")
            st.markdown("**구성 요소:**")
            for comp in score_info['liq_score']['components']:
                st.write(f"• {comp}")
            st.markdown("---")
            st.markdown("**의미:**")
            st.write("유동성이 높을수록 매매가 용이하고, 슬리피지(체결 가격 차이)가 적습니다.")
        
        # 기술적 지표 (차트 위에 배치 - 모바일 최적화)
        st.markdown("---")
        st.markdown("#### 📊 기술적 지표")
        
        # 지표를 가로로 컴팩트하게 표시
        indicator_cols = st.columns(3)
        with indicator_cols[0]:
            if 'ma20' in row and pd.notna(row['ma20']):
                st.write(f"**20일선**: {row['ma20']:,.0f}원")
            if 'ma60' in row and pd.notna(row['ma60']):
                st.write(f"**60일선**: {row['ma60']:,.0f}원")
        with indicator_cols[1]:
            if 'adx' in row and pd.notna(row['adx']):
                st.write(f"**ADX**: {row['adx']:.1f}")
            if 'bbw_pct' in row and pd.notna(row['bbw_pct']):
                st.write(f"**밴드폭%**: {row['bbw_pct']:.0f}%")
        with indicator_cols[2]:
            if 'stop' in row and pd.notna(row['stop']):
                st.write(f"**손절가**: {row['stop']:,.0f}원")
        
        # 차트
        st.markdown("---")
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
                
                # Subplot 생성 (가격 + 거래량) - 거래량 타이틀 제거
                fig = make_subplots(
                    rows=2, cols=1,
                    row_heights=[0.75, 0.25],
                    vertical_spacing=0.03,
                    subplot_titles=(f"{row['name']} ({row['code']})", "")
                )
                
                # 캔들스틱 색상: 상승=빨간색, 하락=파란색
                fig.add_trace(
                    go.Candlestick(
                        x=chart_df.index,
                        open=chart_df['Open'],
                        high=chart_df['High'],
                        low=chart_df['Low'],
                        close=chart_df['Close'],
                        name='가격',
                        increasing_line_color='red',
                        increasing_fillcolor='red',
                        decreasing_line_color='blue',
                        decreasing_fillcolor='blue'
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
                              line=dict(color='purple', width=1)),
                    row=1, col=1
                )
                
                # 볼린저밴드 상단
                fig.add_trace(
                    go.Scatter(x=chart_df.index, y=chart_df['BB_Upper'],
                              mode='lines', name='BB 상단',
                              line=dict(color='gray', width=1, dash='dot')),
                    row=1, col=1
                )
                
                # 손절가 라인
                if 'stop' in row and pd.notna(row['stop']):
                    fig.add_hline(
                        y=row['stop'], line_dash="dash", line_color="red",
                        annotation_text=f"손절: {row['stop']:,.0f}원",
                        row=1, col=1
                    )
                
                # 주요 이벤트 표시 (모바일에서 너무 많으면 복잡하므로 최근 30일만)
                for idx in chart_df.index[-30:]:
                    if chart_df.loc[idx, 'Vol_Spike'] and chart_df.loc[idx, 'Big_Candle']:
                        candle_type = "양봉" if chart_df.loc[idx, 'Close'] > chart_df.loc[idx, 'Open'] else "음봉"
                        fig.add_annotation(
                            x=idx, y=chart_df.loc[idx, 'High'],
                            text=f"장대{candle_type}",
                            showarrow=True, arrowhead=2,
                            arrowcolor="red" if candle_type == "양봉" else "blue",
                            font=dict(size=10),
                            row=1, col=1
                        )
                
                # 거래량 바 색상: 상승=빨간색, 하락=파란색
                colors = ['red' if chart_df.loc[i, 'Close'] >= chart_df.loc[i, 'Open'] 
                         else 'blue' for i in chart_df.index]
                
                fig.add_trace(
                    go.Bar(x=chart_df.index, y=chart_df['Volume'],
                          name='거래량', marker_color=colors, showlegend=False),
                    row=2, col=1
                )
                
                # 레이아웃 (모바일 최적화)
                fig.update_layout(
                    height=600,
                    xaxis_rangeslider_visible=False,
                    hovermode='x unified',
                    showlegend=True,
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.02,
                        xanchor="center",
                        x=0.5,
                        font=dict(size=11)
                    ),
                    margin=dict(l=10, r=10, t=50, b=10)
                )
                
                # x축 날짜만 표시 (거래량 밑에만)
                fig.update_xaxes(showticklabels=False, row=1, col=1)
                fig.update_xaxes(showticklabels=True, row=2, col=1)
                fig.update_yaxes(title_text="", row=1, col=1)
                fig.update_yaxes(title_text="", row=2, col=1)
                
                st.plotly_chart(fig, use_container_width=True)
                
            else:
                st.warning("차트 데이터를 불러올 수 없습니다.")
                
        except Exception as e:
            st.error(f"차트 생성 중 에러: {e}")

else:
    st.info("👆 테이블에서 종목 행을 클릭하면 상세 분석이 표시됩니다.")

st.markdown("---")
st.caption(f"업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {filename}")
