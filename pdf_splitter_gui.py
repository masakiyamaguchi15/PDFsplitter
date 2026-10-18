import sys
import os
import io
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import queue

# 依存ライブラリのインポートチェックとエラー表示
try:
    import fitz  # PyMuPDF
    from PIL import Image, ImageTk, ImageDraw
except ImportError:
    # Tkinterのルートウィンドウを一時的に作成して警告ダイアログを表示
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "ライブラリがインストールされていません",
        "このアプリケーションを実行するには、以下の外部ライブラリが必要です。\n\n"
        "・PyMuPDF (fitz)\n"
        "・Pillow (PIL)\n\n"
        "コマンドプロンプトやターミナルで以下のコマンドを実行してインストールしてください：\n"
        "pip install pymupdf pillow"
    )
    sys.exit(1)


class PDFSplitterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("PDF Page Splitter")
        self.root.geometry("950x700")
        self.root.minsize(700, 500)
        
        # 状態変数
        self.pdf_path = None
        self.selected_pages = set()  # 選択されたページのインデックス（0開始）
        self.active_pages = []        # 現在表示されているページの元のインデックス
        self.total_pages = 0          # 開いているPDFの総ページ数
        self.page_widgets = []        # ページカード用ウィジェットのリスト
        self.photo_images = {}        # 画像のガベージコレクション防止用キャッシュ
        
        # 非同期処理用のキューとスレッド管理
        self.queue = queue.Queue()
        self.stop_event = threading.Event()
        self.render_thread = None
        self.render_generation = 0    # 古いスレッドからの結果を判別するための世代番号
        self.is_loading = False       # サムネイル生成中かどうか
        self.loaded_count = 0         # 生成済みサムネイル数

        # プレースホルダー画像の作成
        self.placeholder_image = self.create_placeholder_image()
        
        # UI構築
        self.setup_ui()
        
        # キュー監視の開始
        self.poll_queue()

    def setup_ui(self):
        """全体のUIを構築します"""
        # アプリ全体の背景色
        self.root.configure(bg="#F5F5F7")
        
        # 1. 操作エリア（上部）
        self.header_frame = tk.Frame(self.root, bg="#FFFFFF", height=70)
        self.header_frame.pack(fill="x", side="top")
        self.header_frame.pack_propagate(False)
        
        # ボタン配置用のコンテナ（左寄せ）
        self.left_btn_frame = tk.Frame(self.header_frame, bg="#FFFFFF")
        self.left_btn_frame.pack(side="left", padx=15, pady=10)
        
        self.open_btn = self.create_flat_button(
            self.left_btn_frame, "PDFを開く", "#007AFF", "white", self.open_pdf
        )
        self.open_btn.pack(side="left", padx=5)
        
        self.save_btn = self.create_flat_button(
            self.left_btn_frame, "選択したページを保存", "#CCCCCC", "white", self.save_selected_pages
        )
        self.save_btn.config(state="disabled")  # 初期状態は無効
        self.save_btn.pack(side="left", padx=5)
        
        self.delete_btn = self.create_flat_button(
            self.left_btn_frame, "選択したページを削除", "#CCCCCC", "white", self.delete_selected_pages
        )
        self.delete_btn.config(state="disabled")  # 初期状態は無効
        self.delete_btn.pack(side="left", padx=5)
        
        # ボタン配置用のコンテナ（右寄せ）
        self.right_btn_frame = tk.Frame(self.header_frame, bg="#FFFFFF")
        self.right_btn_frame.pack(side="right", padx=15, pady=10)
        
        self.select_all_btn = self.create_flat_button(
            self.right_btn_frame, "すべて選択", "#8E8E93", "white", self.select_all
        )
        self.select_all_btn.config(state="disabled")
        self.select_all_btn.pack(side="left", padx=5)
        
        self.clear_btn = self.create_flat_button(
            self.right_btn_frame, "選択解除", "#8E8E93", "white", self.clear_selection
        )
        self.clear_btn.config(state="disabled")
        self.clear_btn.pack(side="left", padx=5)
        
        # 区切り線
        self.separator = tk.Frame(self.root, height=1, bg="#E0E0E0")
        self.separator.pack(fill="x", side="top")
        
        # 2. メインのスクロール表示エリア（中央）
        self.main_frame = tk.Frame(self.root, bg="#F5F5F7")
        self.main_frame.pack(fill="both", expand=True, side="top", padx=10, pady=10)
        
        # キャンバスとスクロールバー
        self.canvas = tk.Canvas(self.main_frame, borderwidth=0, highlightthickness=0, bg="#F5F5F7")
        self.scrollbar = ttk.Scrollbar(self.main_frame, orient="vertical", command=self.canvas.yview)
        
        # スクロール可能なフレーム
        self.scrollable_frame = tk.Frame(self.canvas, bg="#F5F5F7")
        
        # スクロール領域の自動更新設定
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        
        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        
        # キャンバス幅の変更に合わせてフレーム幅とグリッドレイアウトを調整
        self.canvas.bind("<Configure>", self.on_canvas_configure)
        
        # マウスホイールスクロールのバインド
        self.canvas.bind_all("<MouseWheel>", self.on_mousewheel)
        
        # 3. ステータスバー（下部）
        self.status_frame = tk.Frame(self.root, bg="#E5E5EA", height=25)
        self.status_frame.pack(fill="x", side="bottom")
        self.status_frame.pack_propagate(False)
        
        self.status_label = tk.Label(
            self.status_frame, text="PDFファイルを開いてください。", bg="#E5E5EA", fg="#555555", font=("Arial", 9)
        )
        self.status_label.pack(side="left", padx=15, pady=2)

    def create_flat_button(self, parent, text, bg, fg, command):
        """モダンなフラットデザインのボタンを作成します（ホバー効果付き）"""
        btn = tk.Button(
            parent,
            text=text,
            bg=bg,
            fg=fg,
            activebackground=self.darken_color(bg),
            activeforeground=fg,
            font=("Arial", 10, "bold"),
            bd=0,
            padx=15,
            pady=6,
            relief="flat",
            cursor="hand2",
            command=command
        )
        # ホバー時のアクションを設定
        btn.bind("<Enter>", lambda e: self.on_button_hover(btn, bg))
        btn.bind("<Leave>", lambda e: self.on_button_leave(btn, bg))
        return btn

    def on_button_hover(self, btn, orig_bg):
        if btn["state"] != "disabled":
            btn.config(bg=self.lighten_color(orig_bg))

    def on_button_leave(self, btn, orig_bg):
        if btn["state"] != "disabled":
            btn.config(bg=orig_bg)

    def lighten_color(self, hex_color):
        """カラーコードを少し明るくします（ホバー効果用）"""
        if not hex_color.startswith("#"):
            return hex_color
        hex_color = hex_color.lstrip('#')
        if len(hex_color) != 6:
            return "#" + hex_color
        rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        new_rgb = tuple(min(255, int(c + (255 - c) * 0.20)) for c in rgb)
        return '#{:02x}{:02x}{:02x}'.format(*new_rgb)

    def darken_color(self, hex_color):
        """カラーコードを少し暗くします（クリック時の効果用）"""
        if not hex_color.startswith("#"):
            return hex_color
        hex_color = hex_color.lstrip('#')
        if len(hex_color) != 6:
            return "#" + hex_color
        rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        new_rgb = tuple(max(0, int(c * 0.80)) for c in rgb)
        return '#{:02x}{:02x}{:02x}'.format(*new_rgb)

    def create_placeholder_image(self):
        """ローディング中に表示するプレースホルダー画像を作成"""
        img = Image.new("RGB", (140, 180), "#EAEAEA")
        try:
            draw = ImageDraw.Draw(img)
            # 簡易的なローディング表記
            draw.text((45, 85), "Loading...", fill="#888888")
        except Exception:
            pass
        return img

    def on_canvas_configure(self, event):
        """キャンバスのリサイズに合わせてスクロール領域幅を同期"""
        self.canvas.itemconfig(self.canvas_window, width=event.width)
        self.update_grid_layout(event.width)

    def on_mousewheel(self, event):
        """マウスホイールでのスクロール制御"""
        # スクロールバーが動作する状態（コンテンツがウィンドウ幅より大きい）の時のみスクロール
        if self.canvas.yview() != (0.0, 1.0):
            # Windowsではevent.deltaの値をベースにスクロール方向を判定
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def update_grid_layout(self, width=None):
        """グリッドの列数をキャンバス幅に合わせて動的に再配置します"""
        if not self.page_widgets:
            return
        
        if width is None:
            width = self.canvas.winfo_width()
            
        card_w = 170  # カード幅(140) + 余白
        cols = max(1, width // card_w)
        
        # グリッドの列ウェイトを設定
        for c in range(25):  # 念のため十分な列をクリア
            self.scrollable_frame.grid_columnconfigure(c, weight=0)
        for c in range(cols):
            self.scrollable_frame.grid_columnconfigure(c, weight=1)
            
        for idx, widget_dict in enumerate(self.page_widgets):
            frame = widget_dict["frame"]
            r = idx // cols
            c = idx % cols
            frame.grid(row=r, column=c, padx=10, pady=10)

    def open_pdf(self):
        """ファイルダイアログからPDFファイルを読み込みます"""
        file_path = filedialog.askopenfilename(
            title="PDFファイルを開く",
            filetypes=[("PDF Files", "*.pdf"), ("All Files", "*.*")]
        )
        if not file_path:
            return
        
        # 前の処理スレッドを強制終了
        self.stop_event.set()
        
        # 初期化
        self.pdf_path = file_path
        self.selected_pages.clear()
        self.photo_images.clear()
        
        # 既存のページカードを破棄
        for wd in self.page_widgets:
            wd["frame"].destroy()
        self.page_widgets.clear()
        
        try:
            # ページ数取得用に一旦ドキュメントを開く
            doc = fitz.open(file_path)
            num_pages = len(doc)
            doc.close()
        except Exception as e:
            messagebox.showerror("エラー", f"PDFファイルを開けませんでした:\n{str(e)}")
            self.status_label.config(text="PDFの読み込みに失敗しました。")
            return
        
        self.total_pages = num_pages
        self.active_pages = list(range(num_pages))
        
        # プレースホルダーのTk画像を用意
        tk_placeholder = ImageTk.PhotoImage(self.placeholder_image)
        self.photo_images[-1] = tk_placeholder  # キャッシュに保持
        
        # ページグリッドの構築
        self.refresh_page_grid()
        
        # コントロールボタンとステータスの更新
        self.select_all_btn.config(state="normal")
        self.clear_btn.config(state="normal")
        self.update_button_states()
        filename = os.path.basename(file_path)
        self.status_label.config(text=f"読込中: {filename} (全 {num_pages} ページ)")

        # サムネイル生成用の新規スレッドを開始
        self.render_generation += 1
        self.is_loading = True
        self.loaded_count = 0
        self.stop_event = threading.Event()
        self.render_thread = threading.Thread(
            target=self.render_thumbnails_worker,
            args=(file_path, self.stop_event, self.render_generation)
        )
        self.render_thread.daemon = True
        self.render_thread.start()

    def render_thumbnails_worker(self, pdf_path, stop_event, generation):
        """別スレッドでPDFページをレンダリングし、画像を生成するワーカー"""
        try:
            doc = fitz.open(pdf_path)
            for i in range(len(doc)):
                if stop_event.is_set():
                    break
                    
                # ページの取得と描画
                page = doc.load_page(i)
                # dpi=72 で描画し、Pillow側でサムネイルサイズに落とす
                pix = page.get_pixmap(dpi=72, alpha=False)
                img_data = pix.tobytes("png")
                
                img = Image.open(io.BytesIO(img_data))
                img.thumbnail((140, 180), Image.LANCZOS)
                
                # 生成した画像をキューにプッシュ
                self.queue.put(("page", generation, i, img))

            doc.close()
            self.queue.put(("done", generation))
        except Exception as e:
            self.queue.put(("error", generation, str(e)))

    def poll_queue(self):
        """キューから読み込み完了した画像を定期的に取得し、UIに反映します (メインスレッドで実行)"""
        try:
            while True:
                # ブロックせずにキューから要素を取得
                item = self.queue.get_nowait()
                kind, generation = item[0], item[1]

                # 以前に開いたPDFの結果は破棄
                if generation != self.render_generation:
                    self.queue.task_done()
                    continue

                if kind == "error":
                    # エラー発生時の処理
                    self.is_loading = False
                    messagebox.showerror("レンダリングエラー", f"サムネイル生成中にエラーが発生しました:\n{item[2]}")
                    self.update_status_label()
                elif kind == "done":
                    self.is_loading = False
                    self.update_status_label()
                else:
                    idx, img = item[2], item[3]
                    tk_img = ImageTk.PhotoImage(img)
                    self.photo_images[idx] = tk_img  # ガベージコレクション防止
                    self.loaded_count += 1

                    # ウィジェットの画像を更新
                    for wd in self.page_widgets:
                        if wd.get("orig_idx") == idx:
                            wd["img_lbl"].config(image=tk_img)
                            break

                self.queue.task_done()
        except queue.Empty:
            pass

        # 読込中のみ進捗を表示（ページが残っていない場合は表示しない）
        if self.pdf_path and self.is_loading and self.active_pages:
            filename = os.path.basename(self.pdf_path)
            self.status_label.config(text=f"読込中: {filename} ({self.loaded_count}/{self.total_pages} ページ完了)")

        # 100ms後に再確認
        self.root.after(100, self.poll_queue)

    def toggle_page_selection(self, orig_idx):
        """ページの選択状態をトグル切り替えします"""
        if orig_idx in self.selected_pages:
            self.selected_pages.remove(orig_idx)
        else:
            self.selected_pages.add(orig_idx)
            
        self.update_card_visual(orig_idx)
        self.update_button_states()
        self.update_status_label()

    def update_card_visual(self, orig_idx):
        """対象カードのビジュアルを選択状態に応じて更新します"""
        is_selected = orig_idx in self.selected_pages
        for wd in self.page_widgets:
            if wd.get("orig_idx") == orig_idx:
                if is_selected:
                    # 選択時：赤枠、薄い赤の背景、赤いフォント
                    wd["frame"].config(highlightbackground="#FF3B30", highlightcolor="#FF3B30", bg="#FFEAEA")
                    wd["img_lbl"].config(bg="#FFEAEA")
                    wd["txt_lbl"].config(bg="#FFEAEA", fg="#FF3B30")
                else:
                    # 未選択時：グレー枠、ライトグレーの背景、グレーのフォント
                    wd["frame"].config(highlightbackground="#CCCCCC", highlightcolor="#CCCCCC", bg="#F5F5F5")
                    wd["img_lbl"].config(bg="#F5F5F5")
                    wd["txt_lbl"].config(bg="#F5F5F5", fg="#333333")
                break

    def select_all(self):
        """すべてのページを選択します"""
        if not self.pdf_path:
            return
        for orig_idx in self.active_pages:
            self.selected_pages.add(orig_idx)
            self.update_card_visual(orig_idx)
        self.update_button_states()
        self.update_status_label()

    def clear_selection(self):
        """すべての選択を解除します"""
        if not self.pdf_path:
            return
        self.selected_pages.clear()
        for orig_idx in self.active_pages:
            self.update_card_visual(orig_idx)
        self.update_button_states()
        self.update_status_label()

    def update_button_states(self):
        """選択されているページ数に応じて保存ボタンと削除ボタンのアクティブ状態とカラーを制御します"""
        if self.selected_pages:
            self.save_btn.config(state="normal", bg="#34C759")
            self.delete_btn.config(state="normal", bg="#FF3B30")
        else:
            self.save_btn.config(state="disabled", bg="#CCCCCC")
            self.delete_btn.config(state="disabled", bg="#CCCCCC")

    def refresh_page_grid(self):
        """現在の active_pages に基づいて、グリッド表示を再構築します"""
        # 既存のページカードを破棄
        for wd in self.page_widgets:
            wd["frame"].destroy()
        self.page_widgets.clear()
        
        tk_placeholder = self.photo_images.get(-1)
        
        for orig_idx in self.active_pages:
            card_frame = tk.Frame(
                self.scrollable_frame,
                highlightbackground="#CCCCCC",
                highlightcolor="#CCCCCC",
                highlightthickness=2,
                bd=0,
                bg="#F5F5F5",
                cursor="hand2"
            )
            
            tk_img = self.photo_images.get(orig_idx, tk_placeholder)
            img_lbl = tk.Label(card_frame, image=tk_img, bg="#F5F5F5")
            img_lbl.pack(padx=8, pady=8)
            
            txt_lbl = tk.Label(
                card_frame, text=f"Page {orig_idx + 1}", bg="#F5F5F5", fg="#333333", font=("Arial", 10, "bold")
            )
            txt_lbl.pack(padx=8, pady=(0, 8))
            
            # 各要素へのクリックバインド
            for widget in (card_frame, img_lbl, txt_lbl):
                widget.bind("<Button-1>", lambda event, o_idx=orig_idx: self.toggle_page_selection(o_idx))
            
            self.page_widgets.append({
                "frame": card_frame,
                "img_lbl": img_lbl,
                "txt_lbl": txt_lbl,
                "orig_idx": orig_idx
            })
            
            self.update_card_visual(orig_idx)
            
        self.update_grid_layout()

    def delete_selected_pages(self):
        """選択されたページを画面の表示（編集対象）から削除します"""
        if not self.selected_pages:
            return
            
        num_selected = len(self.selected_pages)
        if not messagebox.askyesno(
            "確認", 
            f"選択した {num_selected} ページを削除しますか？\n（元のPDFファイルは変更されません）"
        ):
            return
            
        # active_pages から選択されたページを除外
        self.active_pages = [p for p in self.active_pages if p not in self.selected_pages]
        self.selected_pages.clear()
        
        self.refresh_page_grid()
        self.update_button_states()
        self.update_status_label()
        
        # すべて削除されてしまった場合の処理
        if not self.active_pages:
            self.select_all_btn.config(state="disabled")
            self.clear_btn.config(state="disabled")

    def update_status_label(self):
        """ステータスラベルのテキストを更新します"""
        if self.pdf_path and not self.active_pages:
            self.status_label.config(text="すべてのページが削除されました。新しいPDFファイルを開いてください。")
        elif self.pdf_path:
            total = len(self.page_widgets)
            selected = len(self.selected_pages)
            filename = os.path.basename(self.pdf_path)
            self.status_label.config(text=f"選択中: {selected} / {total} ページ | ファイル: {filename}")

    def save_selected_pages(self):
        """選択されたページを抽出・結合して新しいPDFとして保存します"""
        if not self.selected_pages:
            messagebox.showwarning("警告", "保存するページが選択されていません。")
            return
            
        save_path = filedialog.asksaveasfilename(
            title="選択したページを保存",
            defaultextension=".pdf",
            filetypes=[("PDF Files", "*.pdf")]
        )
        if not save_path:
            return
            
        try:
            # 元のPDFを開く
            src_doc = fitz.open(self.pdf_path)
            # 新しい空のPDFドキュメントを作成
            out_doc = fitz.open()
            
            # 選択されたページを昇順にソートして追加
            sorted_pages = sorted(list(self.selected_pages))
            for p_num in sorted_pages:
                out_doc.insert_pdf(src_doc, from_page=p_num, to_page=p_num)
                
            # 保存
            out_doc.save(save_path)
            out_doc.close()
            src_doc.close()
            
            messagebox.showinfo(
                "保存完了", 
                f"選択したページ（{len(sorted_pages)}ページ）が正常に抽出・保存されました。\n\n保存先:\n{save_path}"
            )
        except Exception as e:
            messagebox.showerror("エラー", f"PDFファイルの作成中にエラーが発生しました:\n{str(e)}")


if __name__ == "__main__":
    root = tk.Tk()
    app = PDFSplitterApp(root)
    root.mainloop()
