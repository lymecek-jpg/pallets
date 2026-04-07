import streamlit as st
import pandas as pd

st.set_page_config(page_title="Optimalizace nakládky palet", layout="wide")
st.title("Optimalizace nakládky palet")

# --- Constants ---
MAX_HEIGHT_MM = 1200
FIRST_LADDER_MM = 50
NESTED_ADDITION_MM = 25
max_per_stack = int((MAX_HEIGHT_MM - FIRST_LADDER_MM) / NESTED_ADDITION_MM) + 1

# --- File Upload ---
uploaded_file = st.file_uploader("Nahrajte soubor objednávek (Excel / CSV)", type=["xlsx", "xls", "csv"])

if uploaded_file:
    try:
        # 1. Read file
        if uploaded_file.name.endswith(".csv"):
            try:
                df = pd.read_csv(uploaded_file, header=None, encoding="utf-8")
            except UnicodeDecodeError:
                uploaded_file.seek(0)
                df = pd.read_csv(uploaded_file, header=None, encoding="cp1250")
        else:
            df = pd.read_excel(uploaded_file, header=None)

        # 2. Find "Zakázka" header row
        zakazka_row_index = -1
        for index in range(min(15, len(df))):
            row_text = df.iloc[index].tolist()
            if any("zak" in str(text).lower() for text in row_text):
                zakazka_row_index = index
                break

        if zakazka_row_index == -1:
            st.error("Řádek s hlavičkou 'Zakázka' nebyl nalezen v prvních 15 řádcích.")
            st.stop()

        # 3. Extract order columns
        order_columns = {}
        for col_idx in range(len(df.columns)):
            val = str(df.iloc[zakazka_row_index, col_idx]).strip()
            if val.lower() not in ["nan", "", "zakázka", "celkem", "celkem příček"] and "zak" not in val.lower():
                order_columns[col_idx] = val

        if not order_columns:
            st.error("V řádku hlavičky nebyly nalezeny žádné sloupce zakázek.")
            st.stop()

        # 4. Parse rows
        orders_dict = {}
        loose_ladders = []

        for row_idx in range(zakazka_row_index + 1, len(df)):
            steps_val = df.iloc[row_idx, 2]
            try:
                steps = float(steps_val)
                if pd.isna(steps):
                    continue
            except (ValueError, TypeError):
                continue

            for col_idx, order_name in order_columns.items():
                qty_val = df.iloc[row_idx, col_idx]
                try:
                    qty = int(float(qty_val))
                    if qty > 0:
                        if steps == 2:
                            loose_ladders.append({"Order": order_name, "Steps": 2, "Quantity": qty})
                        else:
                            if order_name not in orders_dict:
                                orders_dict[order_name] = []
                            while qty > 0:
                                pack_size = min(qty, 5)
                                orders_dict[order_name].append({
                                    "Order": order_name,
                                    "Steps": int(steps),
                                    "Size": pack_size,
                                })
                                qty -= pack_size
                except (ValueError, TypeError):
                    pass

        # 5. Pallet packing
        pallets = []

        for order_name, pack_list in orders_dict.items():
            pack_list.sort(key=lambda x: (x["Steps"], x["Size"]), reverse=True)
            current_left, current_mid, current_right = [], [], []

            for pack in pack_list:
                stacks = [("L", current_left), ("R", current_right), ("M", current_mid)]
                stacks.sort(key=lambda x: (len(x[1]), x[0] == "M"))

                placed = False
                for name, stack in stacks:
                    if len(stack) + pack["Size"] <= max_per_stack:
                        for _ in range(pack["Size"]):
                            stack.append({"Order": pack["Order"], "Steps": pack["Steps"]})
                        placed = True
                        break

                if not placed:
                    pallets.append({"L": current_left, "M": current_mid, "R": current_right, "Order": order_name})
                    current_left, current_mid, current_right = [], [], []
                    for _ in range(pack["Size"]):
                        current_left.append({"Order": pack["Order"], "Steps": pack["Steps"]})

            if current_left or current_mid or current_right:
                pallets.append({"L": current_left, "M": current_mid, "R": current_right, "Order": order_name})

        # 6. Helper to group a stack into packs
        def get_packs(stack):
            if not stack:
                return []
            res = []
            curr = {"Order": stack[0]["Order"], "Steps": stack[0]["Steps"], "Count": 1}
            for i in range(1, len(stack)):
                if stack[i] == stack[i - 1] and curr["Count"] < 5:
                    curr["Count"] += 1
                else:
                    res.append(curr)
                    curr = {"Order": stack[i]["Order"], "Steps": stack[i]["Steps"], "Count": 1}
            res.append(curr)
            return res

        # 7. Display results
        st.success(f"Balení dokončeno — vygenerováno {len(pallets)} palet.")

        for p_idx, p in enumerate(pallets):
            l_packs = get_packs(p["L"])
            m_packs = get_packs(p["M"])
            r_packs = get_packs(p["R"])

            with st.expander(f"Paleta #{p_idx + 1}  —  Zakázka: {p['Order']}", expanded=True):
                # Visual map as a table
                max_d = max(len(l_packs), len(m_packs), len(r_packs), 1)
                rev_l = list(reversed(l_packs))
                rev_m = list(reversed(m_packs))
                rev_r = list(reversed(r_packs))

                def fmt(lst, i, total):
                    offset = total - len(lst)
                    if i >= offset:
                        pk = lst[i - offset]
                        return f"{pk['Count']}x {pk['Steps']}-příčkový"
                    return ""

                visual_rows = []
                for i in range(max_d):
                    visual_rows.append({
                        "LEFT": fmt(rev_l, i, max_d),
                        "MIDDLE": fmt(rev_m, i, max_d),
                        "RIGHT": fmt(rev_r, i, max_d),
                    })

                st.markdown("**Vizuální mapa** (shora dolů)")
                visual_df = pd.DataFrame(visual_rows).rename(columns={"LEFT": "VLEVO", "MIDDLE": "UPROSTŘED", "RIGHT": "VPRAVO"})
                st.table(visual_df)

                # Detailed loading list
                st.markdown("**Pokyny k nakládce** (nakládejte zdola nahoru)")
                cols = st.columns(3)
                for col, label, packs, stack_key in zip(
                    cols,
                    ["VLEVO", "UPROSTŘED", "VPRAVO"],
                    [l_packs, m_packs, r_packs],
                    ["L", "M", "R"],
                ):
                    with col:
                        total = len(p[stack_key])
                        st.markdown(f"**{label}** ({total} žebříků)")
                        if packs:
                            for i, pk in enumerate(packs):
                                note = " ← spodní vrstva" if i == 0 else ""
                                st.write(f"{i+1}. {pk['Count']}x {pk['Steps']}-příčkový{note}")
                        else:
                            st.write("—")

        # Loose ladders
        if loose_ladders:
            st.markdown("---")
            st.markdown("### Volné žebříky (2-příčkové) — umístěte kdekoliv")
            loose_dict = {}
            for item in loose_ladders:
                loose_dict[item["Order"]] = loose_dict.get(item["Order"], 0) + item["Quantity"]
            for order_name, qty in loose_dict.items():
                st.write(f"- **{qty}x** 2-příčkové žebříky  (Zakázka: {order_name})")

    except Exception as e:
        st.error(f"Chyba při zpracování souboru: {e}")
