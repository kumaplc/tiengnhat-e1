import customtkinter as ctk
import pandas as pd
import threading
import os
import time
from tkinter import filedialog

# Cấu hình giao diện hiện đại
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("ALDC Export Tool")
        self.geometry("500x550")

        # Cấu hình ngôn ngữ
        self.ui_text = {
            "Vi": {"label": "Nhập Mã (注番):", "btn": "Chọn Excel & Xuất", "log_start": "Đang xử lý...", "log_done": "Hoàn thành trong", "err": "Không tìm thấy dữ liệu!"},
            "Jp": {"label": "注番を入力:", "btn": "Excel選択 & 出力", "log_start": "処理中...", "log_done": "完了しました。所要時間:", "err": "データが見つかりません！"}
        }

        # Giao diện
        self.label_ma = ctk.CTkLabel(self, text="Nhập Mã (注番):", font=("Arial", 14, "bold"))
        self.label_ma.pack(pady=(20, 5))
        
        self.entry_ma = ctk.CTkEntry(self, width=300, height=35)
        self.entry_ma.pack(pady=5)
        self.load_config() 
        
        self.lang_switch = ctk.CTkOptionMenu(self, values=["Vi", "Jp"], command=self.change_lang)
        self.lang_switch.pack(pady=10)
        
        self.btn_run = ctk.CTkButton(self, text="Chọn Excel & Xuất", command=self.start_thread, height=45, fg_color="#28a745")
        self.btn_run.pack(pady=20)
        
        self.log_box = ctk.CTkTextbox(self, width=400, height=200)
        self.log_box.pack(pady=10)

    def change_lang(self, lang):
        self.label_ma.configure(text=self.ui_text[lang]["label"])
        self.btn_run.configure(text=self.ui_text[lang]["btn"])

    def log(self, message):
        self.log_box.insert("end", message + "\n")
        self.log_box.see("end")

    def load_config(self):
        if os.path.exists("config.txt"):
            with open("config.txt", "r") as f:
                self.entry_ma.insert(0, f.read())

    def save_config(self, ma):
        with open("config.txt", "w") as f:
            f.write(ma)

    def start_thread(self):
        threading.Thread(target=self.process).start()

    def process(self):
        start_time = time.time()
        ma_so = self.entry_ma.get().strip()
        lang = self.lang_switch.get()
        self.save_config(ma_so)
        
        file_path = filedialog.askopenfilename(filetypes=[("Excel files", "*.xlsx")])
        if not file_path: return
        
        self.log(self.ui_text[lang]["log_start"])
        try:
            # Đọc file Excel
            df = pd.read_excel(file_path, sheet_name='LIST', header=1)
            df.columns = df.columns.str.strip()
            df['注番'] = df['注番'].astype(str)
            
            data = df[df['注番'] == ma_so]
            if data.empty:
                self.log(self.ui_text[lang]["err"])
                return
                
            # Lưu file mặc định
            save_path = filedialog.asksaveasfilename(
                defaultextension=".csv", 
                initialfile=f"LIST_{ma_so}.csv",
                filetypes=[("CSV files", "*.csv")]
            )
            if save_path:
                data[['図番/型式', '品名', '手配数', '数量', '入荷状況']].to_csv(save_path, index=False, encoding='utf-8-sig')
                
                # Tính thời gian hoàn thành
                elapsed = round(time.time() - start_time, 2)
                self.log(f"{self.ui_text[lang]['log_done']} {elapsed}s")
                
        except Exception as e:
            self.log(f"Error: {e}")

if __name__ == "__main__":
    app = App()
    app.mainloop()