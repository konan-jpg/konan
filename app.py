# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import glob
import os
import json
import requests
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
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
    
    merged_files = [f for f in glob.glob("data/scanner_output*.csv") 
                    if "chunk" not in f and "latest" not in f]
    chunk_files = glob.glob("data/partial/scanner_output*chunk*.csv")
    
    def get_date_from_filename(fn):
        try:
            basename = os.path.basename(fn)
            parts = basename.replace('scanner_output_', '').split('_')
            date_str = parts[0]
            if date_str.endswith('.csv'): date_str = date_str.replace('.csv', '')
            if len(date_str) == 10 and date_str[4] == '-' and date_str[7] == '-':
                return date_str
            return '0000-00-00'
        except: return '0000-00-00'

    latest_merged_date = '0000-00-00'
    latest_merged_file = None
    if merged_files:
        latest_merged_file = max(merged_files, key=get_date_from_filename)
        latest_merged_date = get_date_from_filename(latest_merged_file)
        
    latest_chunk_date = '0000-00-00'
    if chunk_files:
        latest_chunk_file = max(chunk_files, key=get_date_from_filename)
        latest_chunk_date = get_date_from_filename(latest_chunk_file)
    
    if latest_chunk_date >= latest_merged_date and latest_chunk_date != '0000-00-00':
        try:
            target_chunks = [f for f in chunk_files if latest_chunk_date in os.path.basename(f)]
            if target_chunks:
                df_list = [pd.read_csv(f, dtype={'code': str}) for f in sorted(target_chunks)]
                if df_list:
                    df = pd.concat(df_list, ignore_index=True).drop_duplicates(subset=['code'], keep='first')
                    filename = f"Merged Chunks ({latest_chunk_date})"
        except Exception as e:
            st.error(f"청크 데이터 병합 중 오류: {e}")
            
    if df is None and latest_merged_file:
        try:
            df = pd.read_csv(latest_merged_file, dtype={'code': str})
            filename = os.path.basename(latest_merged_file)
        except Exception as e:
            st.error(f"파일 로드 오류: {e}")

    sector_df = None
    if os.path.exists("data/sector_rankings.csv"):
        try: sector_df = pd.read_csv("data/sector_rankings.csv")
        except: pass
        
    return df, sector_df, filename

@st.cache_data
def get_krx_codes():
    try:
        df = fdr.StockListing("KRX")
        if df is not None and not df.empty:
            return df[['Code', 'Name']]
    except: pass
    
    if os.path.exists("data/krx_tickers.csv"):
        return pd.read_csv("data/krx_tickers.csv", dtype={'Code': str})[['Code', 'Name']]
        
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
                        'components': ['현재가>20선:+5', '현재가>50선:+5', '현재가>200선:+5', '정배열:+5', 'ADX강도:+2-5']},
        'pattern_score': {'name': '위치 (30점)', 'description': '매집 패턴 및 돌파 임박', 
                          'components': ['Door Knock:+10', 'Squeeze:+10', 'Setup:+3-5']},
        'volume_score': {'name': '거래량 (20점)', 'description': '수급의 흔적 (폭발/수축)', 
                         'components': ['과거폭발:+5', '거래량수축:+3-7', '당일거래량:+3-8']},
        'supply_score': {'name': '수급 (15점)', 'description': '외국인/기관 매수세', 
                         'components': ['외인연속5일+:+8', '외인연속3일+:+5', '기관순매수:+4', '외인순매수:+3']},
        'risk_score': {'name': '리스크 (10점)', 'description': '손절가와의 거리', 
                       'components': ['5%이하:10점', '5-8%:-1', '8-10%:-3', '10%이상:-5']}
    }

