import tkinter as tk
from tkinter import filedialog
import pandas as pd
import math

# --- Function to handle file selection and reading ---
def select_file():
    filepath = filedialog.askopenfilename(
        title="Select Order Excel File",
        filetypes=(("Excel files", "*.xlsx *.xls"), ("CSV files", "*.csv"), ("All files", "*.*"))
    )
    
    if filepath:
        file_label.config(text=f"Selected: {filepath}")
        status_label.config(text="Status: Loading data...", fg="blue")
        output_box.delete(1.0, tk.END) 
        root.update() 
        
        try:
            # 1. Read the file safely
            if filepath.endswith('.csv'):
                try:
                    df = pd.read_csv(filepath, header=None, encoding='utf-8')
                except UnicodeDecodeError:
                    df = pd.read_csv(filepath, header=None, encoding='cp1250')
            else:
                df = pd.read_excel(filepath, header=None)
            
            # 2. Hunt for the "Zakázka" (Orders) row safely
            zakazka_row_index = -1
            for index in range(min(15, len(df))): 
                row_text = df.iloc[index].tolist() 
                if any('zak' in str(text).lower() for text in row_text):
                    zakazka_row_index = index
                    break
            
            # 3. Extract and group by ORDER
            if zakazka_row_index != -1:
                order_columns = {}
                for col_idx in range(len(df.columns)):
                    val = str(df.iloc[zakazka_row_index, col_idx]).strip()
                    if val.lower() not in ['nan', '', 'zakázka', 'celkem', 'celkem příček'] and 'zak' not in val.lower():
                        order_columns[col_idx] = val
                
                # --- NEW: Dictionary to keep orders completely separate ---
                orders_dict = {} 
                loose_ladders = []
                
                for row_idx in range(zakazka_row_index + 1, len(df)):
                    steps_val = df.iloc[row_idx, 2] 
                    try:
                        steps = float(steps_val)
                        if pd.isna(steps): continue
                    except (ValueError, TypeError):
                        continue 
                        
                    for col_idx, order_name in order_columns.items():
                        qty_val = df.iloc[row_idx, col_idx]
                        try:
                            qty = int(float(qty_val))
                            if qty > 0: 
                                if steps == 2:
                                    loose_ladders.append({'Order': order_name, 'Steps': 2, 'Quantity': qty})
                                else:
                                    if order_name not in orders_dict:
                                        orders_dict[order_name] = []
                                    # Group into 5-packs
                                    while qty > 0:
                                        pack_size = min(qty, 5)
                                        orders_dict[order_name].append({
                                            'Order': order_name,
                                            'Steps': int(steps),
                                            'Size': pack_size
                                        })
                                        qty -= pack_size
                        except (ValueError, TypeError): pass 

                # --- PALLET PACKING MATH (STRICTLY BY ORDER) ---
                MAX_HEIGHT_MM = 1200
                FIRST_LADDER_MM = 50
                NESTED_ADDITION_MM = 25 
                max_per_stack = int((MAX_HEIGHT_MM - FIRST_LADDER_MM) / NESTED_ADDITION_MM) + 1
                
                pallets = []
                
                # Process ONE order at a time
                for order_name, pack_list in orders_dict.items():
                    # Sort packs for THIS order (Longest on bottom)
                    pack_list.sort(key=lambda x: (x['Steps'], x['Size']), reverse=True)
                    
                    current_left, current_mid, current_right = [], [], []
                    
                    for pack in pack_list:
                        stacks = [('L', current_left), ('R', current_right), ('M', current_mid)]
                        stacks.sort(key=lambda x: (len(x[1]), x[0] == 'M'))
                        
                        placed = False
                        for name, stack in stacks:
                            if len(stack) + pack['Size'] <= max_per_stack:
                                for _ in range(pack['Size']):
                                    stack.append({'Order': pack['Order'], 'Steps': pack['Steps']})
                                placed = True
                                break
                        
                        if not placed:
                            # Pallet for this order is full! Save it and grab a new one
                            pallets.append({'L': current_left, 'M': current_mid, 'R': current_right, 'Order': order_name})
                            current_left, current_mid, current_right = [], [], []
                            for _ in range(pack['Size']):
                                current_left.append({'Order': pack['Order'], 'Steps': pack['Steps']})

                    # Save the last pallet for this order
                    if current_left or current_mid or current_right:
                        pallets.append({'L': current_left, 'M': current_mid, 'R': current_right, 'Order': order_name})

                # --- DISPLAY MANIFEST ---
                output_box.insert(tk.END, f"--- PACKING COMPLETE: Generated {len(pallets)} Pallets! ---\n\n")
                
                for p_idx, p in enumerate(pallets):
                    # Display the Order Name clearly at the top of the Pallet!
                    output_box.insert(tk.END, f"🪵 PALLET #{p_idx + 1}   [ ORDER: {p['Order']} ]\n")
                    
                    def get_packs(stack):
                        if not stack: return []
                        res = []
                        curr = {'Order': stack[0]['Order'], 'Steps': stack[0]['Steps'], 'Count': 1}
                        for i in range(1, len(stack)):
                            if stack[i] == stack[i-1] and curr['Count'] < 5:
                                curr['Count'] += 1
                            else:
                                res.append(curr)
                                curr = {'Order': stack[i]['Order'], 'Steps': stack[i]['Steps'], 'Count': 1}
                        res.append(curr)
                        return res

                    l_packs, m_packs, r_packs = get_packs(p['L']), get_packs(p['M']), get_packs(p['R'])
                    
                    # ASCII Visualizer
                    max_d = max(len(l_packs), len(m_packs), len(r_packs), 1)
                    rev_l, rev_m, rev_r = list(reversed(l_packs)), list(reversed(m_packs)), list(reversed(r_packs))
                    
                    output_box.insert(tk.END, "   [ VISUAL MAP ]\n")
                    for i in range(max_d):
                        lt = f"[{rev_l[i-(max_d-len(rev_l))]['Count']}x {rev_l[i-(max_d-len(rev_l))]['Steps']}]" if i >= max_d-len(rev_l) else ""
                        mt = f"[{rev_m[i-(max_d-len(rev_m))]['Count']}x {rev_m[i-(max_d-len(rev_m))]['Steps']}]" if i >= max_d-len(rev_m) else ""
                        rt = f"[{rev_r[i-(max_d-len(rev_r))]['Count']}x {rev_r[i-(max_d-len(rev_r))]['Steps']}]" if i >= max_d-len(rev_r) else ""
                        output_box.insert(tk.END, f"   {lt:^18} {mt:^18} {rt:^18}\n")
                    output_box.insert(tk.END, "   " + "="*56 + "\n\n")

                    # Step-by-Step Instructions
                    output_box.insert(tk.END, "   [ DETAILED LOADING LIST (Load from Bottom to Top) ]\n")
                    for name, pk in [("LEFT", l_packs), ("MIDDLE", m_packs), ("RIGHT", r_packs)]:
                        if pk: # Only print stacks that actually have ladders
                            output_box.insert(tk.END, f"   [{name} STACK] ({len(p[name[0]])} ladders total)\n")
                            for i, pack in enumerate(pk):
                                note = " -- [BOTTOM LAYER]" if i == 0 else ""
                                output_box.insert(tk.END, f"    Step {i+1}: Load {pack['Count']}x ladders ({pack['Steps']} steps){note}\n")
                    output_box.insert(tk.END, "-"*64 + "\n")

                if loose_ladders:
                    output_box.insert(tk.END, f"\n📝 LOOSE LADDERS (2-step) - Place anywhere:\n")
                    # Group the loose ladders by order for cleaner reading
                    loose_dict = {}
                    for l in loose_ladders:
                        loose_dict[l['Order']] = loose_dict.get(l['Order'], 0) + l['Quantity']
                    for order_name, qty in loose_dict.items():
                        output_box.insert(tk.END, f"   -> {qty}x 2-step ladders (Order: {order_name})\n")

                status_label.config(text=f"Status: Successfully packed {len(pallets)} pallets strictly by order!", fg="green")
                
        except Exception as e:
            status_label.config(text=f"Status: Error loading file", fg="red")
            output_box.insert(tk.END, f"Error details: {e}")

# --- Main Window Setup ---
root = tk.Tk()
root.title("Pallet Loading App")
root.geometry("1000x800") 

# --- UI Elements ---
title_label = tk.Label(root, text="Pallet Loading Optimizer", font=("Arial", 16, "bold"))
title_label.pack(pady=10)

select_button = tk.Button(root, text="Load Excel File", command=select_file, font=("Arial", 12), bg="lightblue")
select_button.pack(pady=5)

file_label = tk.Label(root, text="No file selected yet...", font=("Arial", 10))
file_label.pack(pady=5)

status_label = tk.Label(root, text="Status: Waiting for file...", font=("Arial", 10, "italic"))
status_label.pack(pady=5)

# --- Dynamically Scaling Text Box ---
text_frame = tk.Frame(root)
text_frame.pack(pady=10, padx=20, expand=True, fill=tk.BOTH)

scrollbar = tk.Scrollbar(text_frame)
scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

output_box = tk.Text(text_frame, font=("Consolas", 11), bg="#f4f4f4", yscrollcommand=scrollbar.set)
output_box.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)

scrollbar.config(command=output_box.yview)

root.mainloop()