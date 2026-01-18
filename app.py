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
    col_f1, col_f2 = st.columns([3, 1])
    with col_f1:
        min_score = st.slider("최소 점수", 0, 100, 50)
    with col_f2:
        if st.button("🔄 새로고침"):
            st.cache_data.clear()
            st.rerun()

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
        # '기타' 섹터가 1위가 아닌 경우만 표시
        valid_sector_df = sector_df[sector_df['Sector'] != '기타']
        if len(valid_sector_df) > 0:
            top_sectors = valid_sector_df.head(5)[['Sector', 'AvgReturn_3M', 'StockCount']]
            st.dataframe(
                top_sectors.style.format({'AvgReturn_3M': '{:.1f}%'}),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.caption("⚠️ 유효한 섹터 데이터가 없습니다.")
            st.caption("💡 다음 워크플로우 실행 시 생성됩니다.")
    else:
        st.caption("⚠️ 섹터 랭킹 파일(`sector_rankings.csv`)이 없습니다.")
        st.caption("💡 GitHub에 코드 푸시 후 워크플로우를 실행하세요.")
    
with col_b:
    st.success("🎯 스캐너 포착 섹터")
    if 'sector' in df.columns:
        valid_sectors = df[df['sector'] != '기타']['sector']
        if len(valid_sectors) > 0:
            scanner_sectors = valid_sectors.value_counts().head(5).reset_index()
            scanner_sectors.columns = ['Sector', 'Count']
            
            # 시장 주도 섹터와 일치 여부 확인
            if sector_df is not None:
                market_leaders = sector_df[sector_df['Sector'] != '기타'].head(5)['Sector'].tolist()
                scanner_sectors['일치'] = scanner_sectors['Sector'].apply(
                    lambda x: "✅" if x in market_leaders else "-"
                )
            
            st.dataframe(scanner_sectors, use_container_width=True, hide_index=True)
        else:
            st.caption("⚠️ 섹터 정보가 '기타'만 있습니다.")
            st.caption("💡 워크플로우 재실행 시 정상 로드됩니다.")
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
            import textwrap
            
            current_price = row['close']
            ma20 = row.get('ma20', current_price)
            ma60 = row.get('ma60', current_price)
            base_stop = row.get('stop', current_price * 0.92)
            bb_upper = row.get('bb_upper', current_price * 1.05)
            
            # ==============================
            # 전략별 진입가 및 손절가 (동적 계산)
            # ==============================
            
            # 1. 눌림목 전략: MA20 진입, 손절 = MA20 -3% 또는 기존 stop 중 높은 쪽
            pullback_price = ma20
            pullback_stop = max(pullback_price * 0.97, base_stop)
            risk_pullback = (pullback_price - pullback_stop) / pullback_price * 100
            
            # 2. 추세 돌파 전략: BB상단 진입, 손절 = 진입가 -5%
            breakout_price = bb_upper if bb_upper > current_price else current_price * 1.02
            breakout_stop = breakout_price * 0.95
            risk_breakout = (breakout_price - breakout_stop) / breakout_price * 100
            
            # 3. 오닐/미너비니 전략: 패턴별 가격, 손절 = 진입가 -7%
            oneil_msg = "패턴 형성 대기중"
            oneil_price = 0
            oneil_stop = 0
            oneil_risk = 0
            oneil_setup_name = "-"
            
            try:
                import FinanceDataReader as fdr
                from datetime import timedelta
                end_date_s = datetime.now()
                start_date_s = end_date_s - timedelta(days=60)
                sub_df = fdr.DataReader(row['code'], start_date_s, end_date_s)
                
                if sub_df is not None and len(sub_df) >= 2:
                    today = sub_df.iloc[-1]
                    prev = sub_df.iloc[-2]
                    
                    # Inside Day 패턴
                    if today['High'] < prev['High'] and today['Low'] > prev['Low']:
                        oneil_price = today['High']
                        oneil_setup_name = "Inside Day 돌파"
                        oneil_msg = f"고가({int(today['High']):,}원) 돌파 시"
                    
                    # Oops Reversal 패턴
                    elif today['Open'] < prev['Low'] and today['Close'] > prev['Low'] and today['Close'] > ma20:
                        oneil_price = today['Close']
                        oneil_setup_name = "Oops Reversal"
                        oneil_msg = "반전 확인. 종가/익일시가"
                        
                    # Pocket Pivot 패턴
                    else:
                        vol_ma = sub_df['Volume'].rolling(20).mean().iloc[-1]
                        if today['Volume'] > vol_ma * 2.5 and today['Close'] > prev['Close'] * 1.04:
                            oneil_price = today['Close']
                            oneil_setup_name = "Pocket Pivot"
                            oneil_msg = "거래량 급등. 매수 유효"
                        
                    # 오닐 손절가: 진입가 -7% (오닐 철칙)
                    if oneil_price > 0:
                        oneil_stop = oneil_price * 0.93
                        oneil_risk = (oneil_price - oneil_stop) / oneil_price * 100
            except:
                pass
            
            # ==============================
            # 🥇 추천 우선순위 결정 로직
            # ==============================
            best_strategy = "관망"
            priority_reason = ""
            
            price_vs_ma20 = (current_price - ma20) / ma20 * 100 if ma20 > 0 else 0
            
            # 1순위: 오닐 패턴 (가장 강력하고 희소함)
            if oneil_price > 0:
                best_strategy = "💎 오닐/미너비니"
                priority_reason = f"패턴({oneil_setup_name}) 발생"
            # 2순위: 눌림목 (리스크가 적음, MA20 근접)
            elif -2 <= price_vs_ma20 <= 4:
                best_strategy = "📉 눌림목"
                priority_reason = "MA20 지지선 근접 (저위험)"
            # 3순위: 돌파 (추세가 강함)
            elif current_price >= bb_upper * 0.98:
                best_strategy = "🚀 추세 돌파"
                priority_reason = "볼린저밴드 상단 돌파 임박/진행"
            else:
                best_strategy = "중립/관망"
                priority_reason = "명확한 진입 시그널 없음"

            # 우선순위 표시
            if best_strategy != "중립/관망":
                st.success(f"🏆 **추천 1순위**: {best_strategy} ({priority_reason})")
            else:
                st.info(f"👀 현재 상태: {best_strategy} ({priority_reason})")
            
            # 3-Track UI (HTML 렌더링 수정: textwrap.dedent 사용)
            col_sc1, col_sc2, col_sc3 = st.columns(3)
            
            with col_sc1:
                html_1 = f"""
                <div style="background-color:rgba(0,255,0,0.1); padding:10px; border-radius:10px; height:100%;">
                    <strong>📉 눌림목</strong><br>
                    진입: <strong>{pullback_price:,.0f}원</strong><br>
                    손절: {pullback_stop:,.0f}원<br>
                    <span style="font-size:0.8em; color:#666;">리스크: {risk_pullback:.1f}%</span>
                </div>
                """
                st.markdown(textwrap.dedent(html_1), unsafe_allow_html=True)
                
            with col_sc2:
                html_2 = f"""
                <div style="background-color:rgba(255,165,0,0.1); padding:10px; border-radius:10px; height:100%;">
                    <strong>🚀 추세 돌파</strong><br>
                    진입: <strong>{breakout_price:,.0f}원</strong><br>
                    손절: {breakout_stop:,.0f}원<br>
                    <span style="font-size:0.8em; color:#666;">리스크: {risk_breakout:.1f}%</span>
                </div>
                """
                st.markdown(textwrap.dedent(html_2), unsafe_allow_html=True)
                
            with col_sc3:
                bg_color = "rgba(138,43,226,0.1)" if oneil_price > 0 else "rgba(128,128,128,0.1)"
                if oneil_price > 0:
                    content = f"""
                    진입: <strong>{oneil_price:,.0f}원</strong><br>
                    손절: {oneil_stop:,.0f}원<br>
                    <span style="font-size:0.8em; color:#666;">리스크: {oneil_risk:.1f}%</span>
                    """
                else:
                    content = f"""
                    <span style="color:gray;">{oneil_msg}</span><br>
                    <span style="font-size:0.8em;">패턴이 나타나면 추천됩니다</span>
                    """
                
                # HTML 렌더링 문제 해결을 위해 dedent 적용
                html_3 = f"""
                <div style="background-color:{bg_color}; padding:10px; border-radius:10px; height:100%;">
                    <strong>💎 오닐/미너비니</strong><br>
                    <span style="font-size:0.8em; color:#999;">({oneil_setup_name})</span><br>
                    {content}
                </div>
                """
                st.markdown(textwrap.dedent(html_3), unsafe_allow_html=True)

            st.caption(f"⚠️ 기본 손절가: {base_stop:,.0f}원 | 전략별 손절가는 진입가 기준으로 동적 계산됩니다.")
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
                
                # 오닐 진입가/손절가 라인 (패턴 감지된 경우)
                try:
                    # 오닐 패턴 다시 분석 (차트 데이터 사용)
                    if len(chart_df) >= 2:
                        today_c = chart_df.iloc[-1]
                        prev_c = chart_df.iloc[-2]
                        ma20_chart = chart_df['MA20'].iloc[-1]
                        vol_ma_chart = chart_df['Volume'].rolling(20).mean().iloc[-1]
                        
                        oneil_entry = 0
                        oneil_sl = 0
                        oneil_label = ""
                        
                        # Inside Day
                        if today_c['High'] < prev_c['High'] and today_c['Low'] > prev_c['Low']:
                            oneil_entry = today_c['High']
                            oneil_sl = oneil_entry * 0.93
                            oneil_label = "Inside Day"
                        # Oops Reversal
                        elif today_c['Open'] < prev_c['Low'] and today_c['Close'] > prev_c['Low'] and today_c['Close'] > ma20_chart:
                            oneil_entry = today_c['Close']
                            oneil_sl = oneil_entry * 0.93
                            oneil_label = "Oops"
                        # Pocket Pivot
                        elif today_c['Volume'] > vol_ma_chart * 2.5 and today_c['Close'] > prev_c['Close'] * 1.04:
                            oneil_entry = today_c['Close']
                            oneil_sl = oneil_entry * 0.93
                            oneil_label = "Pocket Pivot"
                        
                        # 오닐 라인 추가
                        if oneil_entry > 0:
                            # 진입가 라인 (보라색 점선)
                            fig.add_trace(
                                go.Scatter(
                                    x=[chart_df.index[0], chart_df.index[-1]],
                                    y=[oneil_entry, oneil_entry],
                                    mode='lines',
                                    name=f'💎진입 {oneil_entry:,.0f}',
                                    line=dict(color='purple', width=1.5, dash='dot'),
                                    hoverinfo='name+y'
                                ),
                                row=1, col=1
                            )
                            # 오닐 손절가 라인 (보라색 대시)
                            fig.add_trace(
                                go.Scatter(
                                    x=[chart_df.index[0], chart_df.index[-1]],
                                    y=[oneil_sl, oneil_sl],
                                    mode='lines',
                                    name=f'💎손절 {oneil_sl:,.0f}',
                                    line=dict(color='violet', width=1, dash='dash'),
                                    hoverinfo='name+y'
                                ),
                                row=1, col=1
                            )
                            # 오닐 패턴 주석
                            fig.add_annotation(
                                x=chart_df.index[-1], y=oneil_entry,
                                text=f"💎{oneil_label}",
                                showarrow=True,
                                arrowhead=2,
                                arrowcolor="purple",
                                ax=40, ay=0,
                                bgcolor="rgba(138,43,226,0.2)",
                                bordercolor="purple",
                                font=dict(size=10, color="purple"),
                                row=1, col=1
                            )
                except Exception as e:
                    print(f"O'Neil Line Error: {e}")
                
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
