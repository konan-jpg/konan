# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import glob
import os
import requests
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from news_analyzer import search_naver_news
import FinanceDataReader as fdr
import yaml
from scanner_core import calculate_signals, score_stock
from image_analysis import analyze_chart_image

st.set_page_config(layout="wide", page_title="추세추종 스캐너")

def get_investor_data_realtime(code):
    """실시간 수급 데이터 조회 (네이버 금융)"""
    try:
        code = str(code).zfill(6)
        url = f"https://finance.naver.com/item/frgn.naver?code={code}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers, timeout=5)
        dfs = pd.read_html(r.text, encoding='cp949')
        
        target_df = None
        for df in dfs:
            if '외국인' in str(df.columns): target_df = df; break
        if target_df is None and len(dfs) >= 2: target_df = dfs[1]
        
        if target_df is not None:
            df = target_df.dropna(how='all').head(10)
            f_con, f_net, i_net = 0, 0, 0
            
            # 컬럼 찾기
            cols = [str(c).lower() for c in df.columns]
            f_col = next((i for i, c in enumerate(cols) if '외국인' in c), -1)
            i_col = next((i for i, c in enumerate(cols) if '기관' in c), -1)
            p_col = next((i for i, c in enumerate(cols) if '종가' in c), -1)
            
            if f_col != -1 and i_col != -1:
                counting = True
                for _, row in df.iterrows():
                    try:
                        price = float(str(row.iloc[p_col]).replace(',', '')) if p_col != -1 else 1
                        f_val = float(str(row.iloc[f_col]).replace(',', ''))
                        i_val = float(str(row.iloc[i_col]).replace(',', ''))
                        
                        f_net += f_val * price
                        i_net += i_val * price
                        
                        if counting and f_val > 0: f_con += 1
                        else: counting = False
                    except: continue
                return {
                    'foreign_consecutive_buy': f_con,
                    'inst_net_buy_5d': i_net,
                    'foreign_net_buy_5d': f_net
                }
    except: pass
    return {'foreign_consecutive_buy': 0, 'inst_net_buy_5d': 0, 'foreign_net_buy_5d': 0}

@st.cache_data(ttl=300)
def load_config():
    cfg_path = "config.yaml"
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}

@st.cache_data(ttl=300)
def load_data():
    df, filename = None, None
    # 1. 병합된 파일 확인
    merged_files = [f for f in glob.glob("data/scanner_output*.csv") if "chunk" not in f]
    if merged_files:
        def extract_date(fn):
            try: return os.path.basename(fn).replace('.csv', '').split('_')[-1]
            except: return '0000-00-00'
        latest_file = max(merged_files, key=extract_date)
        try:
            df = pd.read_csv(latest_file, dtype={'code': str})
            filename = os.path.basename(latest_file)
        except Exception as e:
            st.error(f"파일 로드 오류: {e}")
    else:
        # 2. 청크 파일 확인 (병합 파일이 없는 경우)
        chunk_files = glob.glob("data/partial/scanner_output*chunk*.csv")
        if chunk_files:
            try:
                # 날짜별로 그룹화해서 가장 최신 날짜 찾기
                file_dates = set()
                for f in chunk_files:
                    try: file_dates.add(os.path.basename(f).split('_')[2])
                    except: pass
                
                if file_dates:
                    latest_date = sorted(list(file_dates))[-1]
                    target_chunks = [f for f in chunk_files if latest_date in f]
                    df_list = [pd.read_csv(f, dtype={'code': str}) for f in sorted(target_chunks)]
                    if df_list:
                        df = pd.concat(df_list, ignore_index=True).drop_duplicates(subset=['code'], keep='first')
                        filename = f"Merged Chunks ({latest_date})"
            except Exception as e:
                st.error(f"청크 병합 오류: {e}")

    sector_df = None
    if os.path.exists("data/sector_rankings.csv"):
        try:
            sector_df = pd.read_csv("data/sector_rankings.csv")
        except: pass
        
    return df, sector_df, filename

