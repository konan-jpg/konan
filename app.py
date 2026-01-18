import streamlit as st
import pandas as pd
import glob
import os
from datetime import datetime
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from news_analyzer import search_naver_news

st.set_page_config(layout="wide", page_title="추세추종 스캐너")

@st.cache_data(ttl=300)
def load_data():
    """데이터 로드"""
    df = None
    filename = None
    
    # 1. 병합된 전체 파일 먼저 확인
    merged_files = glob.glob("data/scanner_output*.csv")
    merged_files = [f for f in merged_files if 'chunk' not in f]
    
    if merged_files:
        def extract_date(fn):
            try:
                parts = os.path.basename(fn).replace('.csv', '').split('_')
                if len(parts) >= 3:
                    return parts[-1]
                return '0000-00-00'
            except:
                return '0000-00-00'
        
        latest_file = max(merged_files, key=extract_date)
        df = pd.read_csv(latest_file, dtype={'code': str})
        filename = os.path.basename(latest_file)
    
    else:
        # 2. 병합 파일이 없으면 청크 파일 합치기
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
                df = pd.concat(df_list, ignore_index=True)
                if 'code' in df.columns:
                    df.drop_duplicates(subset=['code'], keep='first', inplace=True)
                filename = f"Merged from {len(df_list)} chunks"
    
    # 3. 섹터 랭킹 데이터 로드
    sector_df = None
    if os.path.exists("data/sector_rankings.csv"):
        sector_df = pd.read_csv("data/sector_rankings.csv")
        
    return df, sector_df, filename

def get_setup_explanations():
    """셋업 타입 설명"""
    return {
        'R': "🔥 재돌파 패턴 - 60일 내 BB(60,2) 돌파 후 눌림 → 재돌파 (가장 강력)",
        'B': "거래량 급등(평균 5배) 후 고점 돌파 + 거래량 재확인",
        'A': "볼린저밴드(60,2) 상단 돌파 + 밴드폭 수축 + 거래량 확인 + ADX 강세",
        'C': "20일 이평선 돌파 + 거래량 증가 + ADX 상승 추세",
        '-': "기본 추세 및 유동성 기준만 충족"
    }

def get_score_explanations():
    """점수 구성요소 설명 (새 체계)"""
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
                '재돌파 패턴 (Setup R): +15점',
                '기준봉 돌파 (Setup B): +10점',
                '스퀴즈 돌파 (Setup A): +8점',
                'MA20 돌파 (Setup C): +5점',
                '밴드폭 수축 상태: +5점'
            ]
        },
        'volume_score': {
            'name': '거래량 점수 (20점)',
            'description': '거래량 급등 및 건조(매집) 신호',
            'components': [
                '돌파 시 거래량 확인: +8점',
                '거래량 건조 (매집): +5~7점',
                '하락 시 거래량 감소: +5점'
            ]
        },
        'supply_score': {
            'name': '수급 점수 (15점)',
            'description': '외국인/기관 투자자 동향',
            'components': [
                '외국인 연속 매수 5일+: +8점',
                '외국인 연속 매수 3일+: +5점',
                '기관 5일 순매수: +4점',
                '외국인 5일 순매수: +3점'
            ]
        },
        'risk_score': {
            'name': '리스크 점수 (10점)',
            'description': '손절가 거리 기반 리스크 평가',
            'components': [
                '리스크 5% 이하: 10점 (만점)',
                '리스크 5~8%: -1점',
                '리스크 8~10%: -3점',
                '리스크 10%+: -5점'
            ]
        }
    }

# 메인 앱
st.title("📊 추세추종 스캐너")

# 상단 필터
with st.expander("🎛️ 필터 설정", expanded=False):
    min_score = st.slider("최소 점수", 0, 100, 50)

df, sector_df, filename = load_data()

if df is None:
    st.error("❌ 결과 파일이 없습니다.")
    st.stop()

if 'code' in df.columns:
    df['code'] = df['code'].astype(str).str.zfill(6)

st.success(f"✅ 데이터 로드: {filename} (총 {len(df)}개)")

# === 주도 섹터 검증 패널 ===
st.markdown("### 🧭 시장 주도 섹터 분석")

