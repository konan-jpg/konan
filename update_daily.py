# -*- coding: utf-8 -*-
"""
update_daily.py - 매일 주식 스캐너 실행 스크립트
GitHub Actions에서 실행되어 수급 데이터를 포함한 스캔 결과를 저장합니다.
"""
import os
import time
import json
import yaml
import pandas as pd
import requests
import FinanceDataReader as fdr
from datetime import datetime, timedelta
from scanner_core import calculate_signals, score_stock, calculate_strategies
from news_analyzer import analyze_stock_news


def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_stock_list(cfg):
    try:
        kospi = fdr.StockListing("KOSPI")
        kosdaq = fdr.StockListing("KOSDAQ")
        stocks = pd.concat([kospi, kosdaq], ignore_index=True)
        stocks = stocks[~stocks["Name"].str.contains("우|스팩", na=False, regex=True)]
        if "Marcap" in stocks.columns:
            stocks = stocks[stocks["Marcap"] >= cfg["universe"]["min_mktcap_krw"]]
            stocks = stocks.sort_values("Marcap", ascending=False)
        
        # Sector 정보 확인 및 매핑 (KRX-DESC 사용)
        has_valid_sector = False
        if "Sector" in stocks.columns:
            if stocks["Sector"].notna().any():
                has_valid_sector = True
        
        if not has_valid_sector:
            try:
                # KRX-DESC에서 섹터(Industry) 가져오기
                krx_desc = fdr.StockListing("KRX-DESC")
                if krx_desc is not None and "Industry" in krx_desc.columns:
                    sector_map = dict(zip(krx_desc["Code"].astype(str).str.zfill(6), krx_desc["Industry"]))
                    stocks["Sector"] = stocks["Code"].astype(str).str.zfill(6).map(sector_map)
                    print(f"[INFO] KRX-DESC 섹터 정보 매핑 완료: {stocks['Sector'].notna().sum()}개")
                elif krx_desc is not None and "Sector" in krx_desc.columns:
                    sector_map = dict(zip(krx_desc["Code"].astype(str).str.zfill(6), krx_desc["Sector"]))
                    stocks["Sector"] = stocks["Code"].astype(str).str.zfill(6).map(sector_map)
                    print(f"[INFO] KRX-DESC Sector 매핑 완료: {stocks['Sector'].notna().sum()}개")
            except Exception as e:
                print(f"[WARN] 섹터 정보 가져오기 실패: {e}")
        
        # Sector 컬럼이 없으면 생성, 있으면 NA만 채우기
        if "Sector" not in stocks.columns:
            stocks["Sector"] = "기타"
        else:
            stocks["Sector"] = stocks["Sector"].fillna("기타")
        
        stocks["Code"] = stocks["Code"].astype(str).str.zfill(6)
        os.makedirs("data", exist_ok=True)
        stocks.to_csv("data/krx_backup.csv", index=False, encoding="utf-8-sig")
        return stocks
    except Exception as e:
        print(f"[ERR] 종목 리스트 로드 실패: {e}")
        try:
            return pd.read_csv("data/krx_backup.csv")
        except:
            return pd.DataFrame()


def check_index_above_ma20():
    """코스피 지수가 20일선 위에 있는지 확인"""
    try:
        now = get_kst_now()
        end = now + timedelta(days=1)
        start = now - timedelta(days=60)
        kospi = fdr.DataReader("KS11", start, end)  # 코스피 지수
        if kospi is not None and len(kospi) >= 20:
            ma20 = kospi["Close"].rolling(20).mean().iloc[-1]
            close = kospi["Close"].iloc[-1]
            above = close > ma20
            print(f"[INDEX] 코스피 {close:.0f} vs MA20 {ma20:.0f} → {'위' if above else '아래'}")
            return above
    except Exception as e:
        print(f"[WARN] 지수 확인 실패: {e}")
    return True  # 기본값: 20일선 위로 가정 (보수적)


