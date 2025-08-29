import streamlit as st
import pandas as pd
import io, os
from io import StringIO

APP_TITLE = "Kindrette Carpentry Quote Tool"
st.set_page_config(page_title=APP_TITLE, layout="wide")

# ---- Data inputs (uploads or bundled files) ----
st.sidebar.subheader("Data (upload or use bundled CSVs)")
a_up = st.sidebar.file_uploader("Alpha price list (CSV)", type="csv", key="alpha_upload")
b_up = st.sidebar.file_uploader("Ben price list (CSV)", type="csv", key="ben_upload")

# Manual refresh button to bust cache on demand
if st.sidebar.button("🔄 Refresh catalogs"):
    st.cache_data.clear()
    st.experimental_rerun()

def _validate_columns(df, who):
    cols = {c.lower() for c in df.columns}
    required = {"sku", "description", "unit", "price"}
    if not required.issubset(cols):
        missing = ", ".join(sorted(required - cols))
        raise ValueError(f"{who} is missing required columns: {missing}")

@st.cache_data(show_spinner=False)
def load_catalogs_from_tokens(a_token: bytes, b_token: bytes, use_uploads: bool):
    """
    a_token/b_token:
      - when using uploads: the raw file bytes
      - when using bundled files: a bytes-encoded mtime string to re-key cache on file change
    """
    if use_uploads:
        a = pd.read_csv(io.BytesIO(a_token))
        b = pd.read_csv(io.BytesIO(b_token))
    else:
        a = pd.read_csv("supplier_a.csv")
        b = pd.read_csv("supplier_b.csv")

    # normalize columns
    a.columns = [c.lower() for c in a.columns]
    b.columns = [c.lower() for c in b.columns]
    _validate_columns(a, "Alpha (supplier_a.csv)")
    _validate_columns(b, "Ben (supplier_b.csv)")
    return a, b

# Build cache tokens
use_uploads = a_up is not None and b_up is not None
if use_uploads:
    a_token = a_up.getvalue()
    b_token = b_up.getvalue()
else:
    a_mtime = os.path.getmtime("supplier_a.csv") if os.path.exists("supplier_a.csv") else 0
    b_mtime = os.path.getmtime("supplier_b.csv") if os.path.exists("supplier_b.csv") else 0
    a_token = str(a_mtime).encode()  # using mtime to invalidate cache when file changes
    b_token = str(b_mtime).encode()

# Load catalogs (cache depends on tokens)
try:
    a_df, b_df = load_catalogs_from_tokens(a_token, b_token, use_uploads)
except Exception as e:
    st.error(f"Problem loading catalogs: {e}")
    st.stop()

def choose_suffix(home: str, laminate: str) -> str:
    h = (home or "").strip().lower()
    lam = (laminate or "").strip().lower()
    if h in ("condo", "landed", "condo/landed", "condo_landed"):
        return "CONDO"
    return "SNS" if lam == "sns" else "HDB"

def sell_from_margin(cost: float, margin_pct: float) -> float:
    # Sell = Cost / (1 - Margin)
    if margin_pct >= 100:
        return float("nan")
    return cost / (1 - margin_pct/100.0)

# -------- Sidebar controls --------
st.sidebar.header("Filters")
supplier_label = st.sidebar.selectbox("Supplier", ["A (Alpha)", "B (Ben)"])
home = st.sidebar.selectbox("Home", ["", "hdb", "condo", "landed"])
laminate = st.sidebar.selectbox("Laminate", ["", "standard", "sns"])

st.sidebar.header("Pricing (margin only)")
margin_pct = st.sidebar.number_input("Target margin (%)", value=25.0, min_value=0.0, max_value=99.0, step=1.0)
tax_rate = st.sidebar.number_input("Tax / GST (%)", value=9.0, min_value=0.0, max_value=100.0, step=0.1)
currency = st.sidebar.text_input("Currency", "SGD")
round_nd = st.sidebar.number_input("Round to decimals", value=2, min_value=0, max_value=4, step=1)

# -------- Catalog view --------
st.title(APP_TITLE)
st.write("Pick items, set quantities, then export to **items.csv** for the PDF quoting tool. Totals use your target margin and GST.")

supplier_code = "A" if supplier_label.startswith("A") else "B"
if supplier_code == "A":
    browse_df = a_df.copy()
else:
    suffix = choose_suffix(home, laminate)
    browse_df = b_df[b_df["sku"].str.upper().str.endswith("-" + suffix)].copy() if (home or laminate) else b_df.copy()

q = st.text_input("Search description or SKU")
if q:
    ql = q.lower()
    browse_df = browse_df[
        browse_df["description"].str.lower().str.contains(ql) |
        browse_df["sku"].str.lower().str.contains(ql)
    ]

st.subheader("Catalog")
st.dataframe(browse_df[["sku", "description", "unit", "price"]], use_container_width=True, height=320)

