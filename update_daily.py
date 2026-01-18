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
    """외국인/기관 투자자 데이터 조회 (pykrx)"""
    try:
        from pykrx import stock as pykrx
        
        end = datetime.now()
        start = end - timedelta(days=days + 10)
        
        df = pykrx.get_market_trading_value_by_date(
            start.strftime("%Y%m%d"),
            end.strftime("%Y%m%d"),
            code
        )
        
        if df is None or len(df) == 0:
            print(f"⚠️ {code}: 투자자 데이터 없음")
            return None
        
        df = df.tail(days)
        print(f"📊 {code} 컬럼: {list(df.columns)}")
        
        # 외국인 컬럼 찾기
        foreign_col = None
        for col_name in ["외국인합계", "외국인", "외국인순매수"]:
            if col_name in df.columns:
                foreign_col = col_name
                break
        if foreign_col is None and len(df.columns) > 2:
            foreign_col = df.columns[2]
        
        # 기관 컬럼 찾기
        inst_col = None
        for col_name in ["기관합계", "기관", "기관순매수"]:
            if col_name in df.columns:
                inst_col = col_name
                break
        if inst_col is None and len(df.columns) > 1:
            inst_col = df.columns[1]
        
        if foreign_col is None:
            print(f"⚠️ {code}: 외국인 컬럼 못 찾음")
            return None
        
        foreign_values = df[foreign_col].values
        
        consecutive_buy = 0
        for val in reversed(foreign_values):
            if val > 0:
                consecutive_buy += 1
            else:
                break
        
        foreign_net_5d = float(df[foreign_col].tail(5).sum()) if len(df) >= 5 else float(df[foreign_col].sum())
        inst_net_5d = float(df[inst_col].tail(5).sum()) if inst_col and len(df) >= 5 else 0
        
        print(f"✅ {code}: 외국인연속={consecutive_buy}, 외국인5d={foreign_net_5d/1e8:.1f}억")
        
        return {
            "foreign_consecutive_buy": consecutive_buy,
            "foreign_net_buy_5d": foreign_net_5d,
            "inst_net_buy_5d": inst_net_5d,
        }
        
    except Exception as e:
        print(f"❌ {code} 투자자 에러: {e}")
        return None

def main():
    cfg = load_config()
    stocks = get_stock_list(cfg)
    
    if stocks.empty:
        print("❌ 종목 리스트가 비어있습니다")
        return
    
    top_n = int(cfg["universe"]["top_n_stocks"])
    chunk_size = int(cfg["universe"]["chunk_size"])
    chunk = int(os.environ.get("SCAN_CHUNK", "1"))
    
    stocks = stocks.head(top_n)
    start_i = (chunk - 1) * chunk_size
    end_i = chunk * chunk_size
    stocks = stocks.iloc[start_i:end_i]
    
    print(f"🔍 Chunk {chunk}: {len(stocks)}개 종목 스캔")
    
    # 1단계: 기술적 스캔
    print("\n📊 [1단계] 기술적 스캔...")
    tech_results = []
    end = datetime.now()
    start = end - timedelta(days=400)
    
    scanned = 0
    for row in stocks.itertuples(index=False):
        code = getattr(row, "Code", None)
        name = getattr(row, "Name", None)
        market = getattr(row, "Market", "")
        mktcap = getattr(row, "Marcap", None)
        
        if not code or not name:
            continue
        
        scanned += 1
        if scanned % 20 == 0:
            print(f"진행: {scanned}/{len(stocks)}")
        
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
            
            if scored:
                tech_results.append({"code": code, "name": name, "market": market, "mktcap": mktcap, **scored})
            
            time.sleep(0.1)
        except:
            continue
    
    print(f"📊 [1단계 완료] {len(tech_results)}개 통과")
    
    if not tech_results:
        scan_day = datetime.now().strftime("%Y-%m-%d")
        os.makedirs("data/partial", exist_ok=True)
        pd.DataFrame().to_csv(f"data/partial/scanner_output_{scan_day}_chunk{chunk}.csv", index=False)
        return
    
    tech_df = pd.DataFrame(tech_results).sort_values("total_score", ascending=False)
    
    # 2단계: 수급 데이터
    top_candidates = cfg.get("investor", {}).get("top_candidates", 100)
    candidates = tech_df.head(top_candidates)
    
    print(f"\n💰 [2단계] 상위 {len(candidates)}개 수급 조회...")
    
    final_results = []
    for idx, row in candidates.iterrows():
        code, name = row["code"], row["name"]
        
        investor_data = get_investor_data(code)
        
        result = row.to_dict()
        if investor_data:
            supply_w = cfg.get("scoring", {}).get("supply_weight", 15)
            supply_score = 0
            
            fc = investor_data.get("foreign_consecutive_buy", 0)
            if fc >= 5: supply_score += 8
            elif fc >= 3: supply_score += 5
            elif fc >= 1: supply_score += 2
            
            if investor_data.get("inst_net_buy_5d", 0) > 0: supply_score += 4
            if investor_data.get("foreign_net_buy_5d", 0) > 0: supply_score += 3
            
            result["supply_score"] = min(supply_score, supply_w)
            result["total_score"] = row["trend_score"] + row["pattern_score"] + row["volume_score"] + result["supply_score"] + row["risk_score"]
            result["foreign_consec_buy"] = fc
            result["foreign_net_5d"] = investor_data.get("foreign_net_buy_5d", 0)
            result["inst_net_5d"] = investor_data.get("inst_net_buy_5d", 0)
        else:
            result["foreign_consec_buy"] = 0
            result["foreign_net_5d"] = 0
            result["inst_net_5d"] = 0
        
        news = analyze_stock_news(name, cfg)
        result.update(news)
        result["scan_date"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        result["chunk"] = chunk
        
        final_results.append(result)
        time.sleep(0.2)
    
    print(f"📊 [완료] {len(final_results)}개")
    
    scan_day = datetime.now().strftime("%Y-%m-%d")
    os.makedirs("data/partial", exist_ok=True)
    out = pd.DataFrame(final_results).sort_values("total_score", ascending=False)
    out.insert(0, "rank", range(1, len(out) + 1))
    out.to_csv(f"data/partial/scanner_output_{scan_day}_chunk{chunk}.csv", index=False, encoding="utf-8-sig")
    print(f"✅ 저장 완료")

if __name__ == "__main__":
    main()