def get_detail_text(key, val):
    """점수 상세 항목 텍스트 생성 - 0점도 표시, RS 제외"""
    max_scores = {
        'trend_ma20': 5, 'trend_ma50': 5, 'trend_ma200': 5,
        'trend_align_20_50': 3, 'trend_align_50_200': 2,
        'trend_adx': 5,
        'pat_door_knock': 10, 'pat_squeeze': 10,
        'pat_setup_a': 4, 'pat_setup_b': 5, 'pat_setup_c': 3,
        'vol_explosion': 5, 'vol_dryup': 7, 'vol_today': 8,
        'sup_foreign_consec': 8, 'sup_inst_net': 4, 'sup_foreign_net': 3,
        'risk_safe': 10, 'risk_deduction': 10
    }
    
    maps = {
        'trend_ma20': '현재가 > 20일선', 
        'trend_ma50': '현재가 > 50일선', 
        'trend_ma200': '현재가 > 200일선',
        'trend_align_20_50': '20일 > 50일 정배열', 
        'trend_align_50_200': '50일 > 200일 정배열',
        'trend_adx': 'ADX 강한 추세',
        'pat_door_knock': 'Door Knock 패턴', 
        'pat_squeeze': 'Squeeze (변동성 축소)',
        'pat_setup_a': 'Setup A (스퀴즈 돌파)', 
        'pat_setup_b': 'Setup B (기준봉 돌파)', 
        'pat_setup_c': 'Setup C (20일선 돌파)',
        'vol_explosion': '과거 거래량 폭발', 
        'vol_dryup': '거래량 수축 발생', 
        'vol_today': '당일 거래량 강세',
        'sup_foreign_consec': '외국인 연속 매수', 
        'sup_inst_net': '기관 순매수', 
        'sup_foreign_net': '외국인 순매수',
        'risk_safe': '리스크 5% 이내', 
        'risk_deduction': '리스크 관리 감점'
    }
    
    desc = maps.get(key, key)
    max_score = max_scores.get(key, 10)
    score = abs(val) if val < 0 else val
    
    return f"{desc} ({score}/{max_score})"

def display_score_details_all_items(details):
    """모든 항목 표시 (0점 포함, RS 제외)"""
    all_items = {
        'trend': [
            ('trend_ma20', 5),
            ('trend_ma50', 5),
            ('trend_ma200', 5),
            ('trend_align_20_50', 3),
            ('trend_align_50_200', 2),
            ('trend_adx', 5)
        ],
        'pattern': [
            ('pat_door_knock', 10),
            ('pat_squeeze', 10),
            ('pat_setup_b', 5),
            ('pat_setup_a', 4),
            ('pat_setup_c', 3),
        ],
        'volume': [
            ('vol_explosion', 5),
            ('vol_dryup', 7),
            ('vol_today', 8)
        ],
        'supply': [
            ('sup_foreign_consec', 8),
            ('sup_inst_net', 4),
            ('sup_foreign_net', 3)
        ],
        'risk': [
            ('risk_safe', 10),
            ('risk_deduction', 10)
        ]
    }
    
    cols = st.columns(3)
    
    with cols[0]:
        st.caption("📈 추세 & 위치")
        for key, max_val in all_items['trend'] + all_items['pattern']:
            actual_val = details.get(key, 0)
            st.markdown(f"- {get_detail_text(key, actual_val)}")
    
    with cols[1]:
        st.caption("📊 거래량 & 수급")
        for key, max_val in all_items['volume'] + all_items['supply']:
            actual_val = details.get(key, 0)
            st.markdown(f"- {get_detail_text(key, actual_val)}")
    
    with cols[2]:
        st.caption("🛡️ 리스크")
        for key, max_val in all_items['risk']:
            actual_val = details.get(key, 0)
            st.markdown(f"- {get_detail_text(key, actual_val)}")

