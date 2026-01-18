import os
import time
import yaml
import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
from scanner_core import calculate_signals, score_stock
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
        
        # Sector 정보가 없으면 여러 방법으로 가져오기 시도
        if "Sector" not in stocks.columns or stocks["Sector"].isna().all():
            sector_loaded = False
            
            # 방법 1: pykrx 라이브러리 사용 (가장 안정적)
            try:
                print("[INFO] pykrx에서 섹터 정보 가져오는 중...")
                from pykrx import stock as pykrx_stock
                
                # 오늘 또는 최근 영업일 기준
                today_str = datetime.now().strftime("%Y%m%d")
                
                sector_dict = {}
                # KOSPI 섹터
                try:
                    kospi_sectors = pykrx_stock.get_index_ticker_list(today_str, market="KOSPI")
                    for ticker in stocks[stocks["Market"] == "KOSPI"]["Code"].tolist()[:100]:  # 샘플
                        try:
                            info = pykrx_stock.get_market_sector_classifications(today_str, "KOSPI")
                            if ticker in info.index:
                                sector_dict[ticker] = info.loc[ticker, "업종명"] if "업종명" in info.columns else "기타"
                        except:
                            pass
                except:
                    pass
                
                if sector_dict:
                    stocks["Sector"] = stocks["Code"].map(sector_dict).fillna("기타")
                    sector_loaded = True
                    print(f"[OK] pykrx 섹터 로드: {stocks['Sector'].nunique()}개 업종")
            except Exception as e:
                print(f"[WARN] pykrx 실패: {e}")
            
            # 방법 2: KIND HTML 크롤링 (안정적)
            if not sector_loaded:
                try:
                    print("[INFO] KIND에서 섹터 정보 가져오는 중...")
                    krx_url = "http://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
                    krx_df = pd.read_html(krx_url, encoding='euc-kr')[0]
                    krx_df = krx_df[["종목코드", "업종"]]
                    krx_df.columns = ["Code", "Sector"]
                    krx_df["Code"] = krx_df["Code"].astype(str).str.zfill(6)
                    
                    if "Sector" in stocks.columns:
                        stocks = stocks.drop(columns=["Sector"])
                    stocks["Code"] = stocks["Code"].astype(str).str.zfill(6)
                    stocks = stocks.merge(krx_df, on="Code", how="left")
                    stocks["Sector"] = stocks["Sector"].fillna("기타")
                    sector_loaded = True
                    print(f"[OK] KIND HTML 섹터 로드: {stocks['Sector'].nunique()}개 업종")
                except Exception as e:
                    print(f"[WARN] KIND HTML 실패: {e}")
            
            # 방법 3: 네이버 금융 API (추가 백업)
            if not sector_loaded:
                try:
                    print("[INFO] 네이버 금융에서 섹터 정보 가져오는 중...")
                    import requests
                    
                    sector_map = {}
                    sample_codes = stocks["Code"].head(50).tolist()
                    
                    for code in sample_codes:
                        try:
                            url = f"https://m.stock.naver.com/api/stock/{code}/basic"
                            r = requests.get(url, timeout=3)
                            if r.status_code == 200:
                                data = r.json()
                                sector = data.get("industryCodeName", "기타")
                                sector_map[code] = sector
                            time.sleep(0.1)  # Rate limit
                        except:
                            continue
                    
                    if sector_map:
                        stocks["Sector"] = stocks["Code"].map(sector_map).fillna("기타")
                        sector_loaded = True
                        print(f"[OK] 네이버 API 섹터 로드: {len(sector_map)}개 종목")
                except Exception as e:
                    print(f"[WARN] 네이버 API 실패: {e}")
            
            # 실패 시 기본값
            if not sector_loaded:
                stocks["Sector"] = "기타"
                print("[WARN] 섹터 정보를 가져올 수 없어 '기타'로 설정")
        
        # Sector가 여전히 없으면 기본값
        if "Sector" not in stocks.columns:
            stocks["Sector"] = "기타"
            
        os.makedirs("data", exist_ok=True)
        stocks.to_csv("data/krx_backup.csv", index=False, encoding="utf-8-sig")
        return stocks
    except Exception as e:
        print(f"종목 리스트 로드 실패: {e}")
        try:
            return pd.read_csv("data/krx_backup.csv")
        except Exception:
            return pd.DataFrame()

