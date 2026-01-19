# -*- coding: utf-8 -*-
"""
update_daily.py - 매일 주식 스캐너 실행 스크립트
GitHub Actions에서 실행되어 수급 데이터를 포함한 스캔 결과를 저장합니다.
"""
import os
import time
import yaml
import pandas as pd
import requests
import FinanceDataReader as fdr
from datetime import datetime, timedelta
from scanner_core import calculate_signals, score_stock
from news_analyzer import analyze_stock_news


def load_config():
    """설정 파일 로드"""
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_stock_list(cfg):
    """종목 리스트 가져오기 (KOSPI + KOSDAQ)"""
    try:
        kospi = fdr.StockListing("KOSPI")
        kosdaq = fdr.StockListing("KOSDAQ")
        stocks = pd.concat([kospi, kosdaq], ignore_index=True)
        stocks = stocks[~stocks["Name"].str.contains("우|스팩", na=False, regex=True)]
        
        if "Marcap" in stocks.columns:
            stocks = stocks[stocks["Marcap"] >= cfg["universe"]["min_mktcap_krw"]]
            stocks = stocks.sort_values("Marcap", ascending=False)
        
        if "Sector" not in stocks.columns or stocks["Sector"].isna().all():
            stocks["Sector"] = "기타"
        
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


def get_investor_data(code, days=10):
    """
    외국인/기관 투자자 데이터 조회
    1순위: Daum API (로컬에서 잘 작동)
    2순위: 네이버 금융 크롤링 (GitHub Actions 등 서버에서 사용)
    """
    code = str(code).zfill(6)
    
    # ========== 방법 1: Daum API ==========
    try:
        url = f'https://finance.daum.net/api/investor/days?symbolCode=A{code}&page=1&perPage={days}'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Referer': 'https://finance.daum.net'
        }
        r = requests.get(url, headers=headers, timeout=8)
        
        if r.status_code == 200:
            data_list = r.json().get('data', [])
            if data_list:
                # 외국인 연속 매수일 계산
                consecutive_buy = 0
                for d in data_list:
                    vol = d.get('foreignStraightPurchaseVolume', 0) or 0
                    if vol > 0:
                        consecutive_buy += 1
                    else:
                        break
                
                # 5일 순매수 금액
                recent_5 = data_list[:5]
                foreign_net_5d = sum(
                    (d.get('foreignStraightPurchaseVolume', 0) or 0) * (d.get('tradePrice', 0) or 0)
                    for d in recent_5
                )
                inst_net_5d = sum(
                    (d.get('institutionStraightPurchaseVolume', 0) or 0) * (d.get('tradePrice', 0) or 0)
                    for d in recent_5
                )
                
                print(f"[OK] {code} Daum: 외국인연속={consecutive_buy}, 외국인5d={foreign_net_5d/1e8:.1f}억")
                return {
                    "foreign_consecutive_buy": consecutive_buy,
                    "foreign_net_buy_5d": float(foreign_net_5d),
                    "inst_net_buy_5d": float(inst_net_5d),
                }
    except Exception as e:
        print(f"[WARN] {code} Daum 실패: {e}")
    
    # ========== 방법 2: 네이버 금융 크롤링 ==========
    try:
        naver_url = f"https://finance.naver.com/item/frgn.naver?code={code}"
        headers_naver = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        r = requests.get(naver_url, headers=headers_naver, timeout=8)
        
        # pandas로 테이블 읽기
        dfs = pd.read_html(r.text, encoding='cp949')
        
        # 외국인/기관 데이터가 있는 테이블 찾기
        target_df = None
        for df in dfs:
            cols_str = ' '.join(str(c) for c in df.columns)
            if '기관' in cols_str or '외국인' in cols_str:
                target_df = df
                break
        
        if target_df is None and len(dfs) >= 2:
            target_df = dfs[1]
        
        if target_df is not None:
            # 결측치 제거 후 최근 5일
            df = target_df.dropna(how='all').head(7)
            
            foreign_sum = 0
            inst_sum = 0
            
            # 컬럼 찾기
            frgn_col = None
            inst_col = None
            price_col = None
            
            for col in df.columns:
                col_str = str(col)
                if '외국인' in col_str and frgn_col is None:
                    frgn_col = col
                if '기관' in col_str and inst_col is None:
                    inst_col = col
                if '종가' in col_str and price_col is None:
                    price_col = col
            
            # 데이터 파싱
            count = 0
            for _, row in df.iterrows():
                if count >= 5:
                    break
                try:
                    price = 1
                    if price_col:
                        price = float(str(row[price_col]).replace(',', '').replace('+', '').replace('-', ''))
                    
                    if frgn_col:
                        frgn_val = str(row[frgn_col]).replace(',', '').replace('+', '')
                        if frgn_val and frgn_val != 'nan':
                            foreign_sum += float(frgn_val) * price
                    
                    if inst_col:
                        inst_val = str(row[inst_col]).replace(',', '').replace('+', '')
                        if inst_val and inst_val != 'nan':
                            inst_sum += float(inst_val) * price
                    
                    count += 1
                except:
                    continue
            
            print(f"[OK] {code} Naver: 외국인5d={foreign_sum/1e8:.1f}억, 기관5d={inst_sum/1e8:.1f}억")
            return {
                "foreign_consecutive_buy": 0,
                "foreign_net_buy_5d": float(foreign_sum),
                "inst_net_buy_5d": float(inst_sum),
            }
            
    except Exception as e:
        print(f"[WARN] {code} Naver 실패: {e}")
    
    # ========== 모두 실패 시 기본값 ==========
    print(f"[WARN] {code} 수급 데이터 없음 - 기본값 사용")
    return {
        "foreign_consecutive_buy": 0,
        "foreign_net_buy_5d": 0.0,
        "inst_net_buy_5d": 0.0,
    }


