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

st.title("📊 eBay Profit Analyzer")
st.markdown(
    "Paste products as **Product title | buy cost**. "
    "This version reads both old eBay result cards (`s-item`) and newer eBay result cards (`s-card`). "
    "It does **not** invent fallback sold prices."
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

        # Split on LAST pipe so titles may contain pipes.
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
    matches = re.findall(r"\$\s*(\d+(?:\.\d{1,2})?)", cleaned)
    if not matches:
        return None
    try:
        return float(matches[0])
    except ValueError:
        return None


def normalize(text: str):
    text = str(text).lower()
    text = text.replace("’", "'").replace("–", "-").replace("—", "-")
    text = re.sub(r"[^a-z0-9\s\.\-\/]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compact(text: str):
    return re.sub(r"[^a-z0-9]+", "", normalize(text))


def extract_phone_model(text: str):
    t = normalize(text)
    patterns = [
        ("iphone 16 pro max", [r"iphone\s*16\s*pro\s*max", r"iphone16promax"]),
        ("iphone 16 pro", [r"iphone\s*16\s*pro\b", r"iphone16pro\b"]),
        ("iphone 16 plus", [r"iphone\s*16\s*plus", r"iphone16plus"]),
        ("iphone 16", [r"iphone\s*16\b", r"iphone16\b"]),
        ("iphone 15 pro max", [r"iphone\s*15\s*pro\s*max", r"iphone15promax"]),
        ("iphone 15 pro", [r"iphone\s*15\s*pro\b", r"iphone15pro\b"]),
        ("iphone 15 plus", [r"iphone\s*15\s*plus", r"iphone15plus"]),
        ("iphone 15", [r"iphone\s*15\b", r"iphone15\b"]),
        ("iphone 14 pro max", [r"iphone\s*14\s*pro\s*max", r"iphone14promax"]),
        ("iphone 14 pro", [r"iphone\s*14\s*pro\b", r"iphone14pro\b"]),
        ("iphone 14 plus", [r"iphone\s*14\s*plus", r"iphone14plus"]),
        ("iphone 14", [r"iphone\s*14\b", r"iphone14\b"]),
        ("iphone 13 pro max", [r"iphone\s*13\s*pro\s*max", r"iphone13promax"]),
        ("iphone 13 pro", [r"iphone\s*13\s*pro\b", r"iphone13pro\b"]),
        ("iphone 13 mini", [r"iphone\s*13\s*mini", r"iphone13mini"]),
        ("iphone 13", [r"iphone\s*13\b", r"iphone13\b"]),
    ]

    tc = compact(text)
    for label, pats in patterns:
        for pat in pats:
            if re.search(pat, t) or re.search(pat, tc):
                return label
    return None


def model_matches(product_model: str, sold_title: str):
    if not product_model:
        return True
    return compact(product_model) in compact(sold_title)


def extract_size_tokens(text: str):
    t = normalize(text)
    tokens = set()

    for m in re.findall(r"(\d+(?:\.\d+)?)\s*(?:fl\s*)?oz", t):
        tokens.add(f"{float(m):g} oz")

    for m in re.findall(r"(\d+(?:\.\d+)?)\s*ml", t):
        tokens.add(f"{float(m):g} ml")

    for m in re.findall(r"(\d+)\s*gb", t):
        tokens.add(f"{m} gb")

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
    return [normalize(b) for b in brands if normalize(b) in t]


def clean_search_term(product_name: str):
    t = re.sub(r"\|\s*verizon", "", product_name, flags=re.I)
    t = re.sub(r"\bwith notes of\b.*", "", t, flags=re.I)

    model = extract_phone_model(t)
    if model:
        b = brand_tokens(t)
        first_brand = b[0] if b else ""

        n = normalize(t)
        case_words = []
        for key in [
            "santa cruz", "crystal palace", "milan", "denali",
            "defender", "plasma", "mirror", "halo", "magsafe",
            "kickstand", "otterbox", "uag", "zagg", "casetify", "incase"
        ]:
            if key in n:
                case_words.append(key)

        # Do NOT force the word "case" only; some eBay listings say cover.
        pieces = [first_brand, " ".join(case_words), model]
        return " ".join([p for p in pieces if p]).strip()

    t = re.split(r"\s+-\s+|\s+\|\s+", t)[0]
    return " ".join(t.split()[:12])


def title_matches(product_name: str, sold_title: str):
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

    phone_model = extract_phone_model(p)
    if phone_model:
        if not model_matches(phone_model, sold_title):
            return False

        if ("case" not in s) and ("cover" not in s):
            return False

        p_brands = [b for b in brand_tokens(p) if b in ["zagg", "otterbox", "uag", "casetify", "incase"]]
        if p_brands and not any(b in s for b in p_brands):
            return False

        reject_case_words = [
            "screen protector", "glass protector", "lens protector",
            "camera protector", "skin sticker", "tempered glass"
        ]
        if any(w in s for w in reject_case_words):
            return False

        return True

    p_sizes = extract_size_tokens(p)
    s_sizes = extract_size_tokens(s)
    if p_sizes and s_sizes and not (p_sizes & s_sizes):
        return False

    p_brands = brand_tokens(p)
    if p_brands and not any(b in s for b in p_brands):
        return False

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
            score += 8

    phone_model = extract_phone_model(p)
    if phone_model and model_matches(phone_model, sold_title):
        score += 15

    p_sizes = extract_size_tokens(p)
    s_sizes = extract_size_tokens(s)
    if p_sizes and s_sizes and (p_sizes & s_sizes):
        score += 10

    for token in set([w for w in p.split() if len(w) >= 4]):
        if token in s:
            score += 1

    return score


def get_card_text(card):
    return card.get_text(" ", strip=True)


def extract_old_s_item_cards(soup):
    cards = []
    for item in soup.select("li.s-item"):
        title_el = item.select_one(".s-item__title")
        price_el = item.select_one(".s-item__price")
        link_el = item.select_one("a.s-item__link")

        title = title_el.get_text(" ", strip=True) if title_el else ""
        price = parse_money(price_el.get_text(" ", strip=True)) if price_el else None
        link = link_el.get("href") if link_el else ""

        if title and price is not None:
            cards.append({"title": title, "price": price, "link": link, "format": "s-item"})
    return cards


def extract_new_s_card_cards(soup):
    """
    Handles newer eBay card layouts that use s-card / su-styled-text classes.
    This is the layout your copied eBay data appears to come from.
    """
    cards = []

    # Find item links first, then walk up to a card container.
    links = soup.select('a[href*="/itm/"]')
    seen = set()

    for link_el in links:
        href = link_el.get("href", "")
        if not href or href in seen:
            continue
        seen.add(href)

        card = link_el
        for _ in range(8):
            if not card.parent:
                break
            card = card.parent
            classes = " ".join(card.get("class", []))
            if ("s-card" in classes) or ("s-item" in classes) or card.name in ["li", "article"]:
                break

        text = get_card_text(card)

        # Try class-based title first.
        title = ""
        for sel in [
            ".s-card__title",
            ".s-item__title",
            "[class*='title']",
            "[class*='styled-text']",
        ]:
            el = card.select_one(sel)
            if el:
                candidate = el.get_text(" ", strip=True)
                if candidate and "$" not in candidate and len(candidate) > 8:
                    title = candidate
                    break

        # Fallback: use link text if it looks like a product title.
        if not title:
            candidate = link_el.get_text(" ", strip=True)
            if candidate and "$" not in candidate and len(candidate) > 8:
                title = candidate

        # Price: look inside the card text for dollar amounts.
        price = None
        dollar_values = re.findall(r"\$\s*\d+(?:,\d{3})*(?:\.\d{1,2})?", text)
        if dollar_values:
            # On eBay cards, the sold price is usually the first dollar amount in the card text.
            price = parse_money(dollar_values[0])

        if title and price is not None:
            cards.append({"title": title, "price": price, "link": href, "format": "s-card"})

    return cards


def fetch_ebay_solds(product_name: str, max_results: int = 30, debug=False):
    search_term = clean_search_term(product_name)

    # Completed/sold/BIN/new
    url = (
        "https://www.ebay.com/sch/i.html?"
        f"_nkw={urllib.parse.quote(search_term)}"
        "&LH_ItemCondition=1000"
        "&LH_Sold=1&LH_Complete=1"
        "&LH_BIN=1"
        "&_sop=13&rt=nc"
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    r = requests.get(url, headers=headers, timeout=25)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    raw_cards = []
    raw_cards.extend(extract_old_s_item_cards(soup))
    raw_cards.extend(extract_new_s_card_cards(soup))

    # Deduplicate by title/price.
    unique = []
    seen = set()
    for c in raw_cards:
        key = (normalize(c["title"]), c["price"])
        if key not in seen:
            seen.add(key)
            unique.append(c)

    comps = []
    rejected_examples = []

    for card in unique:
        title = card["title"]
        price = card["price"]

        if price < 1 or price > 2000:
            continue

        if title_matches(product_name, title):
            comps.append({
                "title": title,
                "price": price,
                "score": score_match(product_name, title),
                "link": card["link"],
                "format": card["format"],
            })
        elif len(rejected_examples) < 5:
            rejected_examples.append(f"${price:.2f} — {title[:110]}")

    comps = sorted(comps, key=lambda x: x["score"], reverse=True)

    debug_info = {
        "raw_card_count": len(unique),
        "raw_examples": " || ".join([f"${c['price']:.2f} — {c['title'][:90]}" for c in unique[:5]]),
        "rejected_examples": " || ".join(rejected_examples),
        "html_length": len(r.text),
    }

    return comps[:max_results], url, search_term, debug_info


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
    show_debug = st.checkbox("Show scraper debug columns", value=True)

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
                comps, search_url, search_term, debug_info = fetch_ebay_solds(name, debug=show_debug)
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

                    row = {
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
                    }
                else:
                    row = {
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
                    }

                if show_debug:
                    row["Raw Cards Found"] = debug_info["raw_card_count"]
                    row["Raw Examples"] = debug_info["raw_examples"]
                    row["Rejected Examples"] = debug_info["rejected_examples"]
                    row["HTML Length"] = debug_info["html_length"]

                results.append(row)

            except Exception as e:
                results.append({
                    "Product": name,
                    "Buy Cost": round(cost, 2),
                    "Status": f"ERROR: {str(e)[:120]}",
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
                max_len = min(80, max(len(str(cell.value)) if cell.value is not None else 0 for cell in col) + 2)
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