def get_investor_data(code, days=10, max_retries=3):
    """외국인/기관 투자자 데이터 조회 (안정화 버전)"""
    code = str(code).zfill(6)
    
    # 방법 1: 네이버 금융 (우선)
    for attempt in range(max_retries):
        try:
            url = f"https://finance.naver.com/item/frgn.naver?code={code}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Referer': 'https://finance.naver.com/',
            }
            session = requests.Session()
            r = session.get(url, headers=headers, timeout=15)
            r.raise_for_status()
            dfs = pd.read_html(r.text, encoding='cp949')
            target_df = None
            for df in dfs:
                cols_str = ' '.join(str(c) for c in df.columns)
                if '기관' in cols_str or '외국인' in cols_str:
                    target_df = df
                    break
            if target_df is None and len(dfs) >= 2:
                target_df = dfs[1]
            if target_df is not None:
                df_clean = target_df.dropna(how='all').head(10)
                foreign_sum, inst_sum, consecutive_buy = 0, 0, 0
                frgn_col, inst_col, price_col = None, None, None
                for col in df_clean.columns:
                    col_str = str(col).lower()
                    if '외국인' in col_str and frgn_col is None: frgn_col = col
                    if '기관' in col_str and inst_col is None: inst_col = col
                    if '종가' in col_str and price_col is None: price_col = col
                count, consecutive_counting = 0, True
                for _, data_row in df_clean.iterrows():
                    if count >= 5: break
                    try:
                        price = 1
                        if price_col:
                            ps = str(data_row[price_col]).replace(',', '').replace('+', '').replace('-', '')
                            if ps and ps != 'nan': price = float(ps)
                        if frgn_col:
                            fv = str(data_row[frgn_col]).replace(',', '').replace('+', '')
                            if fv and fv != 'nan':
                                fn = float(fv)
                                foreign_sum += fn * price
                                if consecutive_counting and fn > 0: consecutive_buy += 1
                                else: consecutive_counting = False
                        if inst_col:
                            iv = str(data_row[inst_col]).replace(',', '').replace('+', '')
                            if iv and iv != 'nan': inst_sum += float(iv) * price
                        count += 1
                    except: continue
                if count > 0:
                    print(f"[OK] {code} Naver: 외국인연속={consecutive_buy}, 외국인5d={foreign_sum/1e8:.1f}억")
                    return {"foreign_consecutive_buy": consecutive_buy, "foreign_net_buy_5d": float(foreign_sum), "inst_net_buy_5d": float(inst_sum)}
        except requests.exceptions.RequestException as e:
            print(f"[WARN] {code} Naver 시도 {attempt+1}/{max_retries} 실패: {e}")
            if attempt < max_retries - 1: time.sleep(1)
            continue
        except Exception as e:
            print(f"[WARN] {code} Naver 파싱 오류: {e}")
            break
    
    # 방법 2: Daum API (백업)
    for attempt in range(max_retries):
        try:
            url = f'https://finance.daum.net/api/investor/days?symbolCode=A{code}&page=1&perPage={days}'
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'ko-KR,ko;q=0.9',
                'Referer': f'https://finance.daum.net/quotes/A{code}',
                'Origin': 'https://finance.daum.net',
            }
            session = requests.Session()
            session.get(f'https://finance.daum.net/quotes/A{code}', headers=headers, timeout=5)
            time.sleep(0.3)
            r = session.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data_list = r.json().get('data', [])
                if data_list:
                    consecutive_buy = 0
                    for d in data_list:
                        vol = d.get('foreignStraightPurchaseVolume', 0) or 0
                        if vol > 0: consecutive_buy += 1
                        else: break
                    recent_5 = data_list[:5]
                    foreign_net = sum((d.get('foreignStraightPurchaseVolume', 0) or 0) * (d.get('tradePrice', 0) or 0) for d in recent_5)
                    inst_net = sum((d.get('institutionStraightPurchaseVolume', 0) or 0) * (d.get('tradePrice', 0) or 0) for d in recent_5)
                    print(f"[OK] {code} Daum: 외국인연속={consecutive_buy}")
                    return {"foreign_consecutive_buy": consecutive_buy, "foreign_net_buy_5d": float(foreign_net), "inst_net_buy_5d": float(inst_net)}
        except requests.exceptions.RequestException as e:
            print(f"[WARN] {code} Daum 시도 {attempt+1}/{max_retries} 실패: {e}")
            if attempt < max_retries - 1: time.sleep(1)
            continue
        except Exception as e:
            print(f"[WARN] {code} Daum 파싱 오류: {e}")
            break
    
    print(f"[WARN] {code} 수급 데이터 없음")
    return {"foreign_consecutive_buy": 0, "foreign_net_buy_5d": 0.0, "inst_net_buy_5d": 0.0}


