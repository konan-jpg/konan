import streamlit as st
import pandas as pd
import glob
import os
from datetime import datetime
import altair as alt

# --------------------------------------------------------------------------
# 1. 설정 및 데이터 로드 함수
# --------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="추세추종 스캐너")

@st.cache_data(ttl=300)
def load_data():
    """
    data/ 폴더 내의 최신 결과 파일을 로드합니다.
    만약 합쳐진 파일이 없으면 data/partial/ 내의 chunk 파일들을 읽어 합칩니다.
    """
    # 1순위: 이미 합쳐진 최종 파일 찾기 (날짜별 파일)
    merged_files = glob.glob("data/scanner_output*.csv")
    merged_files = [f for f in merged_files if 'chunk' not in f]  # chunk 파일 제외
    
    if merged_files:
        # 파일명에서 날짜 추출해서 가장 최신 것 선택
        # scanner_output_2026-01-17.csv 같은 형식 가정
        def extract_date(filename):
            try:
                # 파일명에서 날짜 부분 추출 (YYYY-MM-DD)
                parts = os.path.basename(filename).replace('.csv', '').split('_')
                if len(parts) >= 3:
                    return parts[-1]  # 마지막 부분이 날짜
                return '0000-00-00'
            except:
                return '0000-00-00'
        
        latest_file = max(merged_files, key=extract_date)
        df = pd.read_csv(latest_file)
        return df, os.path.basename(latest_file)

    # 2순위: data/partial/ 내의 chunk 파일 찾기 (fallback)
    chunk_files = glob.glob("data/partial/scanner_output*chunk*.csv")
    
    if chunk_files:
        df_list = []
        for f in sorted(chunk_files):  # 순서대로 읽기
            try:
                sub_df = pd.read_csv(f)
                df_list.append(sub_df)
            except Exception as e:
                st.warning(f"파일 읽기 실패: {f} - {e}")
                continue
        
        if df_list:
            final_df = pd.concat(df_list, ignore_index=True)
            # 중복 제거 (code 컬럼 기준)
            if 'code' in final_df.columns:
                final_df.drop_duplicates(subset=['code'], keep='first', inplace=True)
            
            st.info(f"📦 Partial 파일 {len(df_list)}개를 합쳐서 표시합니다 (총 {len(final_df)}개 종목)")
            return final_df, f"Merged from {len(df_list)} chunks"

    return None, None

# --------------------------------------------------------------------------
# 2. 메인 앱 로직
# --------------------------------------------------------------------------
st.title("🔍 추세추종 스캐너 (일봉/장마감)")

df, filename = load_data()

if df is None:
    st.error("❌ 결과 파일이 없습니다. GitHub Actions 실행 후 data/ 또는 data/partial/에 파일이 있어야 합니다.")
    st.info("💡 GitHub 레포지토리에서 워크플로가 정상 실행되었는지 확인해주세요.")
    st.stop()

st.success(f"✅ 데이터 로드 완료: {filename} (총 {len(df)}개 종목)")

# 점수 기준 내림차순 정렬
if 'total_score' in df.columns:
    df = df.sort_values(by='total_score', ascending=False).reset_index(drop=True)
else:
    st.error("total_score 컬럼이 없습니다. 데이터 형식을 확인해주세요.")
    st.stop()

# --------------------------------------------------------------------------
# 3. 필터링 및 테이블 표시
# --------------------------------------------------------------------------
min_score = st.sidebar.slider("최소 점수", 0, 100, 50)
filtered_df = df[df['total_score'] >= min_score].copy()

st.subheader(f"🏆 상위 랭킹 종목 ({len(filtered_df)}개)")

# 표시할 컬럼 선택 (존재하는 컬럼만)
display_cols = ['rank', 'code', 'name', 'close', 'total_score', 'trend_score', 'vol_score']
display_cols = [col for col in display_cols if col in filtered_df.columns]

st.dataframe(
    filtered_df[display_cols],
    use_container_width=True,
    height=400
)

# --------------------------------------------------------------------------
# 4. 차트 상세 보기 (종목 선택)
# --------------------------------------------------------------------------
if len(filtered_df) > 0:
    st.subheader("📈 종목 상세 분석")
    
    # 선택 박스: "이름 (코드)" 형식
    option_list = [f"{row['name']} ({row['code']})" for _, row in filtered_df.iterrows()]
    selected_option = st.selectbox("종목 선택", option_list)
    
    if selected_option:
        # "삼성전자 (005930)" -> "005930" 추출
        selected_code = selected_option.split('(')[-1].replace(')', '').strip()
        
        # 해당 종목 데이터 가져오기
        row = df[df['code'] == selected_code].iloc[0]
        
        col1, col2, col3 = st.columns(3)
        col1.metric("현재가", f"{row['close']:,.0f}원")
        col2.metric("총점", f"{row['total_score']:.0f}점")
        col3.metric("추세 점수", f"{row['trend_score']:.0f}점")
        
        # 추가 정보 표시
        st.markdown("### 📊 종목 상세 정보")
        info_cols = st.columns(2)
        
        with info_cols[0]:
            if 'vol_score' in row:
                st.write(f"**거래량 점수**: {row['vol_score']:.0f}점")
            if 'rank' in row:
                st.write(f"**순위**: {row['rank']}위")
        
        with info_cols[1]:
            if 'ma20' in df.columns and 'ma20' in row:
                st.write(f"**20일 이평선**: {row['ma20']:,.0f}원")
            if 'ma60' in df.columns and 'ma60' in row:
                st.write(f"**60일 이평선**: {row['ma60']:,.0f}원")
        
        st.info(f"💡 선택된 종목: **{row['name']}** - 상세 차트는 OHLCV 데이터가 필요합니다.")
else:
    st.warning("조건에 맞는 종목이 없습니다. 필터를 조정해주세요.")

# --------------------------------------------------------------------------
# 5. 푸터
# --------------------------------------------------------------------------
st.markdown("---")
st.caption(f"마지막 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 데이터: {filename}")