def get_investor_data(code, days=10):
    """
    외국인/기관 투자자 데이터 조회 (다음 증권 API)
    pykrx, 네이버 금융 스크래핑이 작동하지 않아 다음 증권 API 사용
    """
    try:
        import requests
        
        url = f'https://finance.daum.net/api/investor/days?symbolCode=A{code}&page=1&perPage={days}'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://finance.daum.net'
        }
        
        r = requests.get(url, headers=headers, timeout=10)
        
        if r.status_code != 200:
            print(f"[WARN] {code}: HTTP {r.status_code}")
            return None
        
        result = r.json()
        data_list = result.get('data', [])
        
        if not data_list:
            print(f"[WARN] {code}: 데이터 없음")
            return None
        
        # 외국인 연속 매수일 계산 (최근부터)
        consecutive_buy = 0
        for d in data_list:
            foreign_vol = d.get('foreignStraightPurchaseVolume', 0) or 0
            if foreign_vol > 0:
                consecutive_buy += 1
            else:
                break
        
        # 5일 순매수 금액 합계 (거래량 * 종가)
        recent_5 = data_list[:5]
        foreign_net_5d = sum((d.get('foreignStraightPurchaseVolume', 0) or 0) * (d.get('tradePrice', 0) or 0) for d in recent_5)
        inst_net_5d = sum((d.get('institutionStraightPurchaseVolume', 0) or 0) * (d.get('tradePrice', 0) or 0) for d in recent_5)
        
        print(f"[OK] {code}: 외국인연속={consecutive_buy}, 외국인5d={foreign_net_5d:,.0f}, 기관5d={inst_net_5d:,.0f}")
        
        return {
            "foreign_consecutive_buy": consecutive_buy,
            "foreign_net_buy_5d": float(foreign_net_5d),
            "inst_net_buy_5d": float(inst_net_5d),
        }
        
    except Exception as e:
        print(f"[ERR] {code} 투자자 에러: {e}")
        return None

def calculate_sector_rankings(stocks, top_n=500):
    """
    시장 전체 주도 섹터 분석 (독립적 검증용)
    - 시총 상위 500개 종목을 대상으로 섹터별 평균 수익률 계산
    """
    print(f"\n[SECTOR] 시장 주도 섹터 분석 시작 (상위 {top_n}개 모집단)...")
    
    try:
        # 1. 모집단 선정 (시총 상위)
        universe = stocks.head(top_n).copy()
        
        # 2. 섹터별 그룹화 및 표본 추출 (각 섹터 대장주 5개)
        sector_groups = universe.groupby("Sector")
        
        sector_results = []
        end_date = datetime.now()
        start_date = end_date - timedelta(days=90) # 3개월 추세
        
        for sector, group in sector_groups:
            if len(group) < 3: # 너무 작은 섹터 제외
                continue
                
            # 섹터 내 시총 상위 5개만 표본으로 선정
            top_stocks = group.head(5)
            
            returns = []
            for _, row in top_stocks.iterrows():
                try:
                    df = fdr.DataReader(row["Code"], start_date, end_date)
                    if df is not None and len(df) > 20:
                        # 3개월 등락률
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
        
        # 3. 랭킹 산출 및 저장
        if sector_results:
            rank_df = pd.DataFrame(sector_results).sort_values("AvgReturn_3M", ascending=False)
            rank_df.insert(0, "Rank", range(1, len(rank_df) + 1))
            
            os.makedirs("data", exist_ok=True)
            rank_df.to_csv("data/sector_rankings.csv", index=False, encoding="utf-8-sig")
            print(f"[SECTOR] 섹터 랭킹 저장 완료: data/sector_rankings.csv (1위: {rank_df.iloc[0]['Sector']})")
        
    except Exception as e:
        print(f"[ERR] 섹터 분석 중 오류: {e}")