st.divider()
st.subheader("Add line")

sku = st.selectbox("SKU", options=browse_df["sku"].tolist() if len(browse_df) else [])
qty = st.number_input("Quantity", min_value=0.0, value=1.0, step=1.0)
override_unit_sell = st.text_input("Override unit sell (optional)")

home_val = home if supplier_code == "B" else ""
lam_val = laminate if supplier_code == "B" else ""

if "lines" not in st.session_state:
    st.session_state.lines = []

def add_line():
    if not sku:
        return
    st.session_state.lines.append({
        "sku": sku,
        "supplier": supplier_code,
        "qty": qty,
        "override_unit_sell": override_unit_sell.strip(),
        "home": home_val,
        "laminate": lam_val
    })

st.button("Add to list", on_click=add_line)

# -------- Current selections with Remove/Clear --------
st.subheader("Current selections")

# Drop lines no longer valid after a catalog change
valid_skus = set(a_df["sku"].astype(str)).union(set(b_df["sku"].astype(str)))
if st.session_state.lines:
    before = len(st.session_state.lines)
    st.session_state.lines = [ln for ln in st.session_state.lines if str(ln.get("sku","")) in valid_skus]
    removed = before - len(st.session_state.lines)
    if removed > 0:
        st.warning(f"Removed {removed} outdated selection(s) because the catalog changed.")

if not st.session_state.lines:
    st.info("No items yet. Add some above.")
else:
    # Header row
    h1, h2, h3, h4, h5, h6, h7 = st.columns([3, 1, 1, 1.2, 1.2, 1.6, 0.9])
    h1.write("**SKU**"); h2.write("**Sup**"); h3.write("**Qty**"); h4.write("**Home**"); h5.write("**Laminate**"); h6.write("**Override sell**"); h7.write("")

    to_delete = None
    for idx, line in enumerate(st.session_state.lines):
        c1, c2, c3, c4, c5, c6, c7 = st.columns([3, 1, 1, 1.2, 1.2, 1.6, 0.9])
        c1.write(line.get("sku",""))
        c2.write(line.get("supplier",""))
        c3.write(f'{line.get("qty","")}')
        c4.write(line.get("home",""))
        c5.write(line.get("laminate",""))
        c6.write(line.get("override_unit_sell",""))
        if c7.button("🗑 Remove", key=f"rm_{idx}"):
            to_delete = idx

    if to_delete is not None:
        st.session_state.lines.pop(to_delete)
        st.experimental_rerun()

    if st.button("Clear all selections"):
        st.session_state.lines = []
        st.experimental_rerun()

    sel_df = pd.DataFrame(st.session_state.lines)
    st.dataframe(sel_df, use_container_width=True)

    # ----- pricing & totals (margin-only) -----
    def lookup_cost(row):
        df = a_df if row["supplier"] == "A" else b_df
        hit = df[df["sku"] == row["sku"]]
        return float(hit["price"].iloc[0]) if not hit.empty else float("nan")

    priced = sel_df.copy()
    priced["qty"] = pd.to_numeric(priced["qty"], errors="coerce").fillna(0.0)
    priced["cost"] = priced.apply(lookup_cost, axis=1)

    def calc_unit_sell(row):
        if row.get("override_unit_sell"):
            try:
                return float(row["override_unit_sell"])
            except Exception:
                return float("nan")
        return sell_from_margin(float(row["cost"]), margin_pct)

    priced["unit_sell"] = priced.apply(calc_unit_sell, axis=1)
    priced["line_total"] = (priced["unit_sell"] * priced["qty"]).round(round_nd)

    subtotal = float(priced["line_total"].sum())
    tax = round(subtotal * (tax_rate/100.0), round_nd)
    total = round(subtotal + tax, round_nd)

    def fmt(x): return f"{x:,.{int(round_nd)}f}"
    col1, col2, col3 = st.columns(3)
    col1.metric("Subtotal", f"{currency} {fmt(subtotal)}")
    col2.metric(f"Tax ({tax_rate:.1f}%)", f"{currency} {fmt(tax)}")
    col3.metric("Estimated total (incl. tax)", f"{currency} {fmt(total)}")

    st.markdown("**Itemized pricing (estimated)**")
    show_cols = ["sku","supplier","qty","cost","unit_sell","line_total","home","laminate"]
    st.dataframe(priced[show_cols], use_container_width=True, height=300)

    # Downloads
    headers = ["sku","supplier","qty","override_unit_sell","home","laminate"]
    csv_buf = StringIO()
    sel_df.reindex(columns=headers).to_csv(csv_buf, index=False)
    st.download_button("Download items.csv", csv_buf.getvalue(), file_name="items.csv", mime="text/csv")

    cb = StringIO()
    priced[show_cols].to_csv(cb, index=False)
    st.download_button("Download cost_breakdown.csv", cb.getvalue(), file_name="cost_breakdown.csv", mime="text/csv")