def calculate_sector_rankings(stocks, top_n=500):
    """섹터 랭킹 계산"""
    print(f"\n[SECTOR] 시장 주도 섹터 분석 시작...")
    try:
        universe = stocks.head(top_n).copy()
        sector_groups = universe.groupby("Sector")
        sector_results = []
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=90)
        
        for sector, group in sector_groups:
            if len(group) < 3:
                continue
            
            top_stocks = group.head(5)
            returns = []
            
            for _, row in top_stocks.iterrows():
                try:
                    df = fdr.DataReader(row["Code"], start_date, end_date)
                    if df is not None and len(df) > 20:
                        ret = (df["Close"].iloc[-1] / df["Close"].iloc[0] - 1) * 100
                        returns.append(ret)
                except:
                    continue
            
            if returns:
                avg_return = sum(returns) / len(returns)
                sector_results.append({
                    "Sector": sector,
                    "AvgReturn_3M": avg_return,
                    "StockCount": len(group)
                })
        
        if sector_results:
            rank_df = pd.DataFrame(sector_results).sort_values("AvgReturn_3M", ascending=False)
            rank_df.insert(0, "Rank", range(1, len(rank_df) + 1))
            os.makedirs("data", exist_ok=True)
            rank_df.to_csv("data/sector_rankings.csv", index=False, encoding="utf-8-sig")
            print(f"[SECTOR] 랭킹 저장 완료: 1위 = {rank_df.iloc[0]['Sector']}")
            
    except Exception as e:
        print(f"[ERR] 섹터 분석 오류: {e}")


