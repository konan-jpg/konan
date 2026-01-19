# (앞부분 생략: get_investor_data 등 기존 함수 유지)
def main():
    cfg = load_config()
    stocks = get_stock_list(cfg) # 1단계: 목록 확보 (실패시 백업사용)
    
    # 2단계: 조각 스캔 (Chunk)
    chunk = int(os.environ.get("SCAN_CHUNK", "1"))
    chunk_stocks = stocks.head(1000).iloc[(chunk-1)*500 : chunk*500]
    
    results = []
    for row in chunk_stocks.itertuples():
        df = fdr.DataReader(row.Code, datetime.now()-timedelta(days=400))
        if df is None or len(df) < 100: continue
        
        # 수급 데이터 수집
        investor = get_investor_data(row.Code)
        sig = calculate_signals(df, cfg)
        res = score_stock(df, sig, cfg, investor_data=investor)
        
        if res:
            res.update({'code': row.Code, 'name': row.Name, 'sector': getattr(row, 'Sector', '기타')})
            # 수급 데이터 결과에 매핑 (app.py 표시용)
            res.update({
                'foreign_consec_buy': investor['foreign_consecutive_buy'],
                'foreign_net_5d': investor['foreign_net_buy_5d'],
                'inst_net_5d': investor['inst_net_buy_5d']
            })
            results.append(res)
        time.sleep(0.2) # 차단 방지

    # 3단계: 조각 파일 저장 (통합은 Workflow에서 수행하거나 아래에 추가)
    os.makedirs("data/partial", exist_ok=True)
    pd.DataFrame(results).to_csv(f"data/partial/scanner_output_{datetime.now().date()}_chunk{chunk}.csv", index=False)

# [중요] 3단계 보완: 데이터 통합 함수 추가
def merge_results():
    files = glob.glob("data/partial/scanner_output*chunk*.csv")
    full_df = pd.concat([pd.read_csv(f) for f in files]).drop_duplicates(subset=['code'])
    full_df.to_csv(f"data/scanner_output_{datetime.now().date()}.csv", index=False)
    full_df.to_csv("data/scanner_output_latest.csv", index=False)
