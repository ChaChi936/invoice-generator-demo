# -*- coding: utf-8 -*-
"""
Invoice Generator (MVP)
- 日本語フォント埋め込み（NotoSansJP-Regular.ttf 推奨）
- 右上メタ情報は「ラベル→次の行に値」の縦並び
- 明細は列幅で折り返し（内容/数量/単価/小計）、行高は列の最大行数で揃える
- 税率ごとの内訳（10%/8%/0% など）を合計欄に表示
"""

from __future__ import annotations
import io
import os
import csv
import zipfile
from datetime import datetime
from typing import List, Tuple, Optional
from collections import defaultdict

from flask import Flask, request, send_file, redirect, url_for, render_template_string, flash
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# .env 読み込み（任意）
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

# ---------------- Font utils ----------------
FALLBACK_FONT = "Helvetica"  # ASCII only
JP_FONT_NAME: Optional[str] = None

def _register_jp_font() -> Optional[str]:
    """日本語フォントを登録してフォント名を返す。無ければ None"""
    global JP_FONT_NAME
    candidates: List[str] = []

    # 環境変数（.env 経由でもOK）
    env_font = os.environ.get("FONT_TTF")
    if env_font:
        candidates.append(env_font)

    base = os.path.dirname(__file__)
    # 置き場所（推奨）
    candidates.append(os.path.join(base, "fonts", "NotoSansJP-Regular.ttf"))
    candidates.append(os.path.join(base, "fonts", "NotoSansCJKjp-Regular.otf"))
    candidates.append(os.path.join(base, "fonts", "NotoSansCJKjp-Regular.ttf"))

    for path in candidates:
        if path and os.path.exists(path):
            try:
                name = os.path.splitext(os.path.basename(path))[0]
                pdfmetrics.registerFont(TTFont(name, path))
                JP_FONT_NAME = name
                return JP_FONT_NAME
            except Exception:
                pass

    # 最終フォールバック（CIDフォント）— 環境により不可な場合もある
    try:
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
        JP_FONT_NAME = "HeiseiKakuGo-W5"
        return JP_FONT_NAME
    except Exception:
        return None

_register_jp_font()

# ---------- text wrap helpers ----------
def draw_wrapped(cnv, text, x, y, font_name, font_size, max_width, line_height):
    """左寄せ1段落を幅で折り返して描画。次に描く y を返す"""
    cnv.setFont(font_name, font_size)
    line = ""
    for ch in str(text):
        test = line + ch
        if pdfmetrics.stringWidth(test, font_name, font_size) <= max_width:
            line = test
        else:
            cnv.drawString(x, y, line)
            y -= line_height
            line = ch
    if line:
        cnv.drawString(x, y, line)
        y -= line_height
    return y

def wrap_lines(text, font_name, font_size, max_width):
    """左寄せ用：指定幅で文字列を行配列に"""
    s = str(text)
    lines, cur = [], ""
    for ch in s:
        test = cur + ch
        if pdfmetrics.stringWidth(test, font_name, font_size) <= max_width:
            cur = test
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines or [""]

def wrap_lines_right(text, font_name, font_size, max_width):
    """右寄せ用：分割は左寄せと同じ。描画時に right 揃えで使う"""
    return wrap_lines(text, font_name, font_size, max_width)

