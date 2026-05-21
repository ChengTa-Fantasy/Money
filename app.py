import os
import yfinance as yf
import pandas as pd
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai
import threading
from datetime import datetime, timedelta

app = Flask(__name__)

line_bot_api = LineBotApi(os.environ.get('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.environ.get('LINE_CHANNEL_SECRET'))
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

def generate_report_and_send(stock_id, user_id):
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
        
        line_bot_api.push_message(user_id, TextSendMessage(text=response.text))
    except Exception as e:
        line_bot_api.push_message(user_id, TextSendMessage(text=f"分析失敗，請確認代碼是否正確。"))

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try: handler.handle(body, signature)
    except InvalidSignatureError: abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text.strip().upper()
    user_id = event.source.user_id
    
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"已收到標的 {user_text}。正在計算當沖價位與籌碼，請稍候..."))
    threading.Thread(target=generate_report_and_send, args=(user_text, user_id)).start()

@app.route("/keep_awake", methods=['GET'])
def keep_awake():
    return "I am awake!"

if __name__ == "__main__":
    app.run(port=8080)