@st.cache_data
def get_krx_codes():
    # 1. fdr 사용
    try:
        df = fdr.StockListing("KRX")
        if df is not None and not df.empty:
            return df[['Code', 'Name']]
    except: pass
    
    # 2. 로컬 파일 사용
    if os.path.exists("data/krx_tickers.csv"):
        return pd.read_csv("data/krx_tickers.csv", dtype={'Code': str})[['Code', 'Name']]
        
    # 3. 스캔 데이터 사용
    df_scan, _, _ = load_data()
    if df_scan is not None:
        return df_scan[['code', 'name']].rename(columns={'code': 'Code', 'name': 'Name'}).drop_duplicates()
        
    return pd.DataFrame({'Code':[], 'Name':[]})

def get_setup_explanations():
    return {
        'R': "🔥 재돌파 (Door Knock + Squeeze)", 
        'B': "📈 거래량 급등 후 고점 돌파", 
        'A': "🏹 스퀴즈 돌파 + ADX 상승", 
        'C': "⚡ 20일선 돌파 (단기 추세 전환)", 
        '-': "대기 (특이 셋업 없음)"
    }

def get_score_explanations():
    return {
        'trend_score': {'name': '추세 (25점)', 'description': '이동평균 정배열 + ADX 강도', 
                        'components': ['현재가>20선:+5', '현재가>50선:+5', '현재가>200선:+5', '정배열:+5', 'ADX강도:+2~5']},
        'pattern_score': {'name': '위치 (30점)', 'description': '매집 패턴 및 돌파 임박', 
                          'components': ['Door Knock:+10', 'Squeeze:+10', 'Setup:+3~5', 'RS80+:각+5']},
        'volume_score': {'name': '거래량 (20점)', 'description': '수급의 흔적 (폭발/수축)', 
                         'components': ['과거폭발:+5', '거래량수축:+3~7', '당일거래량:+3~8']},
        'supply_score': {'name': '수급 (15점)', 'description': '외국인/기관 매수세', 
                         'components': ['외인연속5일+:+8', '외인연속3일+:+5', '기관순매수:+4', '외인순매수:+3']},
        'risk_score': {'name': '리스크 (10점)', 'description': '손절가와의 거리', 
                       'components': ['5%이하:10점', '5~8%:-1', '8~10%:-3', '10%이상:-5']}
    }