def get_kst_now():
    """한국 시간(KST) 반환"""
    return datetime.utcnow() + timedelta(hours=9)

def calculate_sector_rankings(stocks, top_n=500):
    print(f"\n[SECTOR] 섹터 분석 시작...")
    try:
        universe = stocks.head(top_n).copy()
        sector_groups = universe.groupby("Sector")
        sector_results = []
        # KST 기준 시간 설정
        now = get_kst_now()
        end_date = now + timedelta(days=1)
        start_date = now - timedelta(days=90)
        
        for sector, group in sector_groups:
            if len(group) < 3: continue
            returns = []
            for _, row in group.head(5).iterrows():
                try:
                    df = fdr.DataReader(row["Code"], start_date, end_date)
                    if df is not None and len(df) > 20:
                        returns.append((df["Close"].iloc[-1] / df["Close"].iloc[0] - 1) * 100)
                except: continue
            if returns:
                sector_results.append({"Sector": sector, "AvgReturn_3M": sum(returns)/len(returns), "StockCount": len(group)})
        if sector_results:
            rank_df = pd.DataFrame(sector_results).sort_values("AvgReturn_3M", ascending=False)
            rank_df.insert(0, "Rank", range(1, len(rank_df) + 1))
            os.makedirs("data", exist_ok=True)
            rank_df.to_csv("data/sector_rankings.csv", index=False, encoding="utf-8-sig")
            print(f"[SECTOR] 완료: 1위={rank_df.iloc[0]['Sector']}")
    except Exception as e:
        print(f"[ERR] 섹터 오류: {e}")


