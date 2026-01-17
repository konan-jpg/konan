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
    
    print(f"🔍 Chunk {chunk}: {len(stocks)}개 종목 스캔 시작 (인덱스 {start_i}~{end_i})")
    
    results = []
    end = datetime.now()
    start = end - timedelta(days=260)
    
    scanned_count = 0
    error_count = 0
    
    for idx, row in enumerate(stocks.itertuples(index=False), start=1):
        code = getattr(row, "Code", None)
        name = getattr(row, "Name", None)
        market = getattr(row, "Market", "")
        mktcap = getattr(row, "Marcap", None)
        
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
            
            news = analyze_stock_news(name, cfg)
            
            results.append({
                "code": code,
                "name": name,
                "market": market,
                **scored,
                **news,
                "scan_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "chunk": chunk,
            })
            
            print(f"✅ {name} ({code}): {scored.get('total_score', 0)}점")
            
            time.sleep(0.1)
            
        except Exception as e:
            error_count += 1
            if error_count <= 5:
                print(f"⚠️ {name} ({code}) 에러: {e}")
            continue
    
    print(f"\n📊 스캔 완료: 총 {scanned_count}개 검토, {len(results)}개 조건 충족, {error_count}개 에러")
    
    scan_day = datetime.now().strftime("%Y-%m-%d")
    os.makedirs("data/partial", exist_ok=True)
    output_file = f"data/partial/scanner_output_{scan_day}_chunk{chunk}.csv"
    
    if not results:
        print("⚠️ 조건에 맞는 종목이 없습니다. 빈 파일(헤더만) 생성합니다.")
        empty_df = pd.DataFrame(columns=[
            "rank", "code", "name", "market", "close", "total_score", 
            "trend_score", "vol_score", "momentum_score", "ma20", "ma60",
            "news_score", "news_summary", "scan_date", "chunk"
        ])
        empty_df.to_csv(output_file, index=False, encoding="utf-8-sig")
        return
    
    out = pd.DataFrame(results).sort_values("total_score", ascending=False)
    out.insert(0, "rank", range(1, len(out) + 1))
    out.to_csv(output_file, index=False, encoding="utf-8-sig")
    
    print(f"✅ 결과 저장 완료: {output_file} ({len(out)}개 종목)")

if __name__ == "__main__":
    main()
