# 請求書ジェネレーター (Flask + ReportLab) – 日本語対応MVP

単票PDFの作成と、CSVアップロードによる複数請求書の一括生成（ZIP）に対応した軽量MVPです。  
**日本語フォント埋め込み**・**税率別内訳**・**長文/長い数値の折返し**に対応しています。

---

## 主な機能
- フォーム入力 → 請求書PDFを即時ダウンロード
- CSVアップロード（1行=1請求書）→ 複数PDFをZIPで一括ダウンロード
- 日本語PDF対応（フォント同梱 or `.env` で指定）
- 税率別内訳（10%/8%/0%など混在対応）
- 長文住所・桁数の多い金額も自動折返し
- オプション：ロゴ画像表示、適格請求書発行事業者の登録番号表示

---

## セットアップ

### Windows (PowerShell)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 環境変数ファイルを用意
Copy-Item .env.example .env

# 日本語フォント（推奨）
mkdir fonts
# NotoSansJP-Regular.ttf を fonts/ に配置
python invoice_generator.py
# → http://127.0.0.1:5000 を開く

※ Activate.ps1 実行時にエラーが出る場合：
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python invoice_generator.py
# → http://127.0.0.1:5000

CSV仕様（1行=1請求書）
invoice_no,date,due_date,
seller_name,seller_address,seller_email,seller_phone,
buyer_name,buyer_address,buyer_email,buyer_phone,
currency,items,tax_rate,note