def main():
    cfg = load_config()
    stocks = get_stock_list(cfg)
    
    if stocks.empty:
        print("[ERR] 종목 리스트가 비어있습니다")
        return
    
    top_n = int(cfg["universe"]["top_n_stocks"])
    chunk_size = int(cfg["universe"]["chunk_size"])
    chunk = int(os.environ.get("SCAN_CHUNK", "1"))
    
    stocks = stocks.head(top_n)
    start_i = (chunk - 1) * chunk_size
    end_i = chunk * chunk_size
    stocks = stocks.iloc[start_i:end_i]
    
    print(f"[SCAN] Chunk {chunk}: {len(stocks)}개 종목 스캔 시작 (인덱스 {start_i}~{end_i})")
    
    # === 0단계: 주도 섹터 분석 (독립 검증용) ===
    # 첫 번째 청크 실행 시에만 수행 (중복 방지)
    if chunk == 1:
        calculate_sector_rankings(stocks)

    # === 1단계: 기술적 스캔 ===
    print("\n[STEP1] 기술적 스캔 시작...")
    tech_results = []
    end = datetime.now()
    start = end - timedelta(days=400)
    
    scanned_count = 0
    error_count = 0
    
    for idx, row in enumerate(stocks.itertuples(index=False), start=1):
        code = getattr(row, "Code", None)
        name = getattr(row, "Name", None)
        market = getattr(row, "Market", "")
        mktcap = getattr(row, "Marcap", None)
        sector = getattr(row, "Sector", "Unknown")
        
        if not code or not name:
            continue
        
        scanned_count += 1
        if scanned_count % 10 == 0:
            print(f"진행중: {scanned_count}/{len(stocks)} ({name})")
        
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
            error_count += 1
            if error_count <= 5:
                print(f"[WARN] {name} ({code}) 에러: {e}")
            continue
    
    print(f"\n[STEP1 DONE] 총 {scanned_count}개 검토, {len(tech_results)}개 기술적 조건 충족")
    
    if not tech_results:
        print("[WARN] 조건에 맞는 종목이 없습니다.")
        scan_day = datetime.now().strftime("%Y-%m-%d")
        os.makedirs("data/partial", exist_ok=True)
        output_file = f"data/partial/scanner_output_{scan_day}_chunk{chunk}.csv"
        empty_df = pd.DataFrame(columns=[
            "rank", "code", "name", "market", "sector", "close", "total_score", 
            "trend_score", "pattern_score", "volume_score", "supply_score", "risk_score",
            "setup", "ma20", "ma60", "scan_date", "chunk"
        ])
        empty_df.to_csv(output_file, index=False, encoding="utf-8-sig")
        return
    
    # 기술적 점수로 정렬
    tech_df = pd.DataFrame(tech_results).sort_values("total_score", ascending=False)
    
    # === 2단계: 수급 데이터 조회 (상위 후보만) ===
    top_candidates = cfg.get("investor", {}).get("top_candidates", 100)
    candidates = tech_df.head(top_candidates)
    
    print(f"\n[STEP2] 상위 {len(candidates)}개 종목 수급 데이터 조회...")
    
    final_results = []
    for idx, row in candidates.iterrows():
        code = row["code"]
        name = row["name"]
        
        # 투자자 데이터 조회
        investor_data = get_investor_data(code)
        
        if investor_data:
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
            new_total = row["trend_score"] + row["pattern_score"] + row["volume_score"] + supply_score + row["risk_score"]
            
            result = row.to_dict()
            result["supply_score"] = supply_score
            result["total_score"] = new_total
            result["foreign_consec_buy"] = foreign_consec
            result["foreign_net_5d"] = investor_data.get("foreign_net_buy_5d", 0)
            result["inst_net_5d"] = investor_data.get("inst_net_buy_5d", 0)
        else:
            result = row.to_dict()
            result["foreign_consec_buy"] = 0
            result["foreign_net_5d"] = 0
            result["inst_net_5d"] = 0
        
        # 뉴스 분석
        news = analyze_stock_news(name, cfg)
        result.update(news)
        result["scan_date"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        result["chunk"] = chunk
        
        final_results.append(result)
        
        print(f"[OK] {name} ({code}): {result['total_score']:.0f}점 (수급: {result.get('supply_score', 0):.0f})")
        
        time.sleep(0.2)  # API 부하 방지
    
    print(f"\n[STEP2 DONE] {len(final_results)}개 종목 최종 점수 계산 완료")
    
    # 결과 저장
    scan_day = datetime.now().strftime("%Y-%m-%d")
    os.makedirs("data/partial", exist_ok=True)
    output_file = f"data/partial/scanner_output_{scan_day}_chunk{chunk}.csv"
    
    out = pd.DataFrame(final_results).sort_values("total_score", ascending=False)
    out.insert(0, "rank", range(1, len(out) + 1))
    out.to_csv(output_file, index=False, encoding="utf-8-sig")
    
    print(f"[OK] 결과 저장 완료: {output_file} ({len(out)}개 종목)")

if __name__ == "__main__":
    main()