def display_stock_report(row, sector_df=None, rs_3m=None, rs_6m=None):
    st.markdown("---")
    st.subheader(f"📊 {row.get('name', 'N/A')} ({row.get('code', '')}) 상세 분석")
    
    # RS 정보 표시
    if rs_3m or rs_6m:
        c1, c2 = st.columns(2)
        if rs_3m: c1.metric("3개월 RS", f"{rs_3m}")
        if rs_6m: c2.metric("6개월 RS", f"{rs_6m}")
    
    # 섹터 정보
    stock_sector = row.get('sector', '기타')
    is_leader = False
    if sector_df is not None and not sector_df.empty:
        leaders = sector_df.head(5)['Sector'].tolist()
        if stock_sector in leaders:
            is_leader = True
            st.success(f"🏆 **주도 섹터 포함**: {stock_sector}")
        else:
            st.info(f"📌 **업종**: {stock_sector}")
    else:
        st.info(f"📌 **업종**: {stock_sector}")

    # 기본 정보 및 점수 (HTML CSS 중괄호 이스케이프 {{, }})
    foreign = int(row.get('foreign_consec_buy', 0))
    inst_net = row.get('inst_net_5d', 0)
    risk_pct = row.get('risk_pct', 0)
    
    st.markdown(f"""
    <style>
    .info-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 20px; }}
    .info-box {{ background: #f0f2f6; padding: 15px; border-radius: 8px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
    .info-label {{ font-size: 12px; color: #666; margin-bottom: 5px; }}
    .info-value {{ font-size: 16px; font-weight: bold; color: #333; }}
    </style>
    <div class="info-grid">
        <div class="info-box"><div class="info-label">현재가</div><div class="info-value">{row['close']:,.0f}원</div></div>
        <div class="info-box"><div class="info-label">총점</div><div class="info-value" style="color: #2e86de;">{row['total_score']:.0f}점</div></div>
        <div class="info-box"><div class="info-label">셋업</div><div class="info-value">{row.get('setup','-')}</div></div>
        <div class="info-box"><div class="info-label">리스크 (손절거리)</div><div class="info-value" style="color: {'red' if risk_pct > 10 else 'green'};">{risk_pct:.1f}%</div></div>
        <div class="info-box"><div class="info-label">외국인 연속매수</div><div class="info-value" style="color: {'red' if foreign > 0 else 'black'};">{foreign}일</div></div>
        <div class="info-box"><div class="info-label">기관 5일 순매수</div><div class="info-value" style="color: {'red' if inst_net > 0 else 'black'};">{inst_net/1e8:,.1f}억</div></div>
    </div>
    """, unsafe_allow_html=True)

    # 셋업 설명 (해당 셋업이 있을 때만 표시)
    current_setup = row.get('setup', '-')
    explanations = get_setup_explanations()
    if current_setup != '-':
        with st.expander(f"ℹ️ **포착된 셋업: {explanations[current_setup]}**", expanded=True):
            st.success(f"{explanations[current_setup]} 패턴이 감지되었습니다.")
    
    st.markdown("---")
    
    # 점수 상세
    st.markdown("#### 📈 점수 구성 상세 (100점 만점)")
    rs_bonus = (5 if rs_3m and rs_3m >= 80 else 0) + (5 if rs_6m and rs_6m >= 80 else 0)
    
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("추세", f"{row.get('trend_score',0):.0f}/25", help="이동평균 정배열 + ADX")
    c2.metric("위치", f"{row.get('pattern_score',0):.0f}/30", help="Door Knock, Squeeze")
    c3.metric("거래량", f"{row.get('volume_score',0):.0f}/20", help="폭발, 수축, 당일확인")
    c4.metric("수급", f"{row.get('supply_score',0):.0f}/15", help="메이저 수급")
    c5.metric("리스크", f"{row.get('risk_score',10):.0f}/10", help="손절가 거리")
    c6.metric("RS가산", f"+{rs_bonus}", help="시장대비 강세 보너스")

    with st.expander("📝 상세 점수 기준 보기"):
        for k, v in get_score_explanations().items():
            st.markdown(f"**{v['name']}**: {v['description']}")
            st.caption(", ".join(v['components']))
            
    # 매수 전략 추천
    st.markdown("---")
    st.markdown("#### 🎯 AI 매수 전략 가이드")
    
    try:
        cp = float(row['close'])
        ma20 = float(row.get('ma20', cp))
        base_stop = float(row.get('stop', cp*0.92))
        bb_upper = float(row.get('bb_upper', cp*1.05))
        
        # 전략 계산
        pullback_price = ma20
        pullback_stop = max(ma20 * 0.97, base_stop)
        
        breakout_price = bb_upper if bb_upper > cp else cp * 1.02
        breakout_stop = breakout_price * 0.95
        
        # 오닐 패턴
        oneil_price, oneil_stop, oneil_msg = 0, 0, ""
        try:
            sub_df = fdr.DataReader(row['code'], datetime.now()-timedelta(days=60), datetime.now())
            if sub_df is not None and len(sub_df) >= 2:
                today = sub_df.iloc[-1]
                prev = sub_df.iloc[-2]
                vol_ma = sub_df['Volume'].rolling(20).mean().iloc[-1]
                
                if today['High'] < prev['High'] and today['Low'] > prev['Low']:
                    oneil_price = today['High']
                    oneil_msg = "Inside Day 돌파"
                elif today['Open'] < prev['Low'] and today['Close'] > prev['Low']:
                    oneil_price = today['Close']
                    oneil_msg = "Oops Reversal"
                elif today['Volume'] > vol_ma * 2:
                    oneil_price = today['Close']
                    oneil_msg = "Pocket Pivot"
                
                if oneil_price > 0:
                    oneil_stop = oneil_price * 0.94
        except: pass
        
        # 카드 표시
        col1, col2, col3 = st.columns(3)
        
        # 1. 눌림목
        with col1:
            risk = (pullback_price - pullback_stop) / pullback_price * 100
            st.markdown(f"""
            <div style="background-color:rgba(0, 128, 0, 0.1); padding:15px; border-radius:10px; border:1px solid green;">
                <h5 style="margin:0; color:green;">📉 눌림목 전략</h5>
                <p style="font-size:13px; margin:5px 0;">20일선 지지 확인 후 매수</p>
                <b>진입: {pullback_price:,.0f}원</b><br>
                <span style="color:red">손절: {pullback_stop:,.0f}원 (-{risk:.1f}%)</span>
            </div>
            """, unsafe_allow_html=True)
            
        # 2. 돌파
        with col2:
            risk = (breakout_price - breakout_stop) / breakout_price * 100
            st.markdown(f"""
            <div style="background-color:rgba(255, 165, 0, 0.1); padding:15px; border-radius:10px; border:1px solid orange;">
                <h5 style="margin:0; color:orange;">🚀 돌파 전략</h5>
                <p style="font-size:13px; margin:5px 0;">BB 상단 강력 돌파 시</p>
                <b>진입: {breakout_price:,.0f}원</b><br>
                <span style="color:red">손절: {breakout_stop:,.0f}원 (-{risk:.1f}%)</span>
            </div>
            """, unsafe_allow_html=True)
            
        # 3. 오닐
        with col3:
            if oneil_price > 0:
                risk = (oneil_price - oneil_stop) / oneil_price * 100
                st.markdown(f"""
                <div style="background-color:rgba(138, 43, 226, 0.1); padding:15px; border-radius:10px; border:1px solid blueviolet;">
                    <h5 style="margin:0; color:blueviolet;">💎 {oneil_msg}</h5>
                    <p style="font-size:13px; margin:5px 0;">특수 패턴 포착</p>
                    <b>진입: {oneil_price:,.0f}원</b><br>
                    <span style="color:red">손절: {oneil_stop:,.0f}원 (-{risk:.1f}%)</span>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div style="background-color:rgba(128, 128, 128, 0.1); padding:15px; border-radius:10px; border:1px solid gray;">
                    <h5 style="margin:0; color:gray;">💎 오닐 패턴</h5>
                    <p style="margin:5px 0;">현재 포착된 특수 패턴 없음</p>
                </div>
                """, unsafe_allow_html=True)
                
    except Exception as e:
        st.error(f"전략 계산 오류: {e}")

    # 차트
    st.markdown("---")
    st.markdown("#### 📉 차트 분석")
    try:
        chart_df = fdr.DataReader(row['code'], datetime.now()-timedelta(days=180), datetime.now())
        if chart_df is not None and len(chart_df) > 0:
            chart_df['MA20'] = chart_df['Close'].rolling(20).mean()
            chart_df['MA60'] = chart_df['Close'].rolling(60).mean()
            mid = chart_df['Close'].rolling(20).mean()
            std = chart_df['Close'].rolling(20).std()
            chart_df['BB_Upper'] = mid + 2*std
            
            fig = make_subplots(rows=2, cols=1, row_heights=[0.7, 0.3], shared_xaxes=True, vertical_spacing=0.05)
            
            # 캔들
            fig.add_trace(go.Candlestick(
                x=chart_df.index, open=chart_df['Open'], high=chart_df['High'], low=chart_df['Low'], close=chart_df['Close'],
                name='주가', increasing_line_color='red', decreasing_line_color='blue'
            ), row=1, col=1)
            
            # 이평선
            fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['MA20'], line=dict(color='orange', width=1.5), name='20일선'), row=1, col=1)
            fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['MA60'], line=dict(color='purple', width=1.5), name='60일선'), row=1, col=1)
            fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['BB_Upper'], line=dict(color='gray', dash='dot'), name='BB상단'), row=1, col=1)
            
            # 손절선 (최근 값)
            if 'stop' in row and pd.notna(row['stop']):
                 fig.add_hline(y=row['stop'], line_dash="dash", line_color="red", annotation_text="손절가", row=1, col=1)

            # 거래량
            colors = ['red' if c >= o else 'blue' for c, o in zip(chart_df['Close'], chart_df['Open'])]
            fig.add_trace(go.Bar(x=chart_df.index, y=chart_df['Volume'], marker_color=colors, name='거래량'), row=2, col=1)
            
            # 불기둥 마커
            vol_ma = chart_df['Volume'].rolling(20).mean()
            for i in range(1, len(chart_df)):
                curr, prev = chart_df.iloc[i], chart_df.iloc[i-1]
                if curr['Volume'] > vol_ma.iloc[i] * 2 and curr['Close'] > curr['Open'] and curr['Close'] > prev['Close'] * 1.05:
                     fig.add_annotation(x=chart_df.index[i], y=curr['High'], text="🔥", showarrow=False, yshift=10, row=1, col=1)

            fig.update_layout(height=600, margin=dict(t=30, b=30, l=30, r=30), xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)
            
    except Exception as e:
        st.warning(f"차트 그리기 오류: {e}")