def display_stock_report(row, sector_df=None, rs_3m=None, rs_6m=None):
    st.markdown("---")
    st.subheader(f"📊 {row.get('name', 'N/A')} ({row.get('code', '')}) 상세 분석")
    
    stock_sector = row.get('sector', '기타')
    if sector_df is not None and not sector_df.empty:
        leaders = sector_df.head(5)['Sector'].tolist()
        if stock_sector in leaders:
            st.success(f"🏆 **주도 섹터 포함**: {stock_sector}")
        else:
            st.info(f"📌 **업종**: {stock_sector}")
    else:
        st.info(f"📌 **업종**: {stock_sector}")

    foreign = int(row.get('foreign_consec_buy', 0))
    foreign_net = row.get('foreign_net_5d', 0) if 'foreign_net_5d' in row else row.get('foreign_net', 0)
    inst_net = row.get('inst_net_5d', 0)
    risk_pct = row.get('risk_pct', 0)
    base_stop = row.get('stop', 0)
    
    st.markdown(f"""
    <style>
    .info-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 20px; }}
    .info-box {{ background: #f0f2f6; padding: 15px; border-radius: 8px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
    .lb {{ font-size: 12px; color: #666; margin-bottom: 5px; }}
    .val {{ font-size: 16px; font-weight: bold; color: #333; }}
    </style>
    <div class="info-grid">
        <div class="info-box"><div class="lb">현재가</div><div class="val">{row['close']:,.0f}원</div></div>
        <div class="info-box"><div class="lb">기본 손절가</div><div class="val" style="color: red;">{base_stop:,.0f}원</div></div>
        <div class="info-box"><div class="lb">리스크</div><div class="val" style="color: {'red' if risk_pct > 10 else 'green'};">{risk_pct:.1f}%</div></div>
        <div class="info-box"><div class="lb">총점</div><div class="val" style="color: #2e86de;">{row['total_score']:.0f}점</div></div>
        <div class="info-box"><div class="lb">셋업</div><div class="val">{row.get('setup','-')}</div></div>
        <div class="info-box"><div class="lb">외국인 연속</div><div class="val" style="color: {'red' if foreign > 0 else 'black'};">{foreign}일</div></div>
        <div class="info-box"><div class="lb">외국인 5일합</div><div class="val" style="color: {'red' if foreign_net > 0 else 'black'};">{foreign_net/1e8:,.1f}억</div></div>
        <div class="info-box"><div class="lb">기관 5일합</div><div class="val" style="color: {'red' if inst_net > 0 else 'black'};">{inst_net/1e8:,.1f}억</div></div>
    </div>
    """, unsafe_allow_html=True)

    current_setup = row.get('setup', '-')
    explanations = get_setup_explanations()
    if current_setup != '-':
        with st.expander(f"ℹ️ **포착된 셋업: {explanations[current_setup]}**", expanded=True):
            st.success(f"{explanations[current_setup]} 패턴이 감지되었습니다.")
    
    st.markdown("---")
    
    st.markdown("#### 📈 점수 구성 상세 (100점 만점)")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("추세 (25)", f"{row.get('trend_score',0):.0f}")
    c2.metric("위치 (30)", f"{row.get('pattern_score',0):.0f}")
    c3.metric("거래량 (20)", f"{row.get('volume_score',0):.0f}")
    c4.metric("수급 (15)", f"{row.get('supply_score',0):.0f}")
    c5.metric("리스크 (10)", f"{row.get('risk_score',10):.0f}")

    score_details = row.get('score_details', None)
    if isinstance(score_details, str):
        try:
            score_details = json.loads(score_details)
        except:
            score_details = None
    
    if score_details and isinstance(score_details, dict):
        with st.expander("📝 상세 점수 획득 내역 보기", expanded=True):
            display_score_details_all_items(score_details)
    else:
        with st.expander("📝 상세 점수 기준 보기"):
            for k, v in get_score_explanations().items():
                st.markdown(f"**{v['name']}**: {v['description']}")
                st.caption(", ".join(v['components']))
            
    st.markdown("---")
    st.markdown("#### 🎯 AI 매수 전략 가이드")
    
    try:
        cp = float(row['close'])
        strategies = []
        use_csv_strategies = False
        
        if 'strat1_type' in row and pd.notna(row.get('strat1_type')):
            use_csv_strategies = True
            strategies = [
                {'type': row.get('strat1_type',''), 'name': row.get('strat1_name',''), 
                 'entry': float(row.get('strat1_entry',0)), 'stop': float(row.get('strat1_stop',0)),
                 'risk': float(row.get('strat1_risk',0)), 'active': True},
                {'type': row.get('strat2_type',''), 'name': row.get('strat2_name',''),
                 'entry': float(row.get('strat2_entry',0)), 'stop': float(row.get('strat2_stop',0)),
                 'risk': float(row.get('strat2_risk',0)), 'active': True},
                {'type': row.get('strat3_type',''), 'name': row.get('strat3_name',''),
                 'entry': float(row.get('strat3_entry',0)), 'stop': float(row.get('strat3_stop',0)),
                 'risk': float(row.get('strat3_risk',0)), 'active': row.get('strat3_name','') not in ['오닐', '']}
            ]
        
        if not use_csv_strategies:
            ma20 = float(row.get('ma20', cp))
            ma10 = cp
            base_stop = float(row.get('stop', cp*0.92))
            bb_upper = float(row.get('bb_upper', cp*1.05))
            atr20 = cp * 0.02
            climax_low = base_stop
        
            try:
                sub_df = fdr.DataReader(row['code'], datetime.now()-timedelta(days=100), datetime.now())
                if sub_df is not None and len(sub_df) >= 20:
                    tr = pd.concat([
                        sub_df['High'] - sub_df['Low'],
                        (sub_df['High'] - sub_df['Close'].shift(1)).abs(),
                        (sub_df['Low'] - sub_df['Close'].shift(1)).abs()
                    ], axis=1).max(axis=1)
                    atr20 = tr.rolling(20).mean().iloc[-1]
                    
                    ma10 = sub_df['Close'].rolling(10).mean().iloc[-1]
                    
                    vol_avg = sub_df['Volume'].rolling(20).mean()
                    climax_mask = sub_df['Volume'] >= (vol_avg * 3)
                    if climax_mask.any():
                        climax_low = sub_df.loc[climax_mask, 'Low'].iloc[-1]
                    else:
                        climax_low = sub_df['Low'].tail(10).min()
                    
                    today = sub_df.iloc[-1]
                    prev = sub_df.iloc[-2]
                    vol_ma = sub_df['Volume'].rolling(20).mean().iloc[-1]
            except:
                sub_df = None
                today, prev, vol_ma = None, None, 0
            
            pullback_entry = ma20
            pullback_stop = max(climax_low, pullback_entry - 1.2 * atr20)
            if pullback_stop >= pullback_entry:
                pullback_stop = pullback_entry * 0.95
            pullback_risk = (pullback_entry - pullback_stop) / pullback_entry * 100
            
            strategies.append({
                'name': '눌림목', 'icon': '📉', 'desc': '20일선 지지',
                'entry': pullback_entry, 'stop': pullback_stop, 'risk': pullback_risk,
                'color': 'green', 'active': True
            })
            
            breakout_entry = bb_upper if bb_upper > cp else cp * 1.02
            breakout_stop = breakout_entry - 1.5 * atr20
            if breakout_stop >= breakout_entry:
                breakout_stop = breakout_entry * 0.95
            breakout_risk = (breakout_entry - breakout_stop) / breakout_entry * 100
            
            strategies.append({
                'name': '돌파', 'icon': '🚀', 'desc': 'BB60 상단 돌파',
                'entry': breakout_entry, 'stop': breakout_stop, 'risk': breakout_risk,
                'color': 'orange', 'active': True
            })
            
            oneil_entry, oneil_stop, oneil_msg = 0, 0, ""
            oneil_active = False
            
            if sub_df is not None and today is not None and prev is not None:
                if today['High'] < prev['High'] and today['Low'] > prev['Low']:
                    oneil_entry, oneil_msg = today['High'], "Inside Day"
                elif today['Open'] < prev['Low'] and today['Close'] > prev['Low']:
                    oneil_entry, oneil_msg = today['Close'], "Oops Reversal"
                elif today['Volume'] > vol_ma * 2 and today['Close'] > today['Open']:
                    oneil_entry, oneil_msg = today['Close'], "Pocket Pivot"
                
                if oneil_entry > 0:
                    oneil_stop = max(ma10, oneil_entry - atr20)
                    if oneil_stop >= oneil_entry:
                        oneil_stop = oneil_entry * 0.94
                    oneil_active = True
            
            if oneil_active:
                oneil_risk = (oneil_entry - oneil_stop) / oneil_entry * 100
                strategies.append({
                    'name': oneil_msg, 'icon': '💎', 'desc': '오닐 패턴',
                    'entry': oneil_entry, 'stop': oneil_stop, 'risk': oneil_risk,
                    'color': 'blueviolet', 'active': True
                })
            else:
                strategies.append({
                    'name': '오닐 패턴', 'icon': '💎', 'desc': '포착 없음',
                    'entry': 0, 'stop': 0, 'risk': 999,
                    'color': 'gray', 'active': False
                })
            
            strategies.sort(key=lambda x: (not x['active'], x['risk']))
        
        if use_csv_strategies:
            for strat in strategies:
                if strat['type'] == 'pullback':
                    strat['icon'] = '📉'
                    strat['color'] = 'green'
                    strat['desc'] = '20일선 지지'
                elif strat['type'] == 'breakout':
                    strat['icon'] = '🚀'
                    strat['color'] = 'orange'
                    strat['desc'] = 'BB60 상단 돌파'
                else:
                    strat['icon'] = '💎'
                    strat['color'] = 'blueviolet' if strat['active'] else 'gray'
                    strat['desc'] = '오닐 패턴'
        
        col1, col2, col3 = st.columns(3)
        cols = [col1, col2, col3]
        rank_labels = ['1순위', '2순위', '3순위']
        
        for i, (col, strat, rank) in enumerate(zip(cols, strategies, rank_labels)):
            with col:
                if strat['active']:
                    risk_pct = strat['risk']
                    st.markdown(f"""<div style="background-color:rgba({'0,128,0' if i==0 else '255,165,0' if i==1 else '138,43,226'},0.1);padding:15px;border-radius:10px;border:1px solid {strat['color']};">
                        <span style="background:{strat['color']};color:white;padding:2px 8px;border-radius:10px;font-size:11px;">{rank}</span>
                        <h5 style="margin:5px 0 0;color:{strat['color']};">{strat['icon']} {strat['name']} 전략</h5>
                        <p style="font-size:13px;margin:5px 0;">{strat['desc']}</p>
                        <b>진입: {strat['entry']:,.0f}원</b><br>
                        <span style="color:red">손절: {strat['stop']:,.0f}원 (-{risk_pct:.1f}%)</span>
                    </div>""", unsafe_allow_html=True)
                else:
                    st.markdown(f"""<div style="background-color:rgba(128,128,128,0.1);padding:15px;border-radius:10px;border:1px solid gray;">
                        <span style="background:gray;color:white;padding:2px 8px;border-radius:10px;font-size:11px;">{rank}</span>
                        <h5 style="margin:5px 0 0;color:gray;">{strat['icon']} {strat['name']}</h5>
                        <p style="margin:5px 0;">{strat['desc']}</p>
                    </div>""", unsafe_allow_html=True)

    except Exception as e: st.error(f"전략 오류: {e}")

    st.markdown("---")
    st.markdown(f"#### 📉 차트 분석 (현재가: {row['close']:,.0f}원)")
    try:
        code_str = str(row['code']).zfill(6)
        chart_df = fdr.DataReader(code_str, datetime.now()-timedelta(days=180), datetime.now())
        
        if chart_df is not None and len(chart_df) > 0:
            chart_df['MA20'] = chart_df['Close'].rolling(20).mean()
            chart_df['MA60'] = chart_df['Close'].rolling(60).mean()
            mid = chart_df['Close'].rolling(60).mean()
            std = chart_df['Close'].rolling(60).std()
            chart_df['BB_Upper'] = mid + 2*std
            
            fig = make_subplots(rows=2, cols=1, row_heights=[0.7, 0.3], shared_xaxes=True, vertical_spacing=0.05)
            
            fig.add_trace(go.Candlestick(
                x=chart_df.index, open=chart_df['Open'], high=chart_df['High'], low=chart_df['Low'], close=chart_df['Close'],
                name=f'주가 ({row["close"]:,.0f})', increasing_line_color='red', decreasing_line_color='blue'
            ), row=1, col=1)
            
            fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['MA20'], line=dict(color='orange', width=1.5), name='20일선'), row=1, col=1)
            fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['MA60'], line=dict(color='purple', width=1.5), name='60일선'), row=1, col=1)
            fig.add_trace(go.Scatter(x=chart_df.index, y=chart_df['BB_Upper'], line=dict(color='gray', dash='dot'), name='BB상단'), row=1, col=1)
            
            if 'stop' in row and pd.notna(row['stop']):
                 fig.add_hline(y=row['stop'], line_dash="dash", line_color="red", annotation_text="손절가", row=1, col=1)

            colors = ['red' if c >= o else 'blue' for c, o in zip(chart_df['Close'], chart_df['Open'])]
            fig.add_trace(go.Bar(x=chart_df.index, y=chart_df['Volume'], marker_color=colors, name='거래량'), row=2, col=1)
            
            vol_ma = chart_df['Volume'].rolling(20).mean()
            for i in range(1, len(chart_df)):
                d = chart_df.iloc[i]
                prev = chart_df.iloc[i-1]
                if d['Volume'] > vol_ma.iloc[i] * 2 and d['Close'] > d['Open'] and d['Close'] > prev['Close'] * 1.05:
                     fig.add_annotation(x=chart_df.index[i], y=d['High'], text="🔥", showarrow=False, yshift=10, row=1, col=1)
            
            try:
                if 'oneil_msg' in dir() and oneil_msg:
                    fig.add_annotation(x=chart_df.index[-1], y=chart_df['High'].iloc[-1], text=f"💎{oneil_msg}", showarrow=True, arrowhead=1, row=1, col=1)
            except:
                pass

            fig.update_layout(
                height=600, 
                margin=dict(t=50, b=30, l=30, r=30), 
                xaxis_rangeslider_visible=False,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                title=f"{row['name']} 차트 분석 (현재가: {row['close']:,.0f})"
            )
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
    st.info("📌 **총점 65점 이상만 매수대상** | 필수: 6개월 RS 70점 이상, 보조: 3개월 RS 65점 이상")
    if filename:
        st.caption(f"📅 데이터 기준: {filename} (최신 업데이트)")
    else:
        st.error("⚠️ 데이터 파일이 없습니다. [Github Actions] 탭에서 'Daily Stock Scanner'를 실행해주세요.")
        
    if df is not None:
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
        
        min_score = st.number_input("최소 점수 필터", min_value=0, max_value=100, value=65, step=5)
        filtered = df[df['total_score'] >= min_score].copy()
        
        st.subheader(f"🏆 고득점 종목 Top {len(filtered)}")
        
        display_cols = ['name', 'sector', 'close', 'total_score', 'setup', 'trend_score', 'pattern_score', 'volume_score', 'supply_score']
        display_cols = [c for c in display_cols if c in filtered.columns]
        
        show_df = filtered[display_cols].rename(columns={
            'name':'종목명', 'sector':'업종', 'close':'현재가', 
            'total_score':'총점', 'setup':'셋업', 
            'trend_score':'추세', 'pattern_score':'위치', 
            'volume_score':'거래량', 'supply_score':'수급'
        })
        
        format_dict = {
            '현재가': '{:,.0f}',
            '총점': '{:.0f}',
            '추세': '{:.0f}',
            '위치': '{:.0f}',
            '거래량': '{:.0f}',
            '수급': '{:.0f}'
        }
        
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
    st.info("📌 **총점 65점 이상만 매수대상** | 필수: 6개월 RS 70점 이상, 보조: 3개월 RS 65점 이상")
    
    stock_list = get_krx_codes()
    stock_map = dict(zip(stock_list['Name'], stock_list['Code']))
    
    options = [f"{name} ({code})" for name, code in stock_map.items()]
    
    st.write("진단할 종목을 검색하거나 선택하세요.")
    selected_option = st.selectbox("종목 검색", options, index=None, placeholder="종목명 또는 코드를 입력하세요...")

    if selected_option:
        name = selected_option.split(' (')[0]
        code = str(selected_option.split(' (')[1][:-1]).zfill(6)
        
        if st.button("🚀 진단 시작"):
            with st.spinner(f"{name} ({code}) 데이터를 분석 중입니다..."):
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

                if not data_found:
                    realtime_inv = get_investor_data_realtime(code)
                    if realtime_inv['inst_net_buy_5d'] != 0 or realtime_inv['foreign_net_buy_5d'] != 0:
                        inv_data = realtime_inv
                
                df_stock = fdr.DataReader(code, datetime.now()-timedelta(days=400), datetime.now())
                
                if df_stock is not None and len(df_stock) > 100:
                    cfg = load_config()
                    sig = calculate_signals(df_stock, cfg)
                    result = score_stock(df_stock, sig, cfg, investor_data=inv_data)
                    
                    if result:
                        row = pd.Series(result)
                        row['name'] = name
                        row['code'] = code
                        row['sector'] = '기타' 
                        if df_scan is not None and not match.empty:
                            row['sector'] = match.iloc[0].get('sector', '기타')
                            
                        if inv_data:
                            row['foreign_consec_buy'] = inv_data['foreign_consecutive_buy']
                            row['inst_net_5d'] = inv_data['inst_net_buy_5d']
                        
                        display_stock_report(row, sector_df)
                    else:
                        st.error("점수 계산에 실패했습니다.")
                else:
                    st.error("종목 데이터를 가져올 수 없습니다. 신규 상장주거나 거래 정지 종목일 수 있습니다.")

elif mode == "🖼️ 차트 이미지 분석":
    st.title("🖼️ 차트 이미지 분석")
    st.info("📌 **총점 65점 이상만 매수대상** | 필수: 6개월 RS 70점 이상, 보조: 3개월 RS 65점 이상")
    st.caption("HTS/MTS 차트 이미지를 업로드하면 AI가 패턴을 분석하고 점수를 매깁니다.")
    
    uploaded_file = st.file_uploader("이미지 파일 업로드 (PNG, JPG)", type=['png', 'jpg', 'jpeg'])
    
    if uploaded_file:
        st.image(uploaded_file, caption="업로드된 차트", use_column_width=True)
        st.warning("이미지 분석 기능은 현재 서버 설정 확인이 필요합니다 (Tesseract OCR 등).")
        
        st.markdown("---")
        st.write("이미지 분석 대신 종목을 직접 선택하여 점수를 확인할 수 있습니다.")
        stock_list = get_krx_codes()
        opts = [f"{r['Name']} ({r['Code']})" for _, r in stock_list.iterrows()]
        sel = st.selectbox("종목 선택", opts)
        if st.button("분석 실행", key='img_btn'):
            pass
