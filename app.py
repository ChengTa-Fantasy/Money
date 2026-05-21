import os
import yfinance as yf
import pandas as pd
import requests
from flask import Flask, request
import google.generativeai as genai
from datetime import datetime, timedelta

app = Flask(__name__)

# 這裡只吃 Gemini 的金鑰，LINE 的通通不需要了
genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))

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
        df_5m_recent.index = df_5m_recent.index.tz_localize(None).strftime('%H:%M')
        
        out = f"【昨日關鍵價】最高:{prev_high}, 最低:{prev_low}, 收盤:{prev_close}, 量:{prev_vol}\n\n"
        out += f"【盤中5分K動能】\n{df_5m_recent.to_markdown()}"
        return out
    except Exception as e:
        return "技術線型資料抓取失敗"

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
    except:
        return "法人籌碼資料抓取失敗"

@app.route("/", methods=['GET', 'POST'])
def index():
    result_html = ""
    stock_id = ""
    
    if request.method == 'POST':
        stock_id = request.form.get('stock_id', '').strip().upper()
        if stock_id:
            try:
                tech_md = get_technical_data(stock_id)
                chips_md = get_chips_data(stock_id)   
                
                system_prompt = """你現在是一位頂級的「當沖交易員」與「波段策略分析師」。
                【分析核心原則】
                1. 絕對客觀：不帶情緒，只看數據與K線說話。
                2. 風險至上：永遠先抓停損點，再看獲利空間。
                3. 沖抱雙規：必須同時評估「日內當沖」動能與「波段持有」安全性。

                請輸出以下格式：
                【價格與動能速寫】趨勢、動能、法人籌碼
                【當沖作戰劇本】精算「突破轉強點(壓力)」與「絕對防守點(支撐)」。分別寫出多方與空方進場條件、停利、停損，並警告當沖風險。
                【波段持有評估】基本面護城河、籌碼集中度、留倉安全性(適合留倉/短波/絕不可留倉)、波段防守底線。
                【最終行動結論】一句話總結現在最適合的操作方式。"""
                
                model = genai.GenerativeModel(model_name='gemini-1.5-flash', system_instruction=system_prompt)
                user_prompt = f"請針對股票 {stock_id} 分析：\n[技術面]\n{tech_md}\n[籌碼面]\n{chips_md}"
                response = model.generate_content(user_prompt, generation_config=genai.types.GenerationConfig(temperature=0.2))
                
                # 將結果轉換為網頁好閱讀的格式
                result_html = response.text.replace('\n', '<br>').replace('**', '<b>').replace('**', '</b>')
            except Exception as e:
                result_html = f"<span style='color:red;'>分析失敗，請確認代碼是否正確。</span>"

    # 簡單乾淨的網頁介面
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

@app.route("/keep_awake", methods=['GET'])
def keep_awake():
    return "I am awake!"

if __name__ == "__main__":
    app.run(port=8080)