# -------------- PDF 生成 --------------
def generate_invoice_pdf(data: dict) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    margin_x = 18 * mm
    margin_y = 18 * mm

    
    base_font = JP_FONT_NAME or FALLBACK_FONT
    title_font_size = 18
    text_font_size = 10

    c.setFont(base_font, title_font_size)
    c.drawString(margin_x, height - margin_y, data.get("title", "請求書 / INVOICE"))
    c.setFont(base_font, text_font_size)


    y = height - margin_y - 12 * mm           
    y2 = height - margin_y - 12 * mm          
    x2 = margin_x + 80 * mm                   
    buyer_max_w = 62 * mm                     

    # データ行
    seller_lines = [
        data.get("seller_name", ""),
        data.get("seller_address", ""),
        data.get("seller_email", ""),
        data.get("seller_phone", ""),
    ]
    buyer_lines = [
        data.get("buyer_name", ""),
        data.get("buyer_address", ""),
        data.get("buyer_email", ""),
        data.get("buyer_phone", ""),
    ]
    meta_right = [
        ("請求書番号 / Invoice No.", data.get("invoice_no", "")),
        ("請求日 / Date",        data.get("date", "")),
        ("支払期日 / Due Date",  data.get("due_date", "")),
        ("通貨 / Currency",      data.get("currency", "JPY")),
        ("税率 / Tax Rate",      f"{float(data.get('tax_rate') or 0)*100:.0f}%"),
        
    ]

           # ---------- Header blocks (2カラム：左=Seller / 右=Meta) ----------
    # ベゼルつまみ
    y_top = height - margin_y - 12 * mm
    col_gap = 6 * mm
    col_split_x = margin_x + 90 * mm   # ← 左と右の境界（必要なら90→95〜100mmへ）
    meta_x = col_split_x + col_gap

    # 右上ロゴ（任意。static/logo.png があれば右上に表示）
    logo_bottom_y = y_top
    try:
        logo_path = os.path.join("static", "logo.png")
        if os.path.exists(logo_path):
            logo_w = 24 * mm
            logo_h = 24 * mm
            logo_x = width - margin_x - logo_w
            logo_y = height - margin_y - logo_h
            c.drawImage(logo_path, logo_x, logo_y, width=logo_w, height=logo_h,
                        preserveAspectRatio=True, mask='auto')
            logo_bottom_y = logo_y
    except Exception:
        pass

    # 見出し（同一行に左右で表示）
    c.setFont(base_font, 11)
    c.drawString(margin_x, y_top, "請求元 / From")
    c.drawString(meta_x,    y_top, "請求書番号 / Invoice No.")

    # 左列：請求元（右カラム境界の1文字手前で必ず折返し）
    y_left = y_top - 16
    one_char_w = pdfmetrics.stringWidth("あ", base_font, text_font_size)  # 全角1文字分
    seller_max_w = max(40 * mm, (col_split_x - margin_x) - one_char_w)

    seller_lines = [
        data.get("seller_name", ""),
        data.get("seller_address", ""),
        data.get("seller_phone", ""),
        data.get("seller_email", ""),
    ]
    for line in seller_lines:
        if line:
            y_left = draw_wrapped(
                c, line, margin_x, y_left,
                base_font, text_font_size,
                max_width=seller_max_w, line_height=12
            )

    # 右列：メタ（ラベル → 次の行に値 の縦積み）
    y_right = y_top - 16
    meta_max_w = (width - margin_x) - meta_x

    # ★ 先頭は請求書番号の値だけを出す（ラベルは上に出しているので不要）