# --- 메인 앱 시작 ---
st.sidebar.title("🚀 추세추종 스캐너")
mode = st.sidebar.radio("모드 선택", ["🔍 종목 상세 진단", "📊 시장 스캐너", "🖼️ 차트 이미지 분석"])

if st.sidebar.button("🔄 데이터 새로고침"):
    st.cache_data.clear()
    st.rerun()

if mode == "📊 시장 스캐너":
    df, sector_df, filename = load_data()
    
    st.title("📊 당일 시장 스캐너")
    if filename:
        st.caption(f"📅 데이터 기준: {filename} (최신 업데이트)")
    else:
        st.error("⚠️ 데이터 파일이 없습니다. [Github Actions] 탭에서 'Daily Stock Scanner'를 실행해주세요.")
        
    if df is not None:
        # 섹터 분석 표시
        st.subheader("🧭 시장 주도 섹터 (Top-Down)")
        c1, c2 = st.columns(2)
        
        leaders = []
        with c1:
            st.caption("📈 최근 3개월 수익률 상위 섹터")
            if sector_df is not None and not sector_df.empty:
                top_sectors = sector_df.head(5)
                st.dataframe(
                    top_sectors[['Rank','Sector','AvgReturn_3M','StockCount']].style.format({'AvgReturn_3M': '{:.1f}%'}), 
                    use_container_width=True, hide_index=True
                )
                leaders = top_sectors['Sector'].tolist()
            else:
                st.info("섹터 랭킹 데이터가 없습니다.")
        
        with c2:
            st.caption("🎯 오늘 스캐너 포착 섹터")
            if 'sector' in df.columns:
                counts = df['sector'].value_counts().head(5).reset_index()
                counts.columns = ['Sector', 'Count']
                counts['주도주여부'] = counts['Sector'].apply(lambda x: "✅ 일치" if x in leaders else "-")
                st.dataframe(counts, use_container_width=True, hide_index=True)

        st.markdown("---")
        
        # 필터 및 리스트
        min_score = st.slider("최소 점수 필터", 0, 100, 60)
        filtered = df[df['total_score'] >= min_score].copy()
        
        st.subheader(f"🏆 고득점 종목 Top {len(filtered)}")
        
    display_cols = ['name', 'sector', 'close', 'total_score', 'setup', 'trend_score', 'pattern_score', 'volume_score', 'supply_score']
    # 컬럼 존재 여부 확인 후 필터링
    display_cols = [c for c in display_cols if c in filtered.columns]
    
    show_df = filtered[display_cols].rename(columns={
        'name':'종목명', 'sector':'업종', 'close':'현재가', 
        'total_score':'총점', 'setup':'셋업', 
        'trend_score':'추세', 'pattern_score':'위치', 
        'volume_score':'거래량', 'supply_score':'수급'
    })
    
    # 소수점 제거 포맷팅
    format_dict = {
        '현재가': '{:,.0f}',
        '총점': '{:.0f}',
        '추세': '{:.0f}',
        '위치': '{:.0f}',
        '거래량': '{:.0f}',
        '수급': '{:.0f}'
    }
    
    # 선택 기능
    event = st.dataframe(
        show_df.style.format(format_dict, na_rep="-").background_gradient(subset=['총점'], cmap='Blues'),
        use_container_width=True, 
        height=500,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row"
    )
    
    if event.selection and len(event.selection.rows) > 0:
        idx = event.selection.rows[0]
        selected_code = filtered.iloc[idx]['code']
        row = filtered.iloc[idx]
        display_stock_report(row, sector_df)

