#!/usr/bin/env python3
"""
HR 知識庫智能查詢系統 - Streamlit 部署版本

支援資料來源：
- 勞動法規 FAQ（勞動部、勞保局、職安署）
- 勞動業務說明
- 稅務問答（綜合所得稅）
- 健保業務（投保與保費）
- 法規條文（全國法規資料庫）
"""

import streamlit as st
import os
import re
import time
import json
from typing import List, Dict, Any
from pathlib import Path

# 頁面配置
st.set_page_config(
    page_title="人資法規智能查詢",
    page_icon="👷",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Store 配置（4 個 Store）- v2 版本
# 2025-11-29 更新：重建 Store 修復重複文件問題
STORES = {
    # === 勞動法規 ===
    'labor_faq': {
        'name': 'krepo-labor-faq-v2',
        'store_id': 'fileSearchStores/krepolaborfaqv2-knbagjg20f9k',
        'display_name': '勞動法規FAQ',
        'icon': '👷',
        'description': '勞動部、勞保局、職安署常見問答',
        'count': 1691,
        'group': 'labor',
    },
    'labor_articles': {
        'name': 'krepo-labor-articles-v2',
        'store_id': 'fileSearchStores/krepolaborarticlesv2-c0q9a9rfsmok',
        'display_name': '勞動與健保業務',
        'icon': '📋',
        'description': '勞動部業務專區、勞保局保險業務、健保投保說明',
        'count': 626,
        'group': 'labor',
    },
    # === 稅務 ===
    'tax_faq': {
        'name': 'krepo-tax-faq-v2',
        'store_id': 'fileSearchStores/krepotaxfaqv2-f7rnf4bjyo4f',
        'display_name': '稅務問答',
        'icon': '💰',
        'description': '綜合所得稅問與答',
        'count': 318,
        'group': 'tax',
    },
    # === 法規 ===
    'law_articles': {
        'name': 'krepo-law-articles-v2',
        'store_id': 'fileSearchStores/krepolawarticlesv2-s6rfdsug6uvx',
        'display_name': '法規條文',
        'icon': '📖',
        'description': '全民健康保險法等法規條文',
        'count': 561,
        'group': 'law',
    },
}


def load_mappings():
    """
    載入 gemini_mappings 目錄下的映射檔案

    格式: {doc_id: {gemini_file_id, store_id, source, title, date, original_url, uploaded_at}}
    """
    mappings_path = Path(__file__).parent.parent / "data" / "gemini_mappings"

    gemini_id_mapping = {}  # gemini_short_id -> doc_id
    file_mapping = {}       # doc_id -> info

    mapping_files = [
        "krepo-labor-faq-v2.json",
        "krepo-labor-articles-v2.json",
        "krepo-tax-faq-v2.json",
        "krepo-law-articles-v2.json",
    ]

    try:
        for filename in mapping_files:
            filepath = mappings_path / filename
            if filepath.exists():
                with open(filepath, 'r', encoding='utf-8') as f:
                    raw_mapping = json.load(f)
                    for doc_id, info in raw_mapping.items():
                        # 建立 gemini_id -> doc_id 映射
                        gemini_file_id = info.get('gemini_file_id', '')
                        if gemini_file_id:
                            short_id = gemini_file_id.replace('files/', '')
                            gemini_id_mapping[short_id] = doc_id

                        # 建立 doc_id -> info 映射
                        file_mapping[doc_id] = {
                            'display_name': info.get('title', ''),
                            'date': info.get('date', ''),
                            'source': info.get('source', ''),
                            'store_id': info.get('store_id', ''),
                            'original_url': info.get('original_url', ''),
                        }

    except Exception as e:
        st.warning(f"載入 mapping 檔案時發生錯誤: {e}")

    return gemini_id_mapping, file_mapping


# 全域 Mapping (載入一次)
GEMINI_ID_MAPPING, FILE_MAPPING = load_mappings()


def load_law_pcode_mapping() -> Dict[str, str]:
    """
    載入法規名稱 → pcode 對照表

    用於將法規名稱轉換為全國法規資料庫連結
    """
    mapping_path = Path(__file__).parent.parent / "data" / "law_pcode_mapping.json"

    try:
        if mapping_path.exists():
            with open(mapping_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        st.warning(f"載入法規對照表時發生錯誤: {e}")

    return {}


# 全域法規對照表
LAW_PCODE_MAPPING = load_law_pcode_mapping()

# 預先計算排序後的法規名稱（長度由長到短，避免部分匹配問題）
SORTED_LAW_NAMES = sorted(LAW_PCODE_MAPPING.keys(), key=len, reverse=True)


def linkify_law_names(text: str) -> str:
    """
    將文字中的法規名稱轉換為可點擊的連結

    支援格式：
    - 純法規名稱：勞動基準法 → [勞動基準法](url)
    - 法規+條文：勞動基準法第38條 → [勞動基準法第38條](url)
    - 包含項款：勞動基準法第11條第1項第5款 → [勞動基準法第11條第1項第5款](url)

    Args:
        text: 原始文字

    Returns:
        轉換後的文字（含 Markdown 連結）
    """
    if not text or not LAW_PCODE_MAPPING:
        return text

    # 記錄已替換的位置，避免重複替換
    replaced_ranges = []

    def is_overlapping(start: int, end: int) -> bool:
        """檢查是否與已替換的範圍重疊"""
        for r_start, r_end in replaced_ranges:
            if start < r_end and end > r_start:
                return True
        return False

    # 建立替換列表（位置, 原始文字, 連結文字）
    replacements = []

    for law_name in SORTED_LAW_NAMES:
        pcode = LAW_PCODE_MAPPING[law_name]

        # 匹配法規名稱 + 可選的條文編號（第X條、第X條之Y、第X條第Y項第Z款、但書等）
        # 支援各種標點符號包圍的格式（Gemini 可能使用《》「」『』【】等）
        # 條文編號格式：第\d+條(?:之\d+)?(?:第\d+項)?(?:第\d+款)?(?:但書)?
        pattern = r'[《「『【]?' + re.escape(law_name) + r'[》」』】]?(第\d+條(?:之\d+)?(?:第\d+項)?(?:第\d+款)?(?:但書)?)?'

        for match in re.finditer(pattern, text):
            start, end = match.span()

            # 檢查是否已被替換
            if is_overlapping(start, end):
                continue

            full_match = match.group(0)
            article_part = match.group(1)  # 可能是 None

            # 建構 URL
            if article_part:
                # 提取條文編號（阿拉伯數字）
                article_match = re.search(r'第(\d+)條', article_part)
                if article_match:
                    article_num = article_match.group(1)
                    # 單一條文頁面
                    url = f"https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode={pcode}&flno={article_num}"
                else:
                    # 整部法規頁面
                    url = f"https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode={pcode}"
            else:
                # 整部法規頁面
                url = f"https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode={pcode}"

            # 建立 Markdown 連結
            link = f"[{full_match}]({url})"

            replacements.append((start, end, full_match, link))
            replaced_ranges.append((start, end))

    # 按位置倒序排列，從後往前替換（避免位置偏移）
    replacements.sort(key=lambda x: x[0], reverse=True)

    result = text
    for start, end, original, link in replacements:
        result = result[:start] + link + result[end:]

    return result


def linkify_law_section(text: str) -> str:
    """
    只在「相關法規」區塊將法規名稱轉換為連結

    找到「相關法規:」或「相關法規：」後的內容，只對該部分套用連結轉換。
    其他內文保持原樣。

    Args:
        text: 原始答案文字

    Returns:
        轉換後的文字
    """
    if not text:
        return text

    # 尋找「相關法規」區塊的各種可能格式
    patterns = [
        r'(相關法規[：:]\s*)',      # 相關法規: 或 相關法規：
        r'(相關法規引用[：:]\s*)',  # 相關法規引用:
        r'(引用法規[：:]\s*)',      # 引用法規:
        r'(法規依據[：:]\s*)',      # 法規依據:
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            # 找到標題位置
            header_end = match.end()

            # 跳過標題後的空白行（可能有 \n\n 或多個空行）
            remaining_after_header = text[header_end:]
            skip_match = re.match(r'^[\s\n]*', remaining_after_header)
            if skip_match:
                content_start = header_end + skip_match.end()
            else:
                content_start = header_end

            # 從內容開始處找結尾
            remaining = text[content_start:]

            # 找下一個明顯的段落分隔（兩個以上的換行，或特殊標記開頭）
            # 排除法規列表中的單一換行
            end_match = re.search(r'\n\n\n|\n\n(?=[^《「『【\n])', remaining)
            if end_match:
                end_pos = content_start + end_match.start()
            else:
                # 到文件結尾
                end_pos = len(text)

            law_section = text[content_start:end_pos]
            # 只對法規區塊套用連結
            linked_section = linkify_law_names(law_section)
            return text[:content_start] + linked_section + text[end_pos:]

    # 沒找到相關法規區塊，返回原文
    return text


def resolve_source_display_name(raw_id: str) -> tuple:
    """
    將 Gemini 回傳的 file ID 解析為可讀的顯示名稱

    回傳: (display_name, source_type, date, original_url)
    """
    # 先檢查 raw_id 是否直接是 doc_id
    if raw_id in FILE_MAPPING:
        doc_id = raw_id
    else:
        # 嘗試從 gemini_id -> doc_id 映射查詢
        doc_id = GEMINI_ID_MAPPING.get(raw_id, '')

    if doc_id and doc_id in FILE_MAPPING:
        info = FILE_MAPPING[doc_id]
        display_name = info.get('display_name', '')
        date = info.get('date', '未知日期')
        source = info.get('source', '')
        original_url = info.get('original_url', '')

        # 判斷來源類型和圖標
        if 'mol_faq' in source:
            source_type = "勞動部FAQ"
            icon = "👷"
        elif 'bli_faq' in source:
            source_type = "勞保局FAQ"
            icon = "🏢"
        elif 'osha_faq' in source:
            source_type = "職安署FAQ"
            icon = "⚠️"
        elif 'mol_business' in source:
            source_type = "勞動部業務"
            icon = "📋"
        elif 'bli_insurance' in source:
            source_type = "勞保局業務"
            icon = "📄"
        elif 'individual_income_tax' in source:
            source_type = "稅務問答"
            icon = "💰"
        elif 'insurance_premium' in source:
            source_type = "健保業務"
            icon = "🏥"
        elif 'law_articles' in source:
            source_type = "法規條文"
            icon = "📖"
        else:
            source_type = "未知"
            icon = "📄"

        # 格式化顯示名稱
        if display_name:
            # 截斷過長的標題
            short_title = display_name[:40] + "..." if len(display_name) > 40 else display_name
            return f"{icon} {short_title}", source_type, date, original_url

        return f"{icon} {source_type}_{date}", source_type, date, original_url

    # 如果 mapping 找不到
    return f"📄 {raw_id[:30]}...", "未知", "未知日期", ""


# 範例問題
EXAMPLE_QUESTIONS = [
    "勞工退休金提繳率是多少？",
    "資遣費如何計算？",
    "育嬰留職停薪期間健保怎麼處理？",
    "加班費要如何計算？",
    "職災補償有哪些項目？",
    "扣繳憑單什麼時候要申報？",
]


def get_system_prompt(selected_stores: List[str]) -> str:
    """
    根據選取的 Store 組合產生系統提示
    """
    base_prompt = """你是專業的 HR 法規顧問，熟悉台灣勞動法規、稅務規定與健保制度。

請根據參考資料回答問題。

回答時必須：
1. 明確引用來源文件
2. 如果資料中沒有相關資訊，請誠實說明
3. 使用繁體中文回答
4. 保持專業、客觀的態度
"""

    # 根據選取的 Store 加入特定指引
    specific_guidelines = []

    if 'labor_faq' in selected_stores:
        specific_guidelines.append("""
【勞動法規FAQ指引】
- 直接引用常見問答內容
- 說明相關法規依據
- 列出適用對象和條件""")

    if 'labor_articles' in selected_stores:
        specific_guidelines.append("""
【勞動業務說明指引】
- 解釋業務流程和規定
- 說明申請方式和條件
- 列出所需文件""")

    if 'tax_faq' in selected_stores:
        specific_guidelines.append("""
【稅務問答指引】
- 解釋稅務規定
- 說明申報方式和期限
- 列出免稅或減稅條件""")

    if 'nhi_insurance' in selected_stores:
        specific_guidelines.append("""
【健保業務指引】
- 說明投保資格和條件
- 解釋保費計算方式
- 說明繳費規定""")

    if 'law_articles' in selected_stores:
        specific_guidelines.append("""
【法規條文指引】
- 引用完整的法條內容
- 說明法條的適用情況""")

    if specific_guidelines:
        return base_prompt + "\n" + "\n".join(specific_guidelines)
    return base_prompt


def query_gemini(
    question: str,
    selected_stores: List[str],
    api_key: str,
    model: str = 'gemini-2.5-flash'
) -> Dict[str, Any]:
    """
    使用 Gemini File Search 執行查詢
    """
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    # 取得選取的 Store IDs
    store_ids = [STORES[s]['store_id'] for s in selected_stores if s in STORES and STORES[s]['store_id']]

    if not store_ids:
        return {
            'answer': '請至少選擇一個資料來源（或 Store 尚未設定）',
            'sources': [],
            'error': True,
            'empty_answer': False
        }

    # 取得系統提示
    system_prompt = get_system_prompt(selected_stores)

    start_time = time.time()

    try:
        response = client.models.generate_content(
            model=model,
            contents=question,
            config=types.GenerateContentConfig(
                tools=[
                    types.Tool(
                        file_search=types.FileSearch(
                            file_search_store_names=store_ids
                        )
                    )
                ],
                temperature=0.1,
                max_output_tokens=8000,
                system_instruction=system_prompt
            )
        )

        latency = time.time() - start_time

        # 提取答案
        answer = None
        empty_answer = True
        if hasattr(response, 'text') and response.text:
            answer = response.text
            empty_answer = False

        # 提取來源
        sources = extract_sources(response)

        return {
            'answer': answer,
            'sources': sources,
            'latency': latency,
            'error': False,
            'empty_answer': empty_answer,
        }

    except Exception as e:
        return {
            'answer': f'查詢失敗: {str(e)}',
            'sources': [],
            'error': True,
            'empty_answer': False
        }


def extract_sources(response) -> List[Dict[str, Any]]:
    """
    從 Gemini 回應中提取來源（已去重）
    """
    sources = []
    seen_ids = set()

    try:
        if hasattr(response, 'candidates') and len(response.candidates) > 0:
            candidate = response.candidates[0]

            if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
                metadata = candidate.grounding_metadata

                if hasattr(metadata, 'grounding_chunks') and metadata.grounding_chunks:
                    for chunk in metadata.grounding_chunks:
                        if hasattr(chunk, 'retrieved_context'):
                            context = chunk.retrieved_context

                            # 提取原始檔名/ID
                            raw_id = ""
                            if hasattr(context, 'title') and context.title:
                                raw_id = context.title
                            elif hasattr(context, 'uri') and context.uri:
                                raw_id = context.uri.split('/')[-1]

                            # 去重
                            if raw_id in seen_ids:
                                continue
                            seen_ids.add(raw_id)

                            # 使用 mapping 解析顯示名稱
                            display_name, source_type, date, original_url = resolve_source_display_name(raw_id)

                            snippet = ""
                            if hasattr(context, 'text') and context.text:
                                snippet = context.text[:500]

                            score = 1.0
                            if hasattr(chunk, 'score'):
                                score = float(chunk.score)

                            sources.append({
                                'filename': display_name,
                                'raw_id': raw_id,
                                'source_type': source_type,
                                'date': date,
                                'snippet': snippet,
                                'score': score,
                                'original_url': original_url,
                            })

    except Exception as e:
        st.warning(f"提取來源時發生錯誤: {e}")

    return sources


def render_sidebar():
    """渲染側邊欄"""
    with st.sidebar:
        st.header("📊 資料來源")

        # 選擇全部 / 取消選擇 按鈕
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ 全選", use_container_width=True):
                for key in STORES.keys():
                    st.session_state[f"store_{key}"] = True
                st.rerun()
        with col2:
            if st.button("❌ 取消", use_container_width=True):
                for key in STORES.keys():
                    st.session_state[f"store_{key}"] = False
                st.rerun()

        st.markdown("---")

        selected_stores = []

        # === 勞動法規 ===
        st.caption("👷 勞動法規")
        for key, store in STORES.items():
            if store.get('group') != 'labor':
                continue
            default_value = (key == 'labor_faq') if f"store_{key}" not in st.session_state else None
            checked = st.checkbox(
                f"{store['icon']} {store['display_name']}",
                value=default_value if default_value is not None else None,
                key=f"store_{key}",
                help=store['description']
            )
            if checked:
                selected_stores.append(key)

        st.markdown("---")

        # === 稅務 ===
        st.caption("💰 稅務")
        for key, store in STORES.items():
            if store.get('group') != 'tax':
                continue
            checked = st.checkbox(
                f"{store['icon']} {store['display_name']}",
                key=f"store_{key}",
                help=store['description']
            )
            if checked:
                selected_stores.append(key)

        st.markdown("---")

        # === 法規 ===
        st.caption("📖 法規條文")
        for key, store in STORES.items():
            if store.get('group') != 'law':
                continue
            checked = st.checkbox(
                f"{store['icon']} {store['display_name']}",
                key=f"store_{key}",
                help=store['description']
            )
            if checked:
                selected_stores.append(key)

        st.markdown("---")

        # 檢查是否選取資料來源
        if not selected_stores:
            st.warning("請至少選擇一個資料來源")

        st.markdown("---")

        # 使用說明
        st.header("📖 使用說明")
        st.markdown("""
1. **選擇資料來源**：勾選要查詢的知識庫
2. **輸入問題**：在主畫面輸入您的問題
3. **點擊查詢**：AI 會從選取的知識庫中搜尋相關資料並回答
4. **查看來源**：展開參考來源可查看原始內容
""")

    return selected_stores


def main():
    """主程式"""
    # 取得 API Key
    api_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")

    if not api_key:
        st.error("請設定 GEMINI_API_KEY")
        st.stop()

    # 渲染側邊欄
    selected_stores = render_sidebar()

    # 主標題
    st.title("👷 人資法規智能查詢")
    st.caption("⚠️ 本系統為展示用，如遇畫面無反應，請重新整理頁面")

    # 問題輸入
    if 'current_question' not in st.session_state:
        st.session_state.current_question = ""

    question = st.text_area(
        "請輸入您的問題：",
        value=st.session_state.current_question,
        placeholder="例如：資遣費如何計算？",
        height=100
    )

    # 按鈕列
    col1, col2, col3 = st.columns([1, 1, 4])

    with col1:
        submit_button = st.button("🔍 查詢", type="primary", use_container_width=True)

    with col2:
        if st.button("🗑️ 清除", use_container_width=True):
            st.session_state.current_question = ""
            st.rerun()

    # 處理查詢
    if submit_button and question:
        if not selected_stores:
            st.error("請至少選擇一個資料來源")
        else:
            with st.spinner("🔍 AI 查詢中..."):
                result = query_gemini(
                    question,
                    selected_stores,
                    api_key
                )

            if result['error']:
                st.error(result['answer'])
            elif result['empty_answer'] or not result['sources']:
                st.warning("⚠️ 查詢未能取得有效回答")
                st.info("請嘗試換個方式描述您的問題。")
            else:
                # 顯示結果
                st.success("✅ 查詢完成")

                stores_text = ", ".join([STORES[s]['display_name'] for s in selected_stores])
                st.caption(f"⏱️ 回應時間: {result['latency']:.2f} 秒　｜　📚 來源數量: {len(result['sources'])} 筆　｜　📂 查詢範圍: {stores_text}")

                st.markdown("---")

                # 答案
                st.subheader("📝 答案")
                # 全內容比對法規名稱，產生連結（不限於特定區塊）
                answer_with_links = linkify_law_names(result['answer'])
                st.markdown(answer_with_links)

                st.markdown("---")

                # 來源（去重複）
                if result['sources']:
                    # 以 filename 去重複
                    seen_filenames = set()
                    unique_sources = []
                    for source in result['sources']:
                        if source['filename'] not in seen_filenames:
                            seen_filenames.add(source['filename'])
                            unique_sources.append(source)

                    st.subheader(f"📚 參考來源 ({len(unique_sources)} 筆)")

                    # 按類型分組
                    source_groups = {}
                    for source in unique_sources:
                        stype = source.get('source_type', '未知')
                        if stype not in source_groups:
                            source_groups[stype] = []
                        source_groups[stype].append(source)

                    # 顯示各組
                    for stype, sources_list in source_groups.items():
                        st.caption(f"{stype} ({len(sources_list)} 筆)")
                        for source in sources_list:
                            with st.expander(f"{source['filename']}", expanded=False):
                                st.markdown(f"**相關內容：**")
                                st.markdown(f"> {source['snippet'][:300]}...")

                                if source.get('original_url'):
                                    st.markdown(f"[🔗 查看原始網頁]({source['original_url']})")

    # 範例問題
    if not question:
        st.markdown("---")
        st.subheader("💡 範例問題")

        cols = st.columns(2)
        for idx, eq in enumerate(EXAMPLE_QUESTIONS):
            col = cols[idx % 2]
            with col:
                if st.button(f"📌 {eq}", key=f"example_{idx}", use_container_width=True):
                    st.session_state.current_question = eq
                    st.rerun()

    # 頁尾
    st.divider()
    st.caption("資料來源：意藍資訊勞動知識庫")


if __name__ == "__main__":
    main()