def main():
    """메인 실행 함수"""
    cfg = load_config()
    stocks = get_stock_list(cfg)
    
    if stocks.empty:
        print("[ERR] 종목 리스트가 비어있습니다")
        return
    
    top_n = int(cfg["universe"]["top_n_stocks"])
    chunk_size = int(cfg["universe"]["chunk_size"])
    chunk = int(os.environ.get("SCAN_CHUNK", "1"))
    
    all_top_stocks = stocks.head(top_n).copy()
    
    # 청크 분할
    start_i = (chunk - 1) * chunk_size
    end_i = chunk * chunk_size
    chunk_stocks = all_top_stocks.iloc[start_i:end_i]
    
    print(f"[SCAN] Chunk {chunk}: {len(chunk_stocks)}개 종목 스캔 시작")
    
    # 첫 번째 청크일 때만 섹터 분석
    if chunk == 1:
        calculate_sector_rankings(all_top_stocks)
    
    # ===== 1단계: 기술적 스캔 =====
    print("\n[STEP1] 기술적 스캔...")
    tech_results = []
    end = datetime.now()
    start = end - timedelta(days=400)
    
    for idx, row in enumerate(chunk_stocks.itertuples(index=False), start=1):
        code = str(getattr(row, "Code", "")).zfill(6)
        name = getattr(row, "Name", "")
        market = getattr(row, "Market", "")
        mktcap = getattr(row, "Marcap", None)
        sector = getattr(row, "Sector", "기타")
        
        if not code or not name:
            continue
        
        if idx % 20 == 0:
            print(f"  진행중: {idx}/{len(chunk_stocks)}")
        
        try:
            df = fdr.DataReader(code, start, end)
            if df is None or len(df) < 200:
                continue
            
            if float(df["Volume"].tail(5).sum()) == 0:
                continue
            
            if float(df["Close"].iloc[-1]) < cfg["universe"]["min_close"]:
                continue
            
            sig = calculate_signals(df, cfg)
            scored = score_stock(df, sig, cfg, mktcap=mktcap)
            
            if scored is None:
                continue
            
            tech_results.append({
                "code": code,
                "name": name,
                "market": market,
                "mktcap": mktcap,
                "sector": sector,
                **scored,
            })
            
            time.sleep(0.1)
            
        except Exception as e:
            continue
    
    print(f"[STEP1 완료] {len(tech_results)}개 기술적 조건 충족")
    
    if not tech_results:
        print("[WARN] 조건에 맞는 종목이 없습니다.")
        scan_day = datetime.now().strftime("%Y-%m-%d")
        os.makedirs("data/partial", exist_ok=True)
        pd.DataFrame().to_csv(f"data/partial/scanner_output_{scan_day}_chunk{chunk}.csv", index=False)
        return
    
    # 기술적 점수로 정렬
    tech_df = pd.DataFrame(tech_results).sort_values("total_score", ascending=False)
    
    # ===== 2단계: 수급 데이터 조회 =====
    top_candidates = cfg.get("investor", {}).get("top_candidates", 100)
    candidates = tech_df.head(top_candidates)
    
    print(f"\n[STEP2] 상위 {len(candidates)}개 종목 수급 데이터 조회...")
    
    final_results = []
    for idx, row in candidates.iterrows():
        code = row["code"]
        name = row["name"]
        
        # 투자자 데이터 조회
        investor_data = get_investor_data(code)
        
        # 수급 점수 재계산
        supply_score = 0
        supply_w = cfg.get("scoring", {}).get("supply_weight", 15)
        
        foreign_consec = investor_data.get("foreign_consecutive_buy", 0)
        if foreign_consec >= 5:
            supply_score += 8
        elif foreign_consec >= 3:
            supply_score += 5
        elif foreign_consec >= 1:
            supply_score += 2
        
        if investor_data.get("inst_net_buy_5d", 0) > 0:
            supply_score += 4
        if investor_data.get("foreign_net_buy_5d", 0) > 0:
            supply_score += 3
        
        supply_score = min(supply_score, supply_w)
        
        # 총점 업데이트
        new_total = (
            row["trend_score"] + 
            row["pattern_score"] + 
            row["volume_score"] + 
            supply_score + 
            row["risk_score"]
        )
        
        result = row.to_dict()
        result["supply_score"] = supply_score
        result["total_score"] = new_total
        result["foreign_consec_buy"] = foreign_consec
        result["foreign_net_5d"] = investor_data.get("foreign_net_buy_5d", 0)
        result["inst_net_5d"] = investor_data.get("inst_net_buy_5d", 0)
        
        # 뉴스 분석
        news = analyze_stock_news(name, cfg)
        result.update(news)
        result["scan_date"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        result["chunk"] = chunk
        
        final_results.append(result)
        
        print(f"  [OK] {name}: {result['total_score']:.0f}점 (수급: {supply_score})")
        
        time.sleep(0.2)
    
    print(f"\n[STEP2 완료] {len(final_results)}개 종목 최종 점수 계산 완료")
    
    # 결과 저장
    scan_day = datetime.now().strftime("%Y-%m-%d")
    os.makedirs("data/partial", exist_ok=True)
    output_file = f"data/partial/scanner_output_{scan_day}_chunk{chunk}.csv"
    
    out = pd.DataFrame(final_results).sort_values("total_score", ascending=False)
    out.insert(0, "rank", range(1, len(out) + 1))
    out.to_csv(output_file, index=False, encoding="utf-8-sig")
    
    print(f"[완료] 결과 저장: {output_file} ({len(out)}개 종목)")


if __name__ == "__main__":
    main()