elif mode == "🔍 종목 상세 진단":
    st.title("🔍 실시간 종목 상세 진단")
    
    # 통합 검색창 (Selectbox with search)
    stock_list = get_krx_codes()
    stock_map = dict(zip(stock_list['Name'], stock_list['Code']))
    
    # 검색 편의를 위해 '이름 (코드)' 형식으로 리스트 생성
    options = [f"{name} ({code})" for name, code in stock_map.items()]
    
    st.write("진단할 종목을 검색하거나 선택하세요.")
    selected_option = st.selectbox("종목 검색", options, index=None, placeholder="종목명 또는 코드를 입력하세요...")

    if selected_option:
        name = selected_option.split(' (')[0]
        code = str(selected_option.split(' (')[1][:-1]).zfill(6)
        
        rs_3m = st.number_input("3개월 RS 점수 (선택사항, 0~99)", 0, 99, 0)
        rs_6m = st.number_input("6개월 RS 점수 (선택사항, 0~99)", 0, 99, 0)
        
        if st.button("🚀 진단 시작"):
            with st.spinner(f"{name} ({code}) 데이터를 분석 중입니다..."):
                # 수급 데이터 로딩 (스캔 데이터 확인 -> 없으면 실시간 크롤링)
                inv_data = {'foreign_consecutive_buy': 0, 'inst_net_buy_5d': 0, 'foreign_net_buy_5d': 0}
                
                df_scan, sector_df, _ = load_data()
                data_found = False
                
                if df_scan is not None:
                    match = df_scan[df_scan['code'] == code]
                    if not match.empty:
                        r = match.iloc[0]
                        inv_data = {
                            'foreign_consecutive_buy': r.get('foreign_consec_buy', 0),
                            'inst_net_buy_5d': r.get('inst_net_5d', 0),
                            'foreign_net_buy_5d': r.get('foreign_net_5d', 0)
                        }
                        if inv_data['inst_net_buy_5d'] != 0 or inv_data['foreign_net_buy_5d'] != 0:
                            data_found = True

                # 스캔 데이터에 없거나 수급이 0이면 실시간 크롤링 시도
                if not data_found:
                    realtime_inv = get_investor_data_realtime(code)
                    if realtime_inv['inst_net_buy_5d'] != 0 or realtime_inv['foreign_net_buy_5d'] != 0:
                        inv_data = realtime_inv
                
                # 데이터 가져오기
                df_stock = fdr.DataReader(code, datetime.now()-timedelta(days=400), datetime.now())
                
                if df_stock is not None and len(df_stock) > 100:
                    cfg = load_config()
                    sig = calculate_signals(df_stock, cfg)
                    result = score_stock(df_stock, sig, cfg, rs_3m=rs_3m, rs_6m=rs_6m, investor_data=inv_data)
                    
                    if result:
                        row = pd.Series(result)
                        row['name'] = name
                        row['code'] = code
                        # 섹터 정보
                        row['sector'] = '기타' 
                        if df_scan is not None and not match.empty:
                            row['sector'] = match.iloc[0].get('sector', '기타')
                            
                        if inv_data:
                            row['foreign_consec_buy'] = inv_data['foreign_consecutive_buy']
                            row['inst_net_5d'] = inv_data['inst_net_buy_5d']
                        
                        display_stock_report(row, sector_df, rs_3m, rs_6m)
                    else:
                        st.error("점수 계산에 실패했습니다.")
                else:
                    st.error("종목 데이터를 가져올 수 없습니다. 신규 상장주거나 거래 정지 종목일 수 있습니다.")

