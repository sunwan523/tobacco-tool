from __future__ import annotations

import pandas as pd
import streamlit as st

# 导入原项目的价格存储模块
from tobacco_core.price_store import load_price_db, search_prices, save_price_db, upsert_manual_market_prices

# 设置页面配置
st.set_page_config(
    page_title="烟草价格查询",
    page_icon="📊",
    layout="centered"
)

# 添加自定义样式
st.markdown("""
<style>
    .block-container {
        max-width: fit-content;
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    h1 {
        font-size: 1.75rem;
        line-height: 1.2;
        margin-bottom: 0.5rem;
    }
    h2 {
        font-size: 1.25rem;
    }
    .stDataFrame, .stButton, .stTextInput, .stAlert {
        margin-left: auto;
        margin-right: auto;
    }
    div[data-testid="stHorizontalBlock"] {
        justify-content: center;
    }
    div[data-testid="stMetric"] {
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# 页面标题
st.title("📊 曲靖本地近期行情价格查询")

# 初始化 session_state 变量
if "price_search_text" not in st.session_state:
    st.session_state.price_search_text = ""
if "price_edits" not in st.session_state:
    st.session_state.price_edits = {}
if "show_price_table" not in st.session_state:
    st.session_state.show_price_table = False
if "show_admin" not in st.session_state:
    st.session_state.show_admin = False

# 加载价格数据
db_prices = load_price_db()

# 分割线
st.divider()

# 搜索区域
st.subheader("🔍 价格查询")

# 创建搜索表单
with st.form("price_search_form", clear_on_submit=False):
    search_col, button_col = st.columns([4, 1], gap="small")
    with search_col:
        search_text = st.text_input(
            "搜索",
            value=st.session_state.price_search_text,
            placeholder="输入商品名称、拼音首字母、条码或盒码",
            label_visibility="collapsed",
        )
    with button_col:
        submitted = st.form_submit_button("搜索", width='stretch', type="primary")

if submitted:
    st.session_state.price_search_text = search_text.strip()
    st.session_state.price_edits = {}
    st.session_state.show_price_table = True

# 执行搜索
price_results = search_prices(db_prices, st.session_state.price_search_text)

# 显示搜索结果
if st.session_state.show_price_table:
    if price_results.empty:
        st.warning("未找到匹配的商品，请尝试其他搜索词。")
    else:
        # 调整列顺序
        display_columns = ["商品名称", "当期找货价格", "建议零售价", "批发价"]
        display_columns = [col for col in display_columns if col in price_results.columns]
        
        st.success(f"找到 {len(price_results)} 条相关商品")
        
        # 显示搜索结果表格
        st.dataframe(
            price_results[display_columns],
            use_container_width=True,
            hide_index=True,
            column_config={
                "商品名称": "商品名称",
                "当期找货价格": st.column_config.NumberColumn("行情价", format="%.2f"),
                "建议零售价": st.column_config.NumberColumn("建议零售价", format="%.2f"),
                "批发价": st.column_config.NumberColumn("批发价", format="%.2f"),
            }
        )

        st.divider()

# 价格统计信息
if not db_prices.empty:
    st.subheader("📈 价格库概览")
    stat_cols = st.columns(3)
    stat_cols[0].metric("商品总数", f"{len(db_prices)}")
    stat_cols[1].metric("有行情价", f"{len(db_prices[db_prices['当期找货价格'].notna()])}")
    stat_cols[2].metric("缺少行情价", f"{len(db_prices[db_prices['当期找货价格'].isna()])}")

# 管理员功能区域
st.divider()
st.subheader("⚙️ 管理员功能")

# 密码验证区域
if not st.session_state.show_admin:
    with st.form("admin_password_form"):
        password = st.text_input("请输入管理员密码以编辑价格", type="password")
        submit_password = st.form_submit_button("验证")
        
        if submit_password and password == "523626":
            st.session_state.show_admin = True
            st.success("密码正确！管理员功能已解锁")
            st.rerun()
        elif submit_password:
            st.error("密码错误，请重试")
else:
    st.success("管理员模式已启用")
    
    # 管理员功能
    tab1, tab2, tab3 = st.tabs(["编辑价格", "补录行情价", "导出价格"])
    
    with tab1:
        st.write("编辑现有商品的行情价格")
        
        if st.button("显示完整价格列表"):
            st.session_state.show_price_table = True
            st.session_state.price_search_text = ""
        
        # 显示可编辑的价格表格
        if st.session_state.show_price_table or not price_results.empty:
            edit_df = st.data_editor(
                price_results[["商品名称", "当期找货价格", "建议零售价", "批发价"]] if not price_results.empty else db_prices[["商品名称", "当期找货价格", "建议零售价", "批发价"]],
                column_config={
                    "商品名称": st.column_config.TextColumn("商品名称", disabled=True),
                    "当期找货价格": st.column_config.NumberColumn("行情价", min_value=0, step=0.01, format="%.2f"),
                    "建议零售价": st.column_config.NumberColumn("建议零售价", disabled=True),
                    "批发价": st.column_config.NumberColumn("批发价", disabled=True),
                },
                use_container_width=True,
                hide_index=True,
            )
            
            if not edit_df.equals(price_results[["商品名称", "当期找货价格", "建议零售价", "批发价"]] if not price_results.empty else db_prices[["商品名称", "当期找货价格", "建议零售价", "批发价"]]):
                # 收集修改的价格
                price_edits = {}
                original_df = price_results[["商品名称", "当期找货价格", "建议零售价", "批发价"]] if not price_results.empty else db_prices[["商品名称", "当期找货价格", "建议零售价", "批发价"]]
                
                for idx, row in edit_df.iterrows():
                    original_row = original_df.iloc[idx]
                    if row["当期找货价格"] != original_row["当期找货价格"]:
                        price_edits[row["商品名称"]] = row["当期找货价格"]
                
                if price_edits:
                    st.session_state.price_edits = price_edits
                    st.write(f"准备保存 {len(price_edits)} 条价格修改")
                    
                    if st.button("确认保存修改", type="primary"):
                        updated_db = db_prices.copy()
                        for product_name, new_price in price_edits.items():
                            updated_db.loc[updated_db["商品名称"] == product_name, "当期找货价格"] = new_price
                        save_price_db(updated_db)
                        st.success(f"成功保存 {len(price_edits)} 条价格修改！")
                        st.session_state.price_edits = {}
                        st.rerun()
    
    with tab2:
        st.write("补录缺少行情价的商品")
        missing_prices = db_prices[db_prices["当期找货价格"].isna()].copy()
        
        if missing_prices.empty:
            st.success("所有商品都有行情价，无需补录！")
        else:
            st.warning(f"有 {len(missing_prices)} 条商品缺少行情价")
            
            editable_missing = missing_prices.copy()
            editable_missing["当期找货价格"] = editable_missing["当期找货价格"].astype("float64")
            
            edited_missing = st.data_editor(
                editable_missing[["商品名称", "当期找货价格", "批发价", "建议零售价"]],
                column_config={
                    "商品名称": st.column_config.TextColumn("商品名称", disabled=True),
                    "当期找货价格": st.column_config.NumberColumn("行情价", min_value=0, step=0.01, format="%.2f"),
                    "批发价": st.column_config.NumberColumn("批发价", disabled=True),
                    "建议零售价": st.column_config.NumberColumn("建议零售价", disabled=True),
                },
                use_container_width=True,
                hide_index=True,
            )
            
            if not edited_missing.equals(editable_missing):
                to_save = edited_missing[edited_missing["当期找货价格"].notna()].copy()
                if len(to_save) > 0:
                    if st.button(f"保存 {len(to_save)} 条补录的价格", type="primary"):
                        manual = to_save[["商品名称", "批发价", "建议零售价", "当期找货价格"]].copy()
                        manual["批发价"] = pd.to_numeric(manual.get("批发价"), errors="coerce")
                        manual["建议零售价"] = pd.to_numeric(manual.get("建议零售价"), errors="coerce")
                        updated_db = upsert_manual_market_prices(db_prices, manual)
                        save_price_db(updated_db)
                        st.success(f"已保存 {len(to_save)} 条补录的行情价格！")
                        st.rerun()
    
    with tab3:
        st.write("导出当前价格库")
        
        if st.button("下载完整价格表", type="primary"):
            from io import BytesIO
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                db_prices.to_excel(writer, index=False, sheet_name='行情价格')
            output.seek(0)
            
            st.download_button(
                label="下载 Excel 文件",
                data=output,
                file_name="烟草行情价格表.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
            
            st.info(f"当前价格库共 {len(db_prices)} 条商品记录")

    # 提供退出管理员模式的选项
    if st.button("退出管理员模式"):
        st.session_state.show_admin = False
        st.rerun()