invoice_no = data.get("invoice_no", "")
if invoice_no:
    c.setFont(base_font, 10)
    for ln in wrap_lines(invoice_no, base_font, 10, meta_max_w):
        c.drawString(meta_x, y_right, ln)
        y_right -= 14
    y_right -= 2  # 少し余白

    # 残りのメタ群
    c.setFont(base_font, 10)
    meta_fields = [
        ("請求日 / Date",        data.get("date", "")),
        ("支払期日 / Due Date",  data.get("due_date", "")),
        ("通貨 / Currency",      data.get("currency", "JPY")),
        ("税率 / Tax Rate",      f"{float(data.get('tax_rate') or 0)*100:.0f}%"),
    ]
    for label, val in meta_fields:
        c.drawString(meta_x, y_right, label)
        y_right -= 12
        for ln in wrap_lines(val, base_font, 10, meta_max_w):
            c.drawString(meta_x, y_right, ln)
            y_right -= 14

    # 請求先 / Bill To は左右ブロックの下に配置（※旧コードの“上段中列”を廃止）
    c.setFont(base_font, 11)
    y_bt = min(y_left, y_right, logo_bottom_y) - 10 * mm
    c.drawString(margin_x, y_bt, "請求先 / Bill To")
    y_bt -= 16
    # 左右ブロックに合わせて、請求先は左側幅いっぱいで折返し
    buyer_max_w = (col_split_x - margin_x) - one_char_w
    buyer_lines = [
        data.get("buyer_name", ""),
        data.get("buyer_address", ""),
        data.get("buyer_phone", ""),
        data.get("buyer_email", ""),
    ]
    for line in buyer_lines:
        if line:
            y_bt = draw_wrapped(
                c, line, margin_x, y_bt,
                base_font, text_font_size,
                max_width=buyer_max_w, line_height=12
            )

    # 明細開始位置：上の3者（Seller / Meta / BillTo）の最下点に合わせる
    table_top = min(y_bt, y_left, y_right) - 8 * mm
    c.setFont(base_font, 11)
    c.drawString(margin_x, table_top, "明細 / Items")

    col_x = [margin_x, margin_x + 90*mm, margin_x + 120*mm, margin_x + 145*mm, width - margin_x]
    header_y = table_top - 16
    c.setFont(base_font, 10)
    headers = ["内容 / Description", "数量 / Qty", "単価 / Unit", "小計 / Subtotal"]
    for i, htxt in enumerate(headers):
        c.drawString(col_x[i], header_y, htxt)
    c.line(margin_x, header_y - 4, width - margin_x, header_y - 4)

    # 明細の列幅・折り返し設定
    row_y = header_y - 18
    currency = data.get("currency", "JPY")

    def money(v: float) -> str:
        s = f"{v:,.0f}" if currency == "JPY" else f"{v:,.2f}"
        return f"¥{s}" if currency == "JPY" else s

    pad_l, pad_r = 2*mm, 2*mm
    w_desc = (col_x[1] - col_x[0]) - (pad_l + pad_r)
    w_qty  = (col_x[2] - col_x[1]) - (pad_l + pad_r)
    w_unit = (col_x[3] - col_x[2]) - (pad_l + pad_r)
    w_sub  = (col_x[4] - col_x[3]) - (pad_l + pad_r)
    line_h = 14

    items: List[Tuple] = data.get("items", [])
    subtotal_by_rate = defaultdict(float)
    default_rate = float(data.get("tax_rate") or 0)

    for it in items:
        if len(it) == 4:
            desc, qty, unit, taxv = it
        else:
            desc, qty, unit = it
            taxv = None

        sub = float(qty) * float(unit)
        rate = default_rate if (taxv in (None, "")) else float(taxv)
        subtotal_by_rate[rate] += sub

        # 折り返し
        c.setFont(base_font, 10)
        desc_lines = wrap_lines(desc, base_font, 10, w_desc)
        qty_lines  = wrap_lines_right(qty, base_font, 10, w_qty)
        unit_lines = wrap_lines_right(money(float(unit)), base_font, 10, w_unit)
        sub_lines  = wrap_lines_right(money(sub),        base_font, 10, w_sub)

        max_lines = max(len(desc_lines), len(qty_lines), len(unit_lines), len(sub_lines))
        row_height = max_lines * line_h

        # 改ページ
        if row_y - row_height < 40 * mm:
            c.showPage()
            c.setFont(base_font, 11)
            c.drawString(margin_x, height - margin_y - 12*mm, "明細 / Items")
            c.setFont(base_font, 10)
            row_y = height - margin_y - 40 * mm

        # 描画（左寄せ/右寄せ）
        y0 = row_y
        for ln in desc_lines:
            c.drawString(col_x[0] + pad_l, y0, ln)
            y0 -= line_h

        y0 = row_y
        for ln in qty_lines:
            c.drawRightString(col_x[2] - pad_r, y0, ln)
            y0 -= line_h

        y0 = row_y
        for ln in unit_lines:
            c.drawRightString(col_x[3] - pad_r, y0, ln)
            y0 -= line_h

        y0 = row_y
        for ln in sub_lines:
            c.drawRightString(col_x[4] - pad_r, y0, ln)
            y0 -= line_h

        row_y -= row_height

    # 合計（税率別内訳）
    totals_x_label = col_x[3] - 30*mm
    totals_x_val = col_x[4] - 4
    row_y -= 6
    c.line(margin_x, row_y, width - margin_x, row_y)
    row_y -= 18

    total_sub = 0.0
    total_tax = 0.0
    for rate in sorted(subtotal_by_rate.keys(), reverse=True):
        sub = subtotal_by_rate[rate]
        tax = sub * rate
        total_sub += sub
        total_tax += tax
        c.drawRightString(totals_x_label, row_y, f"対象小計（{int(rate*100)}%）")
        c.drawRightString(totals_x_val, row_y, money(sub))
        row_y -= 14
        c.drawRightString(totals_x_label, row_y, f"消費税（{int(rate*100)}%）")
        c.drawRightString(totals_x_val, row_y, money(tax))
        row_y -= 14

    c.line(margin_x, row_y, width - margin_x, row_y)
    row_y -= 18
    c.drawRightString(totals_x_label, row_y, "小計 / Subtotal")
    c.drawRightString(totals_x_val, row_y, money(total_sub))
    row_y -= 14

    c.setFont(base_font, 12)
    c.drawRightString(totals_x_label, row_y, "合計 / Total")
    c.drawRightString(totals_x_val, row_y, money(total_sub + total_tax))

       # 備考
    row_y -= 22
    c.setFont(base_font, 9)
    note_text = data.get("note", "")
    note_max_w = (width - 2 * margin_x)
    for ln in wrap_lines(note_text, base_font, 9, note_max_w):
        if row_y < 24 * mm:
            c.showPage()
            c.setFont(base_font, 9)
            row_y = height - margin_y
        c.drawString(margin_x, row_y, ln)
        row_y -= 12

    try:
         c.showPage()
    except Exception:
        pass
    c.save()
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes

# ---------- Flask views ----------
INDEX_HTML = """
<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>請求書ジェネレーター (MVP)</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, "Noto Sans JP", sans-serif; margin: 24px; }
    .wrap { max-width: 980px; margin: 0 auto; }
    h1 { margin-bottom: 8px; }
    fieldset { border: 1px solid #ddd; padding: 12px; margin-bottom: 14px; }
    legend { padding: 0 6px; color: #444; }
    label { display:block; margin: 6px 0 4px; font-size: 14px; color:#333; }
    input, textarea, select { width: 100%; padding: 8px; font-size: 14px; }
    .row { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
    .items { margin-top: 8px; }
    table { width: 100%; border-collapse: collapse; }
    th, td { border: 1px solid #ddd; padding: 6px; font-size: 14px; }
    th { background: #f8f8f8; text-align: left; }
    button { padding: 10px 14px; font-size: 14px; cursor: pointer; }
    .muted { color:#666; font-size: 13px; }
    .actions { display:flex; gap: 12px; }
    .notice { background:#fff8d8; border:1px solid #f0e0a0; padding:8px; margin-bottom:12px; }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>請求書ジェネレーター (MVP)</h1>
    <p class="muted">単票PDFとCSV→ZIP一括を生成。日本語PDFは <code>fonts/NotoSansJP-Regular.ttf</code> を同梱、または環境変数 <code>FONT_TTF</code> で指定してください。</p>

    <div class="notice">{{ notice }}</div>

    <form method="post" action="/generate" id="form-single">
      <fieldset>
        <legend>請求元 / From</legend>
        <div class="row">
          <div><label>会社/氏名</label><input name="seller_name" /></div>
          <div><label>メール</label><input name="seller_email" /></div>
          <div><label>住所</label><input name="seller_address" /></div>
          <div><label>電話</label><input name="seller_phone" /></div>
        </div>
      </fieldset>

      <fieldset>
        <legend>請求先 / Bill To</legend>
        <div class="row">
          <div><label>会社/氏名</label><input name="buyer_name" /></div>
          <div><label>メール</label><input name="buyer_email" /></div>
          <div><label>住所</label><input name="buyer_address" /></div>
          <div><label>電話</label><input name="buyer_phone" /></div>
        </div>
      </fieldset>

      <fieldset>
        <legend>基本情報</legend>
        <div class="row">
          <div><label>請求書番号</label><input name="invoice_no" placeholder="INV-2025-001" /></div>
          <div><label>通貨</label>
            <select name="currency">
              <option value="JPY">JPY (円)</option>
              <option value="USD">USD ($)</option>
              <option value="EUR">EUR (€)</option>
            </select>
          </div>
          <div><label>請求日</label><input name="date" type="date" /></div>
          <div><label>支払期日</label><input name="due_date" type="date" /></div>
        </div>
        <div class="row">
          <div><label>税率 (例: 0.1 は10%)</label><input name="tax_rate" value="0.1" /></div>
          <div><label>備考 / Note</label><input name="note" placeholder="いつもありがとうございます。" /></div>
        </div>
      </fieldset>

      <fieldset>
        <legend>明細 / Items</legend>
        <table id="items-table">
          <thead><tr><th>内容</th><th style="width:120px">数量</th><th style="width:140px">単価</th><th style="width:60px"></th></tr></thead>
          <tbody></tbody>
        </table>
        <div class="actions" style="margin-top:8px">
          <button type="button" onclick="addRow()">行を追加</button>
        </div>
      </fieldset>

      <div class="actions">
        <button type="submit">PDFを生成</button>
      </div>
    </form>

    <hr style="margin:24px 0" />

    <h2>CSVバッチ生成</h2>
    <form method="post" action="/batch" enctype="multipart/form-data">
      <label>CSVファイルを選択:</label>
      <input type="file" name="file" accept=".csv" required />
      <p class="muted">
        列: invoice_no,date,due_date,seller_name,seller_address,buyer_name,buyer_address,currency,items,tax_rate<br>
        items は「説明|数量|単価|税率(任意)」を ; 区切りで複数記入<br>
        例: <code>デザイン|10|5000|0.1; 飲料|5|200|0.08; 非課税|1|1000|0</code>
      </p>
      <div class="actions"><button type="submit">ZIPを生成</button></div>
    </form>
  </div>

<script>
function addRow() {
  const tbody = document.querySelector('#items-table tbody');
  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td><input name="item_desc" placeholder="内容"></td>
    <td><input name="item_qty" type="number" step="0.01" value="1"></td>
    <td><input name="item_unit" type="number" step="0.01" value="0"></td>
    <td><button type="button" onclick="this.closest('tr').remove()">削除</button></td>
  `;
  tbody.appendChild(tr);
}
addRow();
</script>
</body>
</html>
"""

