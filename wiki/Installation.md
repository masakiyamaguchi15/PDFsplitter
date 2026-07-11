# インストール方法 (Installation)

PDF Page Splitter を実行するためのセットアップ手順を説明します。

---

## 動作環境

本アプリケーションは以下の環境で動作します。

- **OS**: Windows, macOS, Linux
- **Python**: Python 3.8 以上推奨

---

## 必要ライブラリのインストール

本アプリケーションの実行には、以下の外部ライブラリが必要です。

1. **PyMuPDF (`fitz`)**: PDFファイルの解析、描画、分割・結合処理に使用します。
2. **Pillow (`PIL`)**: サムネイル画像の処理とTkinterへの描画用データの作成に使用します。

ターミナル（Windowsの場合はコマンドプロンプトやPowerShell）を開き、以下のコマンドを実行してインストールしてください。

```bash
pip install pymupdf pillow
```

### 【補足】Linux環境（Ubuntu/Debianなど）における注意点
Linux環境においてPythonの標準GUIライブラリ `tkinter` がインストールされていない場合、起動時にエラーが発生することがあります。その場合は、システムのパッケージマネージャから以下のコマンドで `tkinter` を個別にインストールしてください。

```bash
sudo apt-get update
sudo apt-get install python3-tk
```

---

## アプリケーションの起動方法

必要なライブラリがインストールされたら、スクリプトがあるディレクトリに移動して、以下のコマンドで起動します。

```bash
python pdf_splitter_gui.py
```

起動後、モダンなフラットデザインのウィンドウが表示されれば、セットアップは完了です。

* **[[使い方|Usage]]** に進んで、実際の操作手順を確認しましょう。
