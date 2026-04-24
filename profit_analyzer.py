import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import time
from io import BytesIO
import urllib.parse

st.set_page_config(page_title="Profit Analyzer", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    .main { padding: 20px; }
    h1 { color: #d32f2f; font-weight: 700; margin-bottom: 10px; }
    .metric-box { background: #f5f5f5; padding: 15px; border-radius: 8px; margin: 10px 0; }
    .status-processing { color: #1976d2; font-weight: 600; }
    .status-success { color: #388e3c; font-weight: 600; }
    .status-error { color: #d32f2f; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

st.title("📊 Profit Analyzer")
st.markdown("*Analyze resale profitability in real-time. Multi-product support, instant insights.*")

# Sidebar for settings
with st.sidebar:
    st.header("⚙️ Settings")
    shipping_shoe = st.slider("Shipping (Shoes) $", 5.00, 15.00, 8.00, 0.50)
    shipping_slide = st.slider("Shipping (Slides) $", 3.00, 8.00, 5.00, 0.50)
    resale_percent = st.slider("Resale Price % of MSRP", 50, 100, 75, 5)
    ebay_fee = st.slider("eBay Fee %", 10.0, 15.0, 12.9, 0.1)

# Input section
st.markdown("### 📥 Input Products")
tab1, tab2 = st.tabs(["Upload CSV", "Paste Titles"])

products = []

with tab1:
    uploaded_file = st.file_uploader("Upload CSV (columns: product_name, msrp)", type="csv")
    if uploaded_file:
        try:
            df = pd.read_csv(uploaded_file)
            required_cols = ['product_name', 'msrp']
            if all(col in df.columns for col in required_cols):
                products = df.to_dict('records')
                st.success(f"✓ Loaded {len(products)} products")
            else:
                st.error(f"CSV must have columns: {', '.join(required_cols)}")
        except Exception as e:
            st.error(f"Error reading CSV: {e}")

with tab2:
    pasted_text = st.text_area("Paste one product per line (format: Product Name | MSRP)\nExample: Nike Air Max 90 | 120", height=150)
    if pasted_text.strip():
        for line in pasted_text.strip().split('\n'):
            if '|' in line:
                try:
                    name, price = line.split('|')
                    products.append({
                        'product_name': name.strip(),
                        'msrp': float(price.strip())
                    })
                except:
                    st.warning(f"Skipped invalid line: {line}")

if products:
    st.markdown(f"### ✓ Ready to analyze {len(products)} products")
    
    if st.button("🚀 Start Analysis", use_container_width=True):
        st.markdown("---")
        
        results = []
        progress_container = st.container()
        results_container = st.container()
        
        with progress_container:
            progress_bar = st.progress(0)
            status_text = st.empty()
            
        with results_container:
            results_table = st.empty()
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        for idx, product in enumerate(products):
            product_name = product['product_name']
            msrp = product['msrp']
            
            status_text.markdown(f"<p class='status-processing'>Processing ({idx+1}/{len(products)}): {product_name[:60]}</p>", unsafe_allow_html=True)
            
            try:
                # Search eBay sold listings
                search_query = product_name.split()[0:3]  # Use first 3 words for search
                search_term = ' '.join(search_query)
                search_url = f"https://www.ebay.com/sch/i.html?_nkw={urllib.parse.quote(search_term)}&LH_ItemCondition=3000&LH_Sold=1&LH_Complete=1&rt=nc"
                
                response = requests.get(search_url, headers=headers, timeout=10)

                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Extract sold prices - updated for current eBay HTML
                prices = []
                
                # Try multiple selectors as eBay changes structure frequently
                price_selectors = [
                    ('span', {'class': 's-item-price'}),  # Current eBay format
                    ('span', {'class': 's-price'}),        # Legacy format
                    ('div', {'class': 's-item-price'}),    # Alternative format
                ]
                
                for tag_name, selector in price_selectors:
                    for price_elem in soup.find_all(tag_name, selector):
                        try:
                            price_text = price_elem.get_text().strip()
                            # Extract first price value (ignore strikethrough/original prices)
                            if '$' in price_text:
                                # Get just the first price mentioned
                                price_part = price_text.split('$')[1].split()[0]
                                price = float(price_part.replace(',', ''))
                                if 0 < price < 500:  # Sanity check: cases shouldn't be >$500
                                    prices.append(price)
                        except:
                            pass
                    
                    if prices:  # Stop if we found prices
                        break
                
                if prices:
                    avg_sold = sum(prices) / len(prices)
                    qty_sold = len(prices)
                else:
                    avg_sold = msrp * (resale_percent / 100)
                    qty_sold = 0
                
                # Determine shipping
                shipping = shipping_shoe
                if 'slide' in product_name.lower() or 'platform' in product_name.lower():
                    shipping = shipping_slide
                
                # Calculate profit
                resale_price = avg_sold
                ebay_fees = resale_price * (ebay_fee / 100)
                net_revenue = resale_price - ebay_fees - shipping
                profit = net_revenue - msrp
                margin = (profit / msrp * 100) if msrp > 0 else 0
                
                results.append({
                    'Product': product_name[:45],
                    'Avg Sold Price': f"${avg_sold:.2f}",
                    'Qty Sold (90d)': qty_sold,
                    'Shipping': f"${shipping:.2f}",
                    'eBay Fees': f"${ebay_fees:.2f}",
                    'Net Revenue': f"${net_revenue:.2f}",
                    'Profit': f"${profit:.2f}",
                    'Margin %': f"{margin:.1f}%",
                    'Status': '✓ Profitable' if profit > 0 else '✗ Loss'
                })
                
                # Update table in real-time
                if results:
                    results_table.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
                
            except Exception as e:
                results.append({
                    'Product': product_name[:45],
                    'Status': f'Error: {str(e)[:25]}'
                })
            
            progress_bar.progress((idx + 1) / len(products))
            time.sleep(1)  # Respectful delay for eBay servers
        
        # Final results
        st.markdown("---")
        st.markdown("### ✅ Analysis Complete")
        
        df_results = pd.DataFrame(results)
        
        # Summary stats
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            profitable = sum(1 for r in results if '✓' in r.get('Status', ''))
            st.metric("Profitable Items", f"{profitable}/{len(products)}")
        with col2:
            st.metric("Success Rate", f"{profitable/len(products)*100:.0f}%")
        with col3:
            st.metric("Items Analyzed", len(results))
        with col4:
            st.metric("Time Taken", f"~{len(products)}s")
        
        # Download Excel
        st.markdown("---")
        
        # Create Excel with formatting
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_results.to_excel(writer, sheet_name='Results', index=False)
            
            worksheet = writer.sheets['Results']
            for column in worksheet.columns:
                max_length = max(len(str(cell.value)) for cell in column) + 2
                worksheet.column_dimensions[column[0].column_letter].width = max_length
        
        output.seek(0)
        
        st.download_button(
            label="📥 Download Excel Report",
            data=output,
            file_name="profit_analysis.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
        
        st.success("✓ Done! Download your results or run another analysis.")

else:
    st.info("👆 Upload a CSV or paste product titles to get started")
