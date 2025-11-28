# 人資法規智能查詢

HR 知識庫查詢系統，使用 Gemini File Search API 搭配 Streamlit 前端。

## 功能

- 勞動法規 FAQ（勞動部、勞保局、職安署）
- 勞動與健保業務說明
- 稅務問答（綜合所得稅）
- 法規條文查詢

## 資料統計

| 知識庫 | 文件數 |
|--------|--------|
| 勞動法規 FAQ | 1,487 |
| 勞動與健保業務 | 228 |
| 稅務問答 | 318 |
| 法規條文 | 193 |
| **合計** | **2,226** |

## 部署

### Streamlit Cloud

1. 連結 GitHub 儲存庫
2. 設定 Secrets：
   ```toml
   GEMINI_API_KEY = "your-api-key"
   ```
3. 主程式路徑：`app/main.py`

### 本機執行

```bash
pip install -r requirements.txt
export GEMINI_API_KEY="your-api-key"
streamlit run app/main.py
```

## 技術架構

- **前端**：Streamlit
- **AI**：Google Gemini 2.5 Flash + File Search API
- **部署**：Streamlit Cloud

## 資料來源

意藍資訊勞動知識庫