def main():
    cfg = load_config()
    stocks = get_stock_list(cfg)
    if stocks.empty:
        print("[ERR] 종목 없음")
        return
    top_n = int(cfg["universe"]["top_n_stocks"])
    chunk_size = int(cfg["universe"]["chunk_size"])
    chunk = int(os.environ.get("SCAN_CHUNK", "1"))
    all_top = stocks.head(top_n).copy()
    start_i, end_i = (chunk - 1) * chunk_size, chunk * chunk_size
    chunk_stocks = all_top.iloc[start_i:end_i]
    print(f"[SCAN] Chunk {chunk}: {len(chunk_stocks)}개")
    if chunk == 1:
        calculate_sector_rankings(all_top)
    
    # 지수 20일선 상태 확인 (리스크 점수 계산용)
    index_above_ma20 = check_index_above_ma20()
    
    print("\n[STEP1] 기술적 스캔...")
    tech_results = []
    
    # KST 기준 시간 설정
    now = get_kst_now()
    end = now + timedelta(days=1) # 내일까지로 설정하여 당일 데이터 포함 보장
    start = now - timedelta(days=400)
    
    for idx, row in enumerate(chunk_stocks.itertuples(index=False), start=1):
        code = str(getattr(row, "Code", "")).zfill(6)
        name = getattr(row, "Name", "")
        market = getattr(row, "Market", "")
        mktcap = getattr(row, "Marcap", None)
        sector = getattr(row, "Sector", "기타")
        if not code or not name: continue
        if idx % 20 == 0: print(f"  {idx}/{len(chunk_stocks)}")
        try:
            df = fdr.DataReader(code, start, end)
            if df is None or len(df) < 200: continue
            if float(df["Volume"].tail(5).sum()) == 0: continue
            if float(df["Close"].iloc[-1]) < cfg["universe"]["min_close"]: continue
            sig = calculate_signals(df, cfg)
            scored = score_stock(df, sig, cfg, mktcap=mktcap, index_above_ma20=index_above_ma20)
            if scored is None: continue
            
            # 전략 계산 추가
            strat_result = calculate_strategies(df, sig, cfg)
            if strat_result:
                # 전략 정보를 scored에 병합 (strategies 리스트 제외, flat 필드만)
                for k, v in strat_result.items():
                    if k != 'strategies':
                        scored[k] = v
            
            # score_details를 JSON 문자열로 변환
            if 'score_details' in scored and isinstance(scored['score_details'], dict):
                scored['score_details'] = json.dumps(scored['score_details'], ensure_ascii=False)
            tech_results.append({"code": code, "name": name, "market": market, "mktcap": mktcap, "sector": sector, **scored})
            time.sleep(0.1)
        except: continue
    print(f"[STEP1] {len(tech_results)}개 통과")
    if not tech_results:
        scan_day = get_kst_now().strftime("%Y-%m-%d")
        os.makedirs("data/partial", exist_ok=True)
        pd.DataFrame().to_csv(f"data/partial/scanner_output_{scan_day}_chunk{chunk}.csv", index=False)
        return
    tech_df = pd.DataFrame(tech_results).sort_values("total_score", ascending=False)
    
    top_candidates = cfg.get("investor", {}).get("top_candidates", 100)
    candidates = tech_df.head(top_candidates)
    print(f"\n[STEP2] 상위 {len(candidates)}개 수급 조회...")
    final_results = []
    for _, row in candidates.iterrows():
        code, name = row["code"], row["name"]
        inv = get_investor_data(code)
        supply_score = 0
        supply_w = cfg.get("scoring", {}).get("supply_weight", 15)
        fc = inv.get("foreign_consecutive_buy", 0)
        if fc >= 5: supply_score += 8
        elif fc >= 3: supply_score += 5
        elif fc >= 1: supply_score += 2
        if inv.get("inst_net_buy_5d", 0) > 0: supply_score += 4
        if inv.get("foreign_net_buy_5d", 0) > 0: supply_score += 3
        supply_score = min(supply_score, supply_w)
        new_total = row["trend_score"] + row["pattern_score"] + row["volume_score"] + supply_score + row["risk_score"]
        result = row.to_dict()
        result.update({
            "supply_score": supply_score, "total_score": new_total,
            "foreign_consec_buy": fc,
            "foreign_net_5d": inv.get("foreign_net_buy_5d", 0),
            "inst_net_5d": inv.get("inst_net_buy_5d", 0),
            "scan_date": get_kst_now().strftime("%Y-%m-%d %H:%M"),
            "chunk": chunk
        })
        news = analyze_stock_news(name, cfg)
        result.update(news)
        final_results.append(result)
        print(f"  [OK] {name}: {new_total:.0f}점 (수급:{supply_score})")
        time.sleep(0.2)
    print(f"\n[STEP2] {len(final_results)}개 완료")
    scan_day = get_kst_now().strftime("%Y-%m-%d")
    os.makedirs("data/partial", exist_ok=True)
    out = pd.DataFrame(final_results).sort_values("total_score", ascending=False)
    out.insert(0, "rank", range(1, len(out) + 1))
    out.to_csv(f"data/partial/scanner_output_{scan_day}_chunk{chunk}.csv", index=False, encoding="utf-8-sig")
    print(f"[완료] 저장됨 ({len(out)}개)")


if __name__ == "__main__":
    main()
