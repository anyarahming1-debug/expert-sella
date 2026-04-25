import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from io import BytesIO
import urllib.parse
import re
import time
from statistics import median

st.set_page_config(page_title="eBay Profit Analyzer", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
    .main { padding: 20px; }
    h1 { color: #d32f2f; font-weight: 700; }
    .small-note { color: #666; font-size: 0.9rem; }
</style>
""", unsafe_allow_html=True)

st.title("📊 eBay Profit Analyzer")
st.markdown(
    "Paste products as **Product title | buy cost**. "
    "This version does **not** invent fallback sold prices. If eBay sold comps are not found, it says NO DATA."
)

# -------------------------
# Helpers
# -------------------------

def parse_input_lines(text: str):
    products = []
    skipped = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "|" not in line:
            skipped.append(raw_line)
            continue

        # Split on the LAST pipe only, so titles may contain pipes.
        title, cost = line.rsplit("|", 1)
        title = title.strip()
        cost = cost.strip().replace("$", "").replace(",", "")

        try:
            cost_float = float(cost)
        except ValueError:
            skipped.append(raw_line)
            continue

        if title:
            products.append({"product_name": title, "buy_cost": cost_float})
        else:
            skipped.append(raw_line)

    return products, skipped


def parse_money(text: str):
    if not text:
        return None

    cleaned = text.replace(",", "").replace("US $", "$")
    # eBay sometimes shows "$12.99 to $19.99"; use first visible price.
    matches = re.findall(r"\$\s*(\d+(?:\.\d{1,2})?)", cleaned)
    if not matches:
        return None

    try:
        return float(matches[0])
    except ValueError:
        return None


def normalize(text: str):
    text = text.lower()
    text = text.replace("’", "'").replace("–", "-").replace("—", "-")
    text = re.sub(r"[^a-z0-9\s\.\-\/]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_phone_model(text: str):
    t = normalize(text)
    # Order matters: pro max before pro before base.
    patterns = [
        r"iphone\s*16\s*pro\s*max",
        r"iphone\s*16\s*pro",
        r"iphone\s*16\s*plus",
        r"iphone\s*16\b",
        r"iphone\s*15\s*pro\s*max",
        r"iphone\s*15\s*pro",
        r"iphone\s*15\s*plus",
        r"iphone\s*15\b",
        r"iphone\s*14\s*pro\s*max",
        r"iphone\s*14\s*pro",
        r"iphone\s*14\s*plus",
        r"iphone\s*14\b",
        r"iphone\s*13\s*pro\s*max",
        r"iphone\s*13\s*pro",
        r"iphone\s*13\s*mini",
        r"iphone\s*13\b",
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            return re.sub(r"\s+", " ", m.group(0)).strip()
    return None


def extract_size_tokens(text: str):
    """Useful mostly for fragrance/skincare/etc."""
    t = normalize(text)
    tokens = set()

    # oz / fl oz
    for m in re.findall(r"(\d+(?:\.\d+)?)\s*(?:fl\s*)?oz", t):
        tokens.add(f"{float(m):g} oz")

    # ml
    for m in re.findall(r"(\d+(?:\.\d+)?)\s*ml", t):
        tokens.add(f"{float(m):g} ml")

    # gb for tablets/electronics
    for m in re.findall(r"(\d+)\s*gb", t):
        tokens.add(f"{m} gb")

    # count / ct / pack
    for m in re.findall(r"(\d+)\s*(?:count|ct|pack|pk)\b", t):
        tokens.add(f"{m} ct")

    return tokens


def brand_tokens(product_name: str):
    t = normalize(product_name)
    brands = [
        "zagg", "otterbox", "uag", "casetify", "incase",
        "coach", "nike", "adidas", "vans", "crocs",
        "dior", "christian dior", "yves saint laurent", "ysl",
        "versace", "paco rabanne", "rabanne", "ralph lauren",
        "clinique", "estee lauder", "estée lauder", "montblanc",
        "mugler", "marc jacobs", "prada", "armani", "bose",
        "jbl", "amazon", "apple", "marshall", "creed",
        "parfums de marly", "viktor", "flowerbomb", "spicebomb",
    ]
    found = []
    for b in brands:
        if normalize(b) in t:
            found.append(normalize(b))
    return found


def clean_search_term(product_name: str):
    """
    eBay performs badly with huge Amazon titles.
    This shortens the query while preserving exact identifiers.
    """
    t = product_name

    # Remove retailer noise.
    t = re.sub(r"\|\s*verizon", "", t, flags=re.I)
    t = re.sub(r"\bwith notes of\b.*", "", t, flags=re.I)
    t = re.sub(r"\bfor (women|men|all skin types|home|office|gym)\b.*", "", t, flags=re.I)

    # Phone cases: keep brand + exact model + case name/color.
    model = extract_phone_model(t)
    if model:
        b = brand_tokens(t)
        first_brand = b[0] if b else ""
        case_words = []
        for key in ["santa cruz", "crystal palace", "milan", "denali", "defender", "plasma", "mirror", "halo", "magsafe", "kickstand"]:
            if key in normalize(t):
                case_words.append(key)
        color_match = re.search(r"\b(black|blue|clear|lilac|smoke|gold|green|red|pink|white)\b", t, flags=re.I)
        color = color_match.group(0) if color_match else ""
        pieces = [first_brand, " ".join(case_words), model, "case", color]
        return " ".join([p for p in pieces if p]).strip()

    # Otherwise limit to first meaningful chunk before long marketing copy.
    t = re.split(r"\s+-\s+|\s+\|\s+", t)[0]
    words = t.split()
    return " ".join(words[:12])


def title_matches(product_name: str, sold_title: str):
    """
    Conservative filter: reject obvious wrong comps.
    """
    p = normalize(product_name)
    s = normalize(sold_title)

    if not s or "shop on ebay" in s:
        return False

    bad_words_global = [
        "empty bottle", "empty box", "box only", "for parts", "not working",
        "broken", "damaged", "read description", "replacement part",
    ]
    if any(w in s for w in bad_words_global):
        return False

    # Phone case mode
    phone_model = extract_phone_model(p)
    if phone_model:
        if phone_model not in s:
            return False
        if "case" not in s and "cover" not in s:
            return False

        # Require brand when product has a known case brand.
        p_brands = [b for b in brand_tokens(p) if b in ["zagg", "otterbox", "uag", "casetify", "incase"]]
        if p_brands and not any(b in s for b in p_brands):
            return False

        reject_case_words = ["screen protector", "glass protector", "lens protector", "camera protector", "skin sticker"]
        if any(w in s for w in reject_case_words):
            return False

        return True

    # Fragrance/skincare/product size mode
    p_sizes = extract_size_tokens(p)
    s_sizes = extract_size_tokens(s)
    if p_sizes:
        # If sold title shows a size, it must overlap. If it shows no size, allow but score later.
        if s_sizes and not (p_sizes & s_sizes):
            return False

    # Require at least one brand token if found in product.
    p_brands = brand_tokens(p)
    if p_brands and not any(b in s for b in p_brands):
        return False

    # Token overlap sanity check
    p_tokens = [w for w in p.split() if len(w) >= 4]
    important = p_tokens[:8]
    if important:
        overlap = sum(1 for w in important if w in s)
        if overlap < max(1, min(3, len(important)//3)):
            return False

    return True


def score_match(product_name: str, sold_title: str):
    p = normalize(product_name)
    s = normalize(sold_title)

    score = 0

    for b in brand_tokens(p):
        if b in s:
            score += 5

    phone_model = extract_phone_model(p)
    if phone_model and phone_model in s:
        score += 10

    p_sizes = extract_size_tokens(p)
    s_sizes = extract_size_tokens(s)
    if p_sizes and s_sizes and (p_sizes & s_sizes):
        score += 8

    for token in set([w for w in p.split() if len(w) >= 4]):
        if token in s:
            score += 1

    return score


def fetch_ebay_solds(product_name: str, max_results: int = 30):
    search_term = clean_search_term(product_name)
    url = (
        "https://www.ebay.com/sch/i.html?"
        f"_nkw={urllib.parse.quote(search_term)}"
        "&LH_ItemCondition=1000"
        "&LH_Sold=1&LH_Complete=1"
        "&LH_BIN=1"
        "&_sop=13&rt=nc"
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }

    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    comps = []
    for item in soup.select("li.s-item"):
        title_el = item.select_one(".s-item__title")
        price_el = item.select_one(".s-item__price")
        link_el = item.select_one("a.s-item__link")

        if not title_el or not price_el:
            continue

        title = title_el.get_text(" ", strip=True)
        price = parse_money(price_el.get_text(" ", strip=True))
        link = link_el.get("href") if link_el else ""

        if price is None:
            continue

        # Keep wide enough range, but eliminate page artifacts.
        if price < 1 or price > 2000:
            continue

        if not title_matches(product_name, title):
            continue

        comps.append({
            "title": title,
            "price": price,
            "score": score_match(product_name, title),
            "link": link
        })

    comps = sorted(comps, key=lambda x: x["score"], reverse=True)
    return comps[:max_results], url, search_term


def trimmed_average(values):
    if not values:
        return None
    values = sorted(values)
    if len(values) >= 8:
        trim = max(1, int(len(values) * 0.15))
        values = values[trim:-trim]
    return sum(values) / len(values)


# -------------------------
# UI
# -------------------------

with st.sidebar:
    st.header("⚙️ Settings")
    default_shipping = st.slider("Default shipping $", 3.00, 15.00, 5.50, 0.50)
    phone_case_shipping = st.slider("Phone case shipping $", 3.00, 10.00, 4.50, 0.50)
    fragrance_shipping = st.slider("Fragrance shipping $", 4.00, 12.00, 6.00, 0.50)
    ebay_fee = st.slider("eBay fee %", 8.0, 16.0, 13.25, 0.05)
    minimum_profit = st.slider("Minimum profit $", 0.00, 50.00, 4.00, 0.50)
    delay = st.slider("Delay between searches sec", 0.0, 3.0, 1.0, 0.25)

st.markdown("### 📥 Paste Products")
pasted_text = st.text_area(
    "Format: Product title with size | buy cost",
    height=260,
    placeholder="Zagg Santa Cruz Snap Case with MagSafe for iPhone 16 Pro - Blue | 5.5"
)

products, skipped = parse_input_lines(pasted_text) if pasted_text.strip() else ([], [])

if skipped:
    st.warning(f"Skipped {len(skipped)} invalid lines. Make sure each line is: title | cost")

if products:
    st.success(f"Ready to analyze {len(products)} products.")

    if st.button("🚀 Start eBay Sold Comp Analysis", use_container_width=True):
        results = []
        progress = st.progress(0)
        status = st.empty()
        table = st.empty()

        for idx, product in enumerate(products):
            name = product["product_name"]
            cost = product["buy_cost"]

            status.write(f"Analyzing {idx+1}/{len(products)}: {name[:90]}")

            try:
                comps, search_url, search_term = fetch_ebay_solds(name)
                prices = [c["price"] for c in comps]

                if prices:
                    avg_price = trimmed_average(prices)
                    med_price = median(prices)

                    n = normalize(name)
                    if extract_phone_model(n):
                        shipping = phone_case_shipping
                    elif any(word in n for word in ["eau de", "cologne", "parfum", "perfume", "toilette", "fragrance"]):
                        shipping = fragrance_shipping
                    else:
                        shipping = default_shipping

                    fees = avg_price * (ebay_fee / 100)
                    net = avg_price - fees - shipping
                    profit = net - cost
                    margin = profit / cost * 100 if cost else 0

                    status_label = "✓ BUY" if profit >= minimum_profit else "✗ SKIP"

                    matched = " || ".join([f"${c['price']:.2f} — {c['title'][:95]}" for c in comps[:5]])

                    results.append({
                        "Product": name,
                        "Buy Cost": round(cost, 2),
                        "Search Term": search_term,
                        "Avg Sold": round(avg_price, 2),
                        "Median Sold": round(med_price, 2),
                        "Comps Used": len(prices),
                        "Shipping": round(shipping, 2),
                        "eBay Fees": round(fees, 2),
                        "Net Revenue": round(net, 2),
                        "Profit": round(profit, 2),
                        "Margin %": round(margin, 1),
                        "Status": status_label,
                        "Matched Sold Titles": matched,
                        "Search URL": search_url,
                    })
                else:
                    results.append({
                        "Product": name,
                        "Buy Cost": round(cost, 2),
                        "Search Term": search_term,
                        "Avg Sold": "NO DATA",
                        "Median Sold": "NO DATA",
                        "Comps Used": 0,
                        "Shipping": "",
                        "eBay Fees": "",
                        "Net Revenue": "",
                        "Profit": "NO DATA",
                        "Margin %": "NO DATA",
                        "Status": "NO SOLD COMPS",
                        "Matched Sold Titles": "",
                        "Search URL": search_url,
                    })

            except Exception as e:
                results.append({
                    "Product": name,
                    "Buy Cost": round(cost, 2),
                    "Status": f"ERROR: {str(e)[:100]}",
                })

            table.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
            progress.progress((idx + 1) / len(products))
            time.sleep(delay)

        st.markdown("### ✅ Done")

        df = pd.DataFrame(results)

        if not df.empty and "Status" in df.columns:
            buy_count = sum(df["Status"].astype(str).str.contains("BUY", na=False))
            st.metric("BUY items", f"{buy_count}/{len(df)}")

        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="eBay Profit Results", index=False)
            ws = writer.sheets["eBay Profit Results"]
            for col in ws.columns:
                max_len = min(70, max(len(str(cell.value)) if cell.value is not None else 0 for cell in col) + 2)
                ws.column_dimensions[col[0].column_letter].width = max_len

        output.seek(0)
        st.download_button(
            "📥 Download Excel Report",
            data=output,
            file_name="ebay_profit_analysis.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

else:
    st.info("Paste products above to begin.")
