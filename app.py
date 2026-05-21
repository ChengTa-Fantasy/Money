import os
import yfinance as yf
import pandas as pd
import requests
from flask import Flask, request
import google.generativeai as genai
from datetime import datetime, timedelta
import traceback

app = Flask(__name__)

def get_technical_data(stock_id):
    try:
        ticker = stock_id if not stock_id.isdigit() else f"{stock_id}.TW"
        stock = yf.Ticker(ticker)
        df_daily = stock.history(period="5d", interval="1d")
        
        if len(df_daily) >= 2:
            prev_day = df_daily.iloc[-2] if len(df_daily) > 1 else df_daily.iloc[-1]
            prev_high, prev_low = round(prev_day['High'], 2), round(prev_day['Low'], 2)
            prev_close, prev_vol = round(prev_day['Close'], 2), int(prev_day['Volume'])
        else:
            prev_high = prev_low = prev_close = prev_vol = "無資料"

        df_5m = stock.history(period="3d", interval="5m")
        if df_5m.empty: return f"【昨日關鍵價】最高:{prev_high}, 最低:{prev_low}, 收盤:{prev_close}\n(註：目前無盤中 5 分 K 數據)"
            
        df_5m['5MA'] = df_5m['Close'].rolling(window=5).mean()
        df_5m['10MA'] = df_5m['Close'].rolling(window=10).mean()
        df_5m_recent = df_5m.tail(8)[['Close', 'Volume', '5MA', '10MA']].round(2)
        df_5m_recent.index = df_5m_recent.index.strftime('%H:%M')
        
        out = f"【昨日關鍵價】最高:{prev_high}, 最低:{prev_low}, 收盤:{prev_close}, 量:{prev_vol}\n\n"
        out += f"【盤中5分K動能】\n{df_5m_recent.to_markdown()}"
        return out
    except Exception as e:
        return f"技術資料抓取失敗: {str(e)}"

def get_chips_data(stock_id, days=5):
    if not stock_id.isdigit(): return "美股無台灣法人籌碼資料"
    url = "https://api.finmindtrade.com/api/v4/data"
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    parameter = {"dataset": "TaiwanStockInstitutionalInvestorsBuySell", "data_id": str(stock_id), "start_date": start_date}
    try:
        resp = requests.get(url, params=parameter).json()
        if resp.get("msg") != "success" or not resp.get("data"): return "無法人數據"
        df = pd.DataFrame(resp["data"])
        df['買賣超(張)'] = (df['buy'] - df['sell']) / 1000
        df_pivot = df.pivot_table(index='date', columns='name', values='買賣超(張)', aggfunc='sum').fillna(0)
        cols_map = {'外資及陸資(不含外資自營商)': '外資', '投信': '投信', '自營商(自行買賣)': '自營商'}
        df_pivot = df_pivot.rename(columns=cols_map)
        available_cols = [c for c in cols_map.values() if c in df_pivot.columns]
        return df_pivot[available_cols].tail(days).round(0).to_markdown()
    except Exception as e:
        return f"籌碼資料抓取失敗: {str(e)}"

@app.route("/", methods=['GET', 'POST'])
def index():
    result_html = ""
    stock_id = ""
    
    if request.method == 'POST':
        stock_id = request.form.get('stock_id', '').strip().upper()
        if stock_id:
            try:
                api_key = os.environ.get('GEMINI_API_KEY')
                if not api_key:
                    raise ValueError("伺服器找不到 GEMINI_API_KEY，請確認 Render 環境變數是否設定正確。")

                genai.configure(api_key=api_key)
                
                tech_md = get_technical_data(stock_id)
                chips_md = get_chips_data(stock_id)   
                
                system_prompt = "你是一位專業的當沖與波段分析師。請保持絕對客觀，分析以下數據，判斷趨勢與關鍵支撐壓力位，並給出行動結論。"
                
                # 這裡已經更新為正確的模型名稱
                model = genai.GenerativeModel(model_name='gemini-1.5-flash-latest', system_instruction=system_prompt)
                user_prompt = f"請針對股票 {stock_id} 分析：\n[技術面]\n{tech_md}\n[籌碼面]\n{chips_md}"
                
                response = model.generate_content(user_prompt)
                
                result_html = response.text.replace('\n', '<br>').replace('**', '<b>').replace('**', '</b>')
            except Exception as e:
                error_trace = traceback.format_exc()
                result_html = f"<div style='color:red; text-align:left; background:#ffe6e6; padding:15px; border-radius:8px; font-size:13px; overflow-x:auto;'><b style='font-size:16px;'>🚨 系統真實錯誤日誌：</b><br><br><pre>{error_trace}</pre></div>"

    html = f"""
    <!DOCTYPE html>
    <html lang="zh-TW">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>AI 專屬操盤手</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; color: #333; padding: 20px; max-width: 600px; margin: 0 auto; }}
            .container {{ background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); }}
            h2 {{ color: #2c3e50; text-align: center; margin-bottom: 20px; }}
            .input-group {{ display: flex; gap: 10px; margin-bottom: 20px; }}
            input[type="text"] {{ flex: 1; padding: 12px; font-size: 16px; border: 1px solid #ddd; border-radius: 8px; outline: none; }}
            button {{ padding: 12px 24px; font-size: 16px; background-color: #2c3e50; color: white; border: none; border-radius: 8px; cursor: pointer; transition: 0.3s; }}
            button:hover {{ background-color: #1a252f; }}
            .result {{ background: #f8f9fa; padding: 20px; border-left: 4px solid #2c3e50; border-radius: 4px; line-height: 1.8; font-size: 15px; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>📈 AI 專屬操盤手</h2>
            <form method="POST">
                <div class="input-group">
                    <input type="text" name="stock_id" placeholder="輸入代碼 (例: 00918, TSLA)" value="{stock_id}" required>
                    <button type="submit">開始分析</button>
                </div>
            </form>
            {f'<div class="result">{result_html}</div>' if result_html else ''}
        </div>
    </body>
    </html>
    """
    return html

if __name__ == "__main__":
    app.run(port=8080)