col_a, col_b = st.columns(2)

with col_a:
    st.info("📊 시장 주도 섹터 (Top-Down)")
    if sector_df is not None and len(sector_df) > 0:
        top_sectors = sector_df.head(5)[['Sector', 'AvgReturn_3M', 'StockCount']]
        st.dataframe(
            top_sectors.style.format({'AvgReturn_3M': '{:.1f}%'}),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.caption("⚠️ 섹터 랭킹 데이터가 없습니다. GitHub Actions 실행 후 생성됩니다.")
    
with col_b:
    st.success("🎯 스캐너 포착 섹터")
    # 스캐너 결과에서 섹터 빈도 계산 ('기타' 제외)
    if 'sector' in df.columns:
        valid_sectors = df[df['sector'] != '기타']['sector']
        if len(valid_sectors) > 0:
            scanner_sectors = valid_sectors.value_counts().head(5).reset_index()
            scanner_sectors.columns = ['Sector', 'Count']
            
            # 시장 주도 섹터와 일치 여부 확인
            if sector_df is not None:
                market_leaders = sector_df.head(5)['Sector'].tolist()
                scanner_sectors['일치'] = scanner_sectors['Sector'].apply(
                    lambda x: "✅" if x in market_leaders else "-"
                )
            
            st.dataframe(scanner_sectors, use_container_width=True, hide_index=True)
        else:
            st.caption("⚠️ 섹터 정보가 없습니다. 다음 스캔 후 표시됩니다.")
    else:
        st.caption("⚠️ 섹터 컬럼이 없습니다.")

st.markdown("---")


if 'total_score' in df.columns:
    df = df.sort_values(by='total_score', ascending=False).reset_index(drop=True)

filtered_df = df[df['total_score'] >= min_score].copy()

# 표 표시
st.subheader(f"🏆 상위 랭킹 종목 ({len(filtered_df)}개)")

# 점수 설명 도움말 (모바일 친화적 - 터치로 열기)
with st.popover("ℹ️ 점수 구성 설명", use_container_width=True):
    st.markdown("""### 📊 점수 체계 (100점 만점)
**🔹 추세 (25점)**: MA20/50/200 정렬 + ADX 강도

**🔹 패턴 (30점)**: 재돌파(R)+15, 기준봉(B)+10, 스퀴즈(A)+8

**🔹 거래량 (20점)**: 돌파 시 거래량 확인 + 거래량 건조(매집)

**🔹 수급 (15점)**: 외국인/기관 연속매수 및 순매수

**🔹 리스크 (10점)**: 손절가 거리 (가까울수록 높은 점수)
""")

st.caption("👆 행 클릭 → 상세 분석 | ℹ️ 터치 → 점수 설명")

# 표시할 컬럼 (새 점수 체계) - 코드 제외
display_cols = ['name', 'sector', 'close', 'total_score', 'setup', 'trend_score', 'pattern_score', 'volume_score', 'supply_score']
display_cols = [col for col in display_cols if col in filtered_df.columns]

# 레거시 컬럼 대체
if 'sector' not in filtered_df.columns:
    filtered_df['sector'] = '-'
if 'pattern_score' not in filtered_df.columns and 'trigger_score' in filtered_df.columns:
    filtered_df['pattern_score'] = filtered_df['trigger_score']
if 'volume_score' not in filtered_df.columns and 'liq_score' in filtered_df.columns:
    filtered_df['volume_score'] = filtered_df['liq_score']
if 'supply_score' not in filtered_df.columns:
    filtered_df['supply_score'] = 0

display_cols = [col for col in display_cols if col in filtered_df.columns]

display_df = filtered_df[display_cols].copy()
display_df.insert(0, '순위', range(1, len(display_df) + 1))

# 컬럼명 한글화 (코드 제외)
rename_map = {
    '순위': '순위',
    'name': '종목명',
    'sector': '업종',
    'close': '현재가',
    'total_score': '총점',
    'setup': '셋업',
    'trend_score': '추세',
    'pattern_score': '패턴',
    'volume_score': '거래량',
    'supply_score': '수급'
}
display_df = display_df.rename(columns=rename_map)

# 테이블 클릭으로 종목 선택
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
        
        # 주도섹터 여부 확인
        stock_sector = row.get('sector', '기타')
        is_leader_sector = False
        if sector_df is not None:
            market_leaders = sector_df.head(5)['Sector'].tolist()
            is_leader_sector = stock_sector in market_leaders
        
        # 업종 배지 표시
        if is_leader_sector:
            st.success(f"🏆 **주도 섹터**: {stock_sector} ← 시장 상위 5개 업종에 속함!")
        else:
            st.info(f"📌 **업종**: {stock_sector}")
        
        # 모바일 친화적 정보 요약 (CSS Grid 사용)
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
        @media (max-width: 600px) {{
            .info-grid {{ grid-template-columns: repeat(3, 1fr); }}
            .info-value {{ font-size: 13px; }}
        }}
        </style>
        
        <div class="info-grid">
            <div class="info-box">
                <div class="info-label">현재가</div>
                <div class="info-value">{row['close']:,.0f}원</div>
            </div>
            <div class="info-box">
                <div class="info-label">총점</div>
                <div class="info-value">{row['total_score']:.0f}점</div>
            </div>
            <div class="info-box">
                <div class="info-label">셋업</div>
                <div class="info-value">{row.get('setup', '-')}</div>
            </div>
            <div class="info-box">
                <div class="info-label">리스크</div>
                <div class="info-value">{risk_pct:.1f}%</div>
            </div>
            <div class="info-box">
                <div class="info-label">외인연속</div>
                <div class="info-value">{int(foreign)}일</div>
            </div>
            <div class="info-box">
                <div class="info-label">기관5일</div>
                <div class="info-value">{inst_net/1e8:,.0f}억</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # 셋업 설명
        setup_type = row.get('setup', '-')
        with st.expander(f"ℹ️ 셋업 설명 (현재: Setup {setup_type})", expanded=False):
            setup_explanations = get_setup_explanations()
            for stype, desc in setup_explanations.items():
                if stype == setup_type:
                    st.success(f"**▶ Setup {stype}** (현재): {desc}")
                else:
                    st.write(f"**Setup {stype}**: {desc}")
        
        st.markdown("---")
        
        # 점수 구성 상세 (5개 카테고리)
        st.markdown("#### 📈 점수 구성 상세 (100점 만점)")
        
        score_info = get_score_explanations()
        
        # 점수 바 차트
        score_data = {
            '추세': row.get('trend_score', 0),
            '패턴': row.get('pattern_score', row.get('trigger_score', 0)),
            '거래량': row.get('volume_score', row.get('liq_score', 0)),
            '수급': row.get('supply_score', 0),
            '리스크': row.get('risk_score', 10)
        }
        
        score_cols = st.columns(5)
        max_scores = [25, 30, 20, 15, 10]
        colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7']
        
        for i, (label, score) in enumerate(score_data.items()):
            with score_cols[i]:
                st.metric(label, f"{score:.0f}/{max_scores[i]}")
        
        # 상세 설명 (접기)
        for key, info in score_info.items():
            score_val = score_data.get(info['name'].split('(')[0].strip().replace('점수', '').strip(), 0)
            with st.expander(f"🔹 {info['name']}", expanded=False):
                st.markdown(f"**{info['description']}**")
                for comp in info['components']:
                    st.write(f"• {comp}")
        
        # 수급 정보 (있으면 표시)
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
        
        # === 매수 전략 추천 ===
        st.markdown("---")
        st.markdown("#### 🎯 매수 전략 추천")
        
        try:
            current_price = row['close']
            ma20 = row.get('ma20', current_price)
            ma60 = row.get('ma60', current_price)
            stop_price = row.get('stop', current_price * 0.92)
            bb_upper = row.get('bb_upper', current_price * 1.05)  # 없으면 추정
            
            # 시나리오별 가격 계산
            pullback_price = ma20  # 눌림목 기준: 20일선
            breakout_price = bb_upper if bb_upper > current_price else current_price * 1.02 # 돌파 기준: 볼밴 상단
            
            # 오닐/미너비니 전략 가격 계산 (차트 데이터 필요)
            oneil_msg = "패턴 형성 대기중"
            oneil_price = 0
            oneil_risk = 0
            oneil_setup_name = "-"
            
            # 차트 데이터가 있으면 패턴 분석
            try:
                import FinanceDataReader as fdr
                from datetime import timedelta
                # 최신 데이터 가져와서 분석
                end_date_s = datetime.now()
                start_date_s = end_date_s - timedelta(days=60)
                sub_df = fdr.DataReader(row['code'], start_date_s, end_date_s)
                
                if sub_df is not None and len(sub_df) >= 2:
                    today = sub_df.iloc[-1]
                    prev = sub_df.iloc[-2]
                    
                    # 1. Inside Day (변동성 축소) -> 오늘 고가 돌파 시 매수
                    if today['High'] < prev['High'] and today['Low'] > prev['Low']:
                        oneil_price = today['High']
                        oneil_setup_name = "Inside Day 돌파"
                        oneil_msg = f"오늘 고가({int(today['High']):,}원) 돌파 시 진입"
                    
                    # 2. Oops Reversal (속임수 반전) -> 상승 추세일 때만 유효
                    elif today['Open'] < prev['Low'] and today['Close'] > prev['Low'] and today['Close'] > ma20:
                        oneil_price = today['Close']
                        oneil_setup_name = "Oops Reversal"
                        oneil_msg = "속임수 반전 확인. 종가/익일 시가 진입"
                        
                    # 3. Pocket Pivot (거래량 매집) -> 종가 진입
                    else:
                        vol_ma = sub_df['Volume'].rolling(20).mean().iloc[-1]
                        if today['Volume'] > vol_ma * 2.5 and today['Close'] > prev['Close'] * 1.04:
                            oneil_price = today['Close']
                            oneil_setup_name = "Pocket Pivot"
                            oneil_msg = "거래량 급등(매집). 눌림 시 매수 유효"
                        
                    # 오닐 전략 리스크
                    if oneil_price > 0:
                        oneil_risk = (oneil_price - stop_price) / oneil_price * 100
            except:
                pass
            
            # 리스크 계산
            risk_pullback = (pullback_price - stop_price) / pullback_price * 100
            risk_breakout = (breakout_price - stop_price) / breakout_price * 100
            
            # 현재 상태 진단
            price_vs_ma20 = (current_price - ma20) / ma20 * 100 if ma20 > 0 else 0
            
            status_msg = ""
            if price_vs_ma20 <= 3:
                status_msg = "🟢 현재 **눌림목 구간**입니다. 분할 매수 유효."
            elif price_vs_ma20 > 8:
                status_msg = "🟡 현재 **고점 구간**입니다. 돌파 확인 후 진입 추천."
            else:
                status_msg = "🟠 **중립 구간**입니다. 방향성 관찰 필요."

            # UI 표시 (3-Track 전략)
            st.info(status_msg)
            
            col_sc1, col_sc2, col_sc3 = st.columns(3)
            
            with col_sc1:
                st.markdown(f"""
                <div style="background-color:rgba(0,255,0,0.1); padding:10px; border-radius:10px; height:100%;">
                    <strong>📉 기본 눌림목</strong><br>
                    목표: <strong>{pullback_price:,.0f}원</strong><br>
                    <span style="font-size:0.8em; color:gray;">(MA20 지지)</span><br>
                    <span style="font-size:0.8em;">리스크: {risk_pullback:.1f}%</span>
                </div>
                """, unsafe_allow_html=True)
                
            with col_sc2:
                st.markdown(f"""
                <div style="background-color:rgba(255,0,0,0.1); padding:10px; border-radius:10px; height:100%;">
                    <strong>🚀 기본 돌파</strong><br>
                    목표: <strong>{breakout_price:,.0f}원</strong><br>
                    <span style="font-size:0.8em; color:gray;">(BB 상단)</span><br>
                    <span style="font-size:0.8em;">리스크: {risk_breakout:.1f}%</span>
                </div>
                """, unsafe_allow_html=True)
                
            with col_sc3:
                # 오닐 전략 스타일 (활성화 여부에 따라 다르게)
                bg_color = "rgba(0,0,255,0.1)" if oneil_price > 0 else "rgba(128,128,128,0.1)"
                price_disp = f"{oneil_price:,.0f}원" if oneil_price > 0 else "-"
                risk_disp = f"리스크: {oneil_risk:.1f}%" if oneil_price > 0 else oneil_msg
                
                st.markdown(f"""
                <div style="background-color:{bg_color}; padding:10px; border-radius:10px; height:100%;">
                    <strong>💎 오닐/미너비니</strong><br>
                    목표: <strong>{price_disp}</strong><br>
                    <span style="font-size:0.8em; color:gray;">({oneil_setup_name})</span><br>
                    <span style="font-size:0.8em;">{risk_disp}</span>
                </div>
                """, unsafe_allow_html=True)

            st.caption(f"💡 손절가: {stop_price:,.0f}원 (필수 준수)")
        except Exception as e:
            st.warning(f"매수 전략 계산 오류: {e}")
        
        # 기술적 지표
        st.markdown("---")
        st.markdown("#### 📊 기술적 지표")
        
        indicator_cols = st.columns(4)
        with indicator_cols[0]:
            if 'ma20' in row and pd.notna(row['ma20']):
                st.write(f"**20일선**: {row['ma20']:,.0f}원")
        with indicator_cols[1]:
            if 'ma60' in row and pd.notna(row['ma60']):
                st.write(f"**60일선**: {row['ma60']:,.0f}원")
        with indicator_cols[2]:
            if 'adx' in row and pd.notna(row['adx']):
                st.write(f"**ADX**: {row['adx']:.1f}")
        with indicator_cols[3]:
            if 'stop' in row and pd.notna(row['stop']):
                st.write(f"**손절가**: {row['stop']:,.0f}원")
        
        # === 최신 뉴스 ===
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
                        pub_date = news.get('pubDate', '')[:16]  # 날짜만
                        st.markdown(f"- [{title}]({link}) ({pub_date})")
                else:
                    st.caption("관련 뉴스가 없습니다.")
            else:
                st.caption("네이버 API 키가 설정되지 않았습니다. (Streamlit Cloud 환경변수 설정 필요)")
        except Exception as e:
            st.caption(f"뉴스 로드 오류: {e}")
        
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
                # 이동평균 및 볼린저밴드
                chart_df['MA20'] = chart_df['Close'].rolling(20).mean()
                chart_df['MA60'] = chart_df['Close'].rolling(60).mean()
                
                bb_mid = chart_df['Close'].rolling(60).mean()
                bb_std = chart_df['Close'].rolling(60).std()
                chart_df['BB_Upper'] = bb_mid + (2 * bb_std)
                chart_df['BB_Lower'] = bb_mid - (2 * bb_std)
                
                # 거래량 급등 감지
                vol_ma = chart_df['Volume'].rolling(20).mean()
                chart_df['Vol_Spike'] = chart_df['Volume'] > vol_ma * 2
                
                # 차트 생성
                fig = make_subplots(
                    rows=2, cols=1,
                    row_heights=[0.75, 0.25],
                    vertical_spacing=0.03,
                    subplot_titles=("", "")
                )
                
                # 현재가 가져오기
                current_price = chart_df['Close'].iloc[-1]
                
                # 캔들스틱 (현재가 표시)
                fig.add_trace(
                    go.Candlestick(
                        x=chart_df.index,
                        open=chart_df['Open'],
                        high=chart_df['High'],
                        low=chart_df['Low'],
                        close=chart_df['Close'],
                        name=f'가격 {current_price:,.0f}',
                        increasing_line_color='red',
                        increasing_fillcolor='red',
                        decreasing_line_color='blue',
                        decreasing_fillcolor='blue'
                    ),
                    row=1, col=1
                )
                
                # 이동평균선 (마지막 값 표시)
                ma20_val = chart_df['MA20'].iloc[-1]
                fig.add_trace(
                    go.Scatter(x=chart_df.index, y=chart_df['MA20'],
                              mode='lines', name=f'MA20 ({ma20_val:,.0f})',
                              line=dict(color='orange', width=1.5)),
                    row=1, col=1
                )
                
                ma60_val = chart_df['MA60'].iloc[-1]
                fig.add_trace(
                    go.Scatter(x=chart_df.index, y=chart_df['MA60'],
                              mode='lines', name=f'MA60 ({ma60_val:,.0f})',
                              line=dict(color='purple', width=1.5)),
                    row=1, col=1
                )
                
                # 볼린저밴드 상단 (마지막 값 표시)
                bb_up_val = chart_df['BB_Upper'].iloc[-1]
                fig.add_trace(
                    go.Scatter(x=chart_df.index, y=chart_df['BB_Upper'],
                              mode='lines', name=f'BB상단 ({bb_up_val:,.0f})',
                              line=dict(color='gray', width=1, dash='dot')),
                    row=1, col=1
                )
                
                # 손절가 라인
                if 'stop' in row and pd.notna(row['stop']):
                    stop_price = row['stop']
                    fig.add_trace(
                        go.Scatter(
                            x=[chart_df.index[0], chart_df.index[-1]],
                            y=[stop_price, stop_price],
                            mode='lines',
                            name=f'손절 {stop_price:,.0f}',
                            line=dict(color='red', width=1.5, dash='dash'),
                            hoverinfo='name+y'
                        ),
                        row=1, col=1
                    )
                
                # 거래량 바
                colors = ['red' if o <= c else 'blue' for o, c in zip(chart_df['Open'], chart_df['Close'])]
                fig.add_trace(
                    go.Bar(x=chart_df.index, y=chart_df['Volume'],
                           name='거래량', marker_color=colors, opacity=0.5),
                    row=2, col=1
                )
                
                # 차트 주석 추가 (장대양봉, 대량거래 등)
                try:
                    vol_ma20 = chart_df['Volume'].rolling(20).mean()
                    
                    for i in range(20, len(chart_df)):
                        date = chart_df.index[i]
                        close = chart_df['Close'].iloc[i]
                        open_p = chart_df['Open'].iloc[i]
                        vol = chart_df['Volume'].iloc[i]
                        prev_close = chart_df['Close'].iloc[i-1]
                        
                        # 조건 정의
                        is_bullish = close >= open_p
                        body_pct = abs(close - open_p) / open_p * 100
                        change_pct = (close - prev_close) / prev_close * 100
                        vol_ratio = vol / vol_ma20.iloc[i] if vol_ma20.iloc[i] > 0 else 0
                        
                        annotation_text = ""
                        bg_color = ""
                        
                        # 1. 장대양봉 + 대량 (4% 이상 상승, 거래량 2.5배)
                        if change_pct >= 4 and vol_ratio >= 2.5:
                            annotation_text = "🔥장대+대량"
                            bg_color = "#FFD700"  # 골드
                        # 2. 장대음봉 + 대량 (4% 이상 하락, 거래량 2.5배)
                        elif change_pct <= -4 and vol_ratio >= 2.5:
                            annotation_text = "💀장대+대량"
                            bg_color = "#00BFFF"  # 딥 스카이 블루
                        # 3. 대량거래 (그냥 거래량만 2.5배)
                        elif vol_ratio >= 2.5:
                            annotation_text = "⚡대량"
                            bg_color = "#FFFFFF"
                        
                        if annotation_text:
                            fig.add_annotation(
                                x=date, y=chart_df['High'].iloc[i],
                                text=annotation_text,
                                showarrow=True,
                                arrowhead=1,
                                arrowcolor="gray",
                                arrowsize=1,
                                arrowwidth=1,
                                ax=0, ay=-30,
                                bgcolor=bg_color,
                                bordercolor="gray",
                                borderwidth=1,
                                opacity=0.8,
                                font=dict(size=9, color="black"),
                                row=1, col=1
                            )
                except Exception as e:
                    print(f"Annotation Error: {e}")


                # 레이아웃
                fig.update_layout(
                    height=550,
                    xaxis_rangeslider_visible=False,
                    hovermode='x unified',
                    showlegend=True,
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.02,
                        xanchor="center",
                        x=0.5,
                        font=dict(size=12),
                        itemsizing='constant',
                        itemwidth=50
                    ),
                    margin=dict(l=5, r=5, t=40, b=5)
                )
                
                fig.update_xaxes(showticklabels=False, row=1, col=1)
                fig.update_xaxes(showticklabels=True, row=2, col=1, tickfont=dict(size=10))
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