@app.route("/")
def index():
    notice = "日本語PDFが文字化けする場合は ./fonts に NotoSansJP-Regular.ttf を配置するか、環境変数 FONT_TTF で日本語フォントを指定してください。"
    if JP_FONT_NAME:
        notice = f"使用フォント: {JP_FONT_NAME} (日本語対応)"
    return render_template_string(INDEX_HTML, notice=notice)

@app.route("/generate", methods=["POST"])
def generate_single():
    form = request.form
    # Items come in parallel lists; gather them
    descs = request.form.getlist("item_desc")
    qtys = request.form.getlist("item_qty")
    units = request.form.getlist("item_unit")

    items: List[Tuple[str, float, float, Optional[float]]] = []
    for d, q, u in zip(descs, qtys, units):
        if not d:
            continue
        try:
            qv = float(q or 0)
            uv = float(u or 0)
        except ValueError:
            qv, uv = 0.0, 0.0
        items.append((d, qv, uv, None))  # 単票は per-item tax 未指定(None)

    data = {
        "title": "請求書 / INVOICE",
        "seller_name": form.get("seller_name", ""),
        "seller_address": form.get("seller_address", ""),
        "seller_email": form.get("seller_email", ""),
        "seller_phone": form.get("seller_phone", ""),
        "buyer_name": form.get("buyer_name", ""),
        "buyer_address": form.get("buyer_address", ""),
        "buyer_email": form.get("buyer_email", ""),
        "buyer_phone": form.get("buyer_phone", ""),
        "invoice_no": form.get("invoice_no", ""),
        "date": form.get("date", datetime.today().strftime("%Y-%m-%d")),
        "due_date": form.get("due_date", ""),
        "currency": form.get("currency", "JPY"),
        "tax_rate": form.get("tax_rate", "0"),
        "note": form.get("note", ""),
        "items": items,
    }

    pdf_bytes = generate_invoice_pdf(data)
    filename = f"invoice_{data['invoice_no'] or datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf", as_attachment=True, download_name=filename)

@app.route("/batch", methods=["POST"])
def generate_batch():
    f = request.files.get("file")
    if not f:
        flash("CSVファイルが選択されていません。")
        return redirect(url_for("index"))

    stream = io.StringIO(f.stream.read().decode("utf-8-sig"))
    reader = csv.DictReader(stream)

    mem_zip = io.BytesIO()
    with zipfile.ZipFile(mem_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for row in reader:
            items_raw = row.get("items", "")
            items: List[Tuple[str, float, float, Optional[float]]] = []
            if items_raw:
                for part in items_raw.split(";"):
                    part = part.strip()
                    if not part:
                        continue
                    segs = [s.strip() for s in part.split("|")]
                    if len(segs) >= 3:
                        desc, qty, unit = segs[0], segs[1], segs[2]
                        taxv = None
                        if len(segs) >= 4 and segs[3] != "":
                            try:
                                taxv = float(segs[3])
                            except ValueError:
                                taxv = None
                        try:
                            qv = float(qty)
                            uv = float(unit)
                        except ValueError:
                            qv, uv = 0.0, 0.0
                        items.append((desc, qv, uv, taxv))

            data = {
                "title": "請求書 / INVOICE",
                "seller_name": row.get("seller_name", ""),
                "seller_address": row.get("seller_address", ""),
                "seller_email": row.get("seller_email", ""),
                "seller_phone": row.get("seller_phone", ""),
                "buyer_name": row.get("buyer_name", ""),
                "buyer_address": row.get("buyer_address", ""),
                "buyer_email": row.get("buyer_email", ""),
                "buyer_phone": row.get("buyer_phone", ""),
                "invoice_no": row.get("invoice_no", ""),
                "date": row.get("date", ""),
                "due_date": row.get("due_date", ""),
                "currency": row.get("currency", "JPY"),
                "tax_rate": row.get("tax_rate", "0"),
                "note": row.get("note", ""),
                "items": items,
            }
            pdf_bytes = generate_invoice_pdf(data)
            name = row.get("invoice_no") or datetime.now().strftime('%Y%m%d%H%M%S')
            zf.writestr(f"invoice_{name}.pdf", pdf_bytes)

    mem_zip.seek(0)
    return send_file(mem_zip, mimetype="application/zip", as_attachment=True, download_name="invoices.zip")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)