elif mode == "🖼️ 차트 이미지 분석":
    st.title("🖼️ 차트 이미지 분석")
    st.info("HTS/MTS 차트 이미지를 업로드하면 AI가 패턴을 분석하고 점수를 매깁니다.")
    
    uploaded_file = st.file_uploader("이미지 파일 업로드 (PNG, JPG)", type=['png', 'jpg', 'jpeg'])
    
    if uploaded_file:
        st.image(uploaded_file, caption="업로드된 차트", use_column_width=True)
        # 이미지 분석 로직 (Placeholder)
        # from PIL import Image
        # img = Image.open(uploaded_file)
        # result = analyze_chart_image(img)
        # ...
        st.warning("이미지 분석 기능은 현재 서버 설정 확인이 필요합니다 (Tesseract OCR 등).")
        
        # 수동 종목 연동
        st.markdown("---")
        st.write("이미지 분석 대신 종목을 직접 선택하여 점수를 확인할 수 있습니다.")
        stock_list = get_krx_codes()
        opts = [f"{r['Name']} ({r['Code']})" for _, r in stock_list.iterrows()]
        sel = st.selectbox("종목 선택", opts)
        if st.button("분석 실행", key='img_btn'):
            # (위 상세 진단 로직과 동일하게 연결 가능)
            pass
