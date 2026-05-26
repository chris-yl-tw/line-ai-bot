"""
LINE Bot 後台管理模組
====================
提供密碼保護的 Web 管理介面，功能包含：
  - 商店資料 CRUD（儲存至 GitHub）
  - 機器人互動記錄瀏覽
  - 服務健康狀態監控
  - 環境設定一覽

使用前須在 Render 設定以下環境變數：
  ADMIN_PASSWORD  - 後台登入密碼（必填）
  SECRET_KEY      - Flask session 金鑰（必填，任意亂數字串）
  GITHUB_TOKEN    - GitHub Personal Access Token（選填；填入後才能儲存商店資料至 GitHub）
  GITHUB_REPO     - 倉庫路徑，例如 chris-yl-tw/line-ai-bot（選填，預設同上）
"""

import os
import json
import base64
import logging
from datetime import datetime, timezone
from collections import deque
from functools import wraps

import requests as _http
from flask import (
    Blueprint, render_template_string, request,
    session, redirect, url_for, jsonify
)

logger = logging.getLogger(__name__)

# ── 全域狀態 ──────────────────────────────────────────────────────────────────

interaction_log: deque = deque(maxlen=300)   # 互動記錄（最多 300 筆）
service_start_time: datetime = datetime.now(timezone.utc)
_error_count: int = 0

GITHUB_REPO    = os.getenv("GITHUB_REPO", "chris-yl-tw/line-ai-bot")
GITHUB_TOKEN   = os.getenv("GITHUB_TOKEN", "")
GITHUB_FILE    = "stores_override.json"
GITHUB_API     = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"


def log_interaction(user_name: str, user_id: str, message: str,
                    response_type: str, success: bool) -> None:
    """從 app.py 呼叫，記錄每次機器人互動。"""
    global _error_count
    interaction_log.appendleft({
        "time": datetime.now().strftime("%m/%d %H:%M:%S"),
        "user": user_name or "—",
        "uid":  (user_id[:8] + "…") if len(user_id) > 8 else user_id,
        "msg":  message[:80] + ("…" if len(message) > 80 else ""),
        "type": response_type,
        "ok":   success,
    })
    if not success:
        _error_count += 1


# ── Blueprint ─────────────────────────────────────────────────────────────────

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_ok"):
            return redirect(url_for("admin.login"))
        return f(*args, **kwargs)
    return decorated


# ── GitHub API 輔助函式 ────────────────────────────────────────────────────────

def _github_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }


def _github_get_file():
    """取得 stores_override.json 的內容和 SHA（不存在回傳 None）。"""
    if not GITHUB_TOKEN:
        return None, None
    try:
        r = _http.get(GITHUB_API, headers=_github_headers(), timeout=10)
        if r.status_code == 404:
            return None, None
        r.raise_for_status()
        data = r.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        return content, data["sha"]
    except Exception as e:
        logger.warning(f"GitHub GET 失敗: {e}")
        return None, None


def _github_commit(stores_list: list) -> tuple[bool, str]:
    """將 stores_list 序列化並 commit 到 GitHub。"""
    if not GITHUB_TOKEN:
        return False, "未設定 GITHUB_TOKEN，無法儲存到 GitHub。商店資料僅在當次執行期間有效。"

    new_content = json.dumps(stores_list, ensure_ascii=False, indent=2)
    encoded = base64.b64encode(new_content.encode("utf-8")).decode("utf-8")
    _, sha = _github_get_file()

    payload: dict = {
        "message": f"chore: update stores_override.json via admin panel ({datetime.now().strftime('%Y-%m-%d %H:%M')})",
        "content": encoded,
        "committer": {"name": "LINE Bot Admin", "email": "admin@yile.com.tw"},
    }
    if sha:
        payload["sha"] = sha

    try:
        r = _http.put(GITHUB_API, headers=_github_headers(),
                      json=payload, timeout=15)
        r.raise_for_status()
        return True, "已成功 commit 到 GitHub！Render 約 1–2 分鐘後自動重新部署。"
    except Exception as e:
        logger.error(f"GitHub PUT 失敗: {e}")
        return False, f"GitHub 儲存失敗：{e}"


# ── Routes ────────────────────────────────────────────────────────────────────

@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        pw = request.form.get("password", "")
        admin_pw = os.getenv("ADMIN_PASSWORD", "")
        if not admin_pw:
            error = "尚未設定 ADMIN_PASSWORD 環境變數"
        elif pw == admin_pw:
            session["admin_ok"] = True
            session.permanent = True
            return redirect(url_for("admin.dashboard"))
        else:
            error = "密碼錯誤，請再試一次"
    return render_template_string(_LOGIN_HTML, error=error)


@admin_bp.route("/logout")
def logout():
    session.pop("admin_ok", None)
    return redirect(url_for("admin.login"))


@admin_bp.route("/")
@_login_required
def dashboard():
    return render_template_string(_DASHBOARD_HTML)


# ── API endpoints ─────────────────────────────────────────────────────────────

@admin_bp.route("/api/stores", methods=["GET"])
@_login_required
def api_get_stores():
    import store_data
    return jsonify(store_data.STORE_CARDS)


@admin_bp.route("/api/stores", methods=["PUT"])
@_login_required
def api_save_stores():
    """接收完整的商店列表 JSON，更新記憶體並 commit 到 GitHub。"""
    import store_data
    data = request.get_json(force=True)
    if not isinstance(data, list):
        return jsonify({"ok": False, "msg": "格式錯誤：需要 JSON 陣列"}), 400

    # 立即更新記憶體（重啟前即時生效）
    store_data.STORE_CARDS = data
    logger.info(f"[admin] 商店資料已更新，共 {len(data)} 筆")

    # 非同步 commit 到 GitHub
    ok, msg = _github_commit(data)
    return jsonify({"ok": ok, "msg": msg})


@admin_bp.route("/api/logs", methods=["GET"])
@_login_required
def api_logs():
    return jsonify(list(interaction_log))


@admin_bp.route("/api/status", methods=["GET"])
@_login_required
def api_status():
    now = datetime.now(timezone.utc)
    delta = now - service_start_time
    hours, rem = divmod(int(delta.total_seconds()), 3600)
    minutes, seconds = divmod(rem, 60)
    uptime = f"{hours}h {minutes}m {seconds}s"

    recent_ok  = sum(1 for x in interaction_log if x["ok"])
    recent_err = sum(1 for x in interaction_log if not x["ok"])
    last_time  = interaction_log[0]["time"] if interaction_log else "尚無記錄"

    return jsonify({
        "uptime":      uptime,
        "start_time":  service_start_time.strftime("%Y-%m-%d %H:%M UTC"),
        "total_ok":    recent_ok,
        "total_err":   recent_err,
        "last_active": last_time,
        "github_token_set": bool(GITHUB_TOKEN),
        "github_repo": GITHUB_REPO,
    })


# ── HTML 範本 ─────────────────────────────────────────────────────────────────

_LOGIN_HTML = """
<!DOCTYPE html><html lang="zh-TW"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>後台登入</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#f0f4f8;
     display:flex;align-items:center;justify-content:center;min-height:100vh}
.card{background:#fff;border-radius:16px;box-shadow:0 4px 24px rgba(0,0,0,.1);
      padding:40px;width:360px;max-width:95vw}
h1{font-size:1.4rem;color:#1a202c;margin-bottom:8px}
p{color:#718096;font-size:.9rem;margin-bottom:28px}
label{display:block;font-size:.85rem;color:#4a5568;margin-bottom:6px;font-weight:600}
input{width:100%;padding:10px 14px;border:1.5px solid #e2e8f0;border-radius:8px;
      font-size:1rem;outline:none;transition:.2s}
input:focus{border-color:#667eea}
.btn{margin-top:20px;width:100%;padding:12px;background:linear-gradient(135deg,#667eea,#764ba2);
     color:#fff;border:none;border-radius:8px;font-size:1rem;font-weight:600;cursor:pointer}
.btn:hover{opacity:.9}
.err{color:#e53e3e;font-size:.85rem;margin-top:12px;text-align:center}
</style></head><body>
<div class="card">
  <h1>🤖 LINE Bot 後台</h1>
  <p>弈樂科技特約商店管理系統</p>
  <form method="post">
    <label>管理員密碼</label>
    <input type="password" name="password" autofocus placeholder="請輸入密碼">
    <button class="btn" type="submit">登入</button>
    {% if error %}<div class="err">{{ error }}</div>{% endif %}
  </form>
</div></body></html>
"""

_DASHBOARD_HTML = """
<!DOCTYPE html><html lang="zh-TW"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LINE Bot 後台管理</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#f7fafc;color:#2d3748}
.header{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;
        padding:16px 24px;display:flex;align-items:center;justify-content:space-between;
        position:sticky;top:0;z-index:100;box-shadow:0 2px 8px rgba(0,0,0,.15)}
.header h1{font-size:1.1rem;font-weight:700}
.logout{color:#fff;text-decoration:none;font-size:.85rem;opacity:.85;
        padding:6px 14px;border:1.5px solid rgba(255,255,255,.5);border-radius:20px}
.logout:hover{opacity:1;background:rgba(255,255,255,.15)}
.tabs{background:#fff;border-bottom:2px solid #e2e8f0;padding:0 16px;
      display:flex;overflow-x:auto;gap:4px}
.tab{padding:14px 18px;cursor:pointer;font-weight:600;font-size:.9rem;
     color:#718096;border-bottom:3px solid transparent;white-space:nowrap;margin-bottom:-2px}
.tab.active{color:#667eea;border-bottom-color:#667eea}
.tab:hover{color:#4a5568}
.content{display:none;padding:20px 16px;max-width:1100px;margin:0 auto}
.content.active{display:block}

/* cards */
.stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:20px}
.stat-card{background:#fff;border-radius:12px;padding:16px;box-shadow:0 1px 6px rgba(0,0,0,.07)}
.stat-card .val{font-size:1.8rem;font-weight:700;color:#667eea}
.stat-card .lbl{font-size:.8rem;color:#718096;margin-top:4px}

/* table */
.table-wrap{background:#fff;border-radius:12px;box-shadow:0 1px 6px rgba(0,0,0,.07);overflow:hidden}
table{width:100%;border-collapse:collapse;font-size:.88rem}
th{background:#f7fafc;padding:10px 12px;text-align:left;font-size:.8rem;
   color:#718096;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid #e2e8f0}
td{padding:10px 12px;border-bottom:1px solid #f0f4f8;vertical-align:top;line-height:1.4}
tr:last-child td{border:none}
tr:hover td{background:#fafbff}
.badge{display:inline-block;padding:2px 8px;border-radius:20px;font-size:.75rem;font-weight:600}
.badge-ok{background:#c6f6d5;color:#276749}
.badge-err{background:#fed7d7;color:#9b2c2c}
.badge-type{background:#e9d8fd;color:#553c9a}

/* buttons */
.btn-primary{background:#667eea;color:#fff;border:none;padding:9px 18px;
             border-radius:8px;cursor:pointer;font-size:.9rem;font-weight:600}
.btn-primary:hover{background:#5a67d8}
.btn-danger{background:#fc8181;color:#fff;border:none;padding:5px 10px;
            border-radius:6px;cursor:pointer;font-size:.8rem}
.btn-danger:hover{background:#e53e3e}
.btn-edit{background:#90cdf4;color:#2a4365;border:none;padding:5px 10px;
          border-radius:6px;cursor:pointer;font-size:.8rem}
.btn-edit:hover{background:#63b3ed}
.btn-sm{padding:7px 14px;font-size:.85rem}

/* modal */
.modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);
          z-index:200;align-items:center;justify-content:center}
.modal-bg.open{display:flex}
.modal{background:#fff;border-radius:16px;padding:28px;width:520px;max-width:95vw;
       max-height:90vh;overflow-y:auto;box-shadow:0 8px 40px rgba(0,0,0,.2)}
.modal h2{font-size:1.1rem;margin-bottom:18px;color:#1a202c}
.form-row{margin-bottom:14px}
.form-row label{display:block;font-size:.82rem;color:#4a5568;margin-bottom:5px;font-weight:600}
.form-row input,.form-row textarea,.form-row select{
  width:100%;padding:9px 12px;border:1.5px solid #e2e8f0;border-radius:8px;
  font-size:.9rem;outline:none;font-family:inherit}
.form-row input:focus,.form-row textarea:focus,.form-row select:focus{border-color:#667eea}
.form-row textarea{resize:vertical;min-height:70px}
.modal-footer{display:flex;justify-content:flex-end;gap:10px;margin-top:20px}
.btn-cancel{background:#e2e8f0;color:#4a5568;border:none;padding:9px 18px;
            border-radius:8px;cursor:pointer;font-size:.9rem;font-weight:600}
.btn-cancel:hover{background:#cbd5e0}

/* toolbar */
.toolbar{display:flex;justify-content:space-between;align-items:center;
         padding:14px 16px;border-bottom:1px solid #e2e8f0}
.toolbar h2{font-size:1rem;font-weight:700;color:#2d3748}

/* notice */
.notice{padding:10px 16px;border-radius:8px;font-size:.88rem;margin-bottom:16px}
.notice-info{background:#ebf8ff;color:#2b6cb0;border-left:4px solid #4299e1}
.notice-ok{background:#f0fff4;color:#276749;border-left:4px solid #48bb78}
.notice-warn{background:#fffbeb;color:#92400e;border-left:4px solid #f6ad55}

/* env */
.env-table td:first-child{font-family:monospace;background:#f7fafc;color:#553c9a;
                           font-size:.85rem;width:220px}
.env-table td:last-child{color:#2d3748;font-size:.88rem}
.check{color:#38a169;font-weight:700}
.cross{color:#e53e3e;font-weight:700}

/* util */
.text-muted{color:#a0aec0;font-size:.8rem}
#save-status{font-size:.9rem;color:#276749;margin-left:12px;display:none}
</style></head><body>

<div class="header">
  <h1>🤖 LINE Bot 後台管理</h1>
  <a class="logout" href="/admin/logout">登出</a>
</div>

<div class="tabs">
  <div class="tab active" onclick="switchTab('stores')">🏪 商店管理</div>
  <div class="tab" onclick="switchTab('logs')">📋 互動記錄</div>
  <div class="tab" onclick="switchTab('status')">💡 服務狀態</div>
  <div class="tab" onclick="switchTab('env')">⚙️ 環境設定</div>
</div>

<!-- ────────── 商店管理 ────────── -->
<div id="tab-stores" class="content active">
  <div class="toolbar">
    <h2>商店列表</h2>
    <div style="display:flex;align-items:center">
      <span id="save-status">✅ 已儲存</span>
      <button class="btn-primary btn-sm" onclick="openAddModal()">＋ 新增商店</button>
    </div>
  </div>
  <div id="github-notice" style="padding:12px 16px 0"></div>
  <div class="table-wrap" style="margin:12px 16px">
    <table id="store-table">
      <thead><tr>
        <th>#</th><th>名稱</th><th>分類</th><th>優惠說明</th><th>網址</th><th>操作</th>
      </tr></thead>
      <tbody id="store-tbody"><tr><td colspan="6" style="text-align:center;color:#a0aec0;padding:30px">載入中…</td></tr></tbody>
    </table>
  </div>
</div>

<!-- ────────── 互動記錄 ────────── -->
<div id="tab-logs" class="content">
  <div class="toolbar">
    <h2>最近互動記錄（最多 300 筆，重啟後清零）</h2>
    <button class="btn-primary btn-sm" onclick="loadLogs()">🔄 重新整理</button>
  </div>
  <div class="table-wrap" style="margin:12px 16px">
    <table>
      <thead><tr>
        <th>時間</th><th>用戶</th><th>訊息</th><th>回應類型</th><th>結果</th>
      </tr></thead>
      <tbody id="log-tbody"><tr><td colspan="5" style="text-align:center;color:#a0aec0;padding:30px">切換至此分頁自動載入</td></tr></tbody>
    </table>
  </div>
</div>

<!-- ────────── 服務狀態 ────────── -->
<div id="tab-status" class="content">
  <div class="stat-grid" id="stat-grid" style="padding:4px 0">
    <div class="stat-card"><div class="val" id="s-uptime">—</div><div class="lbl">服務運行時間</div></div>
    <div class="stat-card"><div class="val" id="s-ok" style="color:#38a169">—</div><div class="lbl">成功回應筆數</div></div>
    <div class="stat-card"><div class="val" id="s-err" style="color:#e53e3e">—</div><div class="lbl">錯誤次數</div></div>
    <div class="stat-card"><div class="val" id="s-last" style="font-size:1rem">—</div><div class="lbl">最後活動時間</div></div>
  </div>
  <div style="padding:0 0 16px">
    <div class="notice notice-info" id="s-start">啟動時間：載入中…</div>
    <div class="notice" id="s-github-status">GitHub 狀態：載入中…</div>
  </div>
  <button class="btn-primary btn-sm" onclick="loadStatus()">🔄 重新整理</button>
</div>

<!-- ────────── 環境設定 ────────── -->
<div id="tab-env" class="content">
  <div class="notice notice-warn" style="margin-bottom:16px">
    ⚠️ 環境變數值在此不顯示，請前往
    <a href="https://dashboard.render.com/web/srv-d8afv3q8qa3s73eq8ptg/env" target="_blank" style="color:#744210">
      Render 環境設定
    </a> 管理。
  </div>
  <div class="table-wrap">
    <table class="env-table">
      <thead><tr><th>變數名稱</th><th>說明與狀態</th></tr></thead>
      <tbody id="env-tbody">
        <tr><td>LINE_CHANNEL_SECRET</td><td>LINE Channel Secret（必填）</td></tr>
        <tr><td>LINE_CHANNEL_ACCESS_TOKEN</td><td>LINE Channel Access Token（必填）</td></tr>
        <tr><td>GEMINI_API_KEY</td><td>Google Gemini API 金鑰（必填）</td></tr>
        <tr><td>ADMIN_PASSWORD</td><td>後台登入密碼（必填）<span id="env-pw"></span></td></tr>
        <tr><td>SECRET_KEY</td><td>Flask session 加密金鑰（必填）</td></tr>
        <tr><td>GITHUB_TOKEN</td><td>GitHub Personal Access Token，允許商店資料儲存至 GitHub<span id="env-gh"></span></td></tr>
        <tr><td>GITHUB_REPO</td><td>GitHub 倉庫路徑（預設：chris-yl-tw/line-ai-bot）<span id="env-repo"></span></td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- ────────── 新增/編輯 Modal ────────── -->
<div class="modal-bg" id="store-modal">
  <div class="modal">
    <h2 id="modal-title">新增商店</h2>
    <input type="hidden" id="edit-idx" value="-1">
    <div class="form-row"><label>商店名稱 *</label><input id="f-name" placeholder="例：昭日餐飲"></div>
    <div class="form-row"><label>副標題</label><input id="f-subtitle" placeholder="例：昭日堂燒肉 / 鍋好日"></div>
    <div class="form-row">
      <label>分類 *</label>
      <select id="f-category">
        <option>🍽️ 餐飲</option><option>🛍️ 購物</option><option>📱 通訊</option>
        <option>🎉 休閒</option><option>🚗 汽車</option><option>🏥 醫療</option>
        <option>🏨 住宿</option>
      </select>
    </div>
    <div class="form-row"><label>優惠說明 *</label><textarea id="f-benefit" rows="3" placeholder="例：出示識別證享 9 折優惠"></textarea></div>
    <div class="form-row"><label>商店網址（選填）</label><input id="f-url" placeholder="https://…"></div>
    <div class="form-row"><label>圖片網址（選填）</label><input id="f-image-url" placeholder="https://… (HTTPS 圖片連結)"><p style="font-size:11px;color:#999;margin:2px 0 0">建議比例 20:13，可用 Imgur 或官網圖片</p></div>
    <div class="form-row"><label>關鍵字（逗號分隔）</label><input id="f-keywords" placeholder="例：昭日,鍋好日"></div>
    <div class="modal-footer">
      <button class="btn-cancel" onclick="closeModal()">取消</button>
      <button class="btn-primary" onclick="saveStore()">儲存</button>
    </div>
  </div>
</div>

<script>
let stores = [];

// ── Tab 切換 ──
function switchTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.content').forEach(c => c.classList.remove('active'));
  const idx = ['stores','logs','status','env'].indexOf(name);
  document.querySelectorAll('.tab')[idx].classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
  if (name === 'logs')   loadLogs();
  if (name === 'status') loadStatus();
  if (name === 'env')    loadEnv();
}

// ── 商店管理 ──
async function loadStores() {
  const r = await fetch('/admin/api/stores');
  stores = await r.json();
  renderStores();
}

function renderStores() {
  const tbody = document.getElementById('store-tbody');
  if (!stores.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#a0aec0;padding:30px">尚無商店資料</td></tr>';
    return;
  }
  tbody.innerHTML = stores.map((s, i) => `
    <tr>
      <td class="text-muted">${i + 1}</td>
      <td><strong>${esc(s.name)}</strong><br><span class="text-muted">${esc(s.subtitle||'')}</span></td>
      <td><span class="badge badge-type">${esc(s.category)}</span></td>
      <td>${esc(s.benefit)}</td>
      <td>${s.url ? `<a href="${esc(s.url)}" target="_blank" style="color:#667eea;font-size:.8rem">連結</a>` : '<span class="text-muted">—</span>'}</td>
      <td style="white-space:nowrap">
        <button class="btn-edit" onclick="openEditModal(${i})">編輯</button>
        <button class="btn-danger" onclick="deleteStore(${i})" style="margin-left:4px">刪除</button>
      </td>
    </tr>`).join('');
}

function openAddModal() {
  document.getElementById('modal-title').textContent = '新增商店';
  document.getElementById('edit-idx').value = -1;
  ['name','subtitle','benefit','url','keywords'].forEach(k => document.getElementById('f-'+k).value = '');
  document.getElementById('f-category').value = '🍽️ 餐飲';
  document.getElementById('f-image-url').value = '';
  document.getElementById('store-modal').classList.add('open');
}

function openEditModal(idx) {
  const s = stores[idx];
  document.getElementById('modal-title').textContent = '編輯商店';
  document.getElementById('edit-idx').value = idx;
  document.getElementById('f-name').value = s.name || '';
  document.getElementById('f-subtitle').value = s.subtitle || '';
  document.getElementById('f-category').value = s.category || '🍽️ 餐飲';
  document.getElementById('f-benefit').value = s.benefit || '';
  document.getElementById('f-url').value = s.url || '';
  document.getElementById('f-image-url').value = s.image_url || '';
  document.getElementById('f-keywords').value = (s.keywords || []).join(', ');
  document.getElementById('store-modal').classList.add('open');
}

function closeModal() {
  document.getElementById('store-modal').classList.remove('open');
}

function saveStore() {
  const name    = document.getElementById('f-name').value.trim();
  const benefit = document.getElementById('f-benefit').value.trim();
  if (!name || !benefit) { alert('名稱與優惠說明為必填欄位'); return; }

  const entry = {
    name,
    subtitle:  document.getElementById('f-subtitle').value.trim(),
    category:  document.getElementById('f-category').value,
    benefit,
    url: document.getElementById('f-url').value.trim() || null,
    image_url: document.getElementById('f-image-url').value.trim() || null,
    keywords:  document.getElementById('f-keywords').value.split(',').map(k => k.trim()).filter(Boolean),
  };

  const idx = parseInt(document.getElementById('edit-idx').value);
  if (idx === -1) stores.push(entry);
  else            stores[idx] = entry;

  closeModal();
  renderStores();
  commitStores();
}

function deleteStore(idx) {
  if (!confirm(`確定要刪除「${stores[idx].name}」？`)) return;
  stores.splice(idx, 1);
  renderStores();
  commitStores();
}

async function commitStores() {
  const notice = document.getElementById('github-notice');
  const saveStatus = document.getElementById('save-status');
  notice.innerHTML = '<div class="notice notice-warn">💾 儲存中…</div>';
  saveStatus.style.display = 'none';
  try {
    const r = await fetch('/admin/api/stores', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(stores),
    });
    const d = await r.json();
    notice.innerHTML = `<div class="notice ${d.ok ? 'notice-ok' : 'notice-warn'}">${esc(d.msg)}</div>`;
    if (d.ok) { saveStatus.style.display = 'inline'; setTimeout(() => saveStatus.style.display = 'none', 4000); }
  } catch(e) {
    notice.innerHTML = '<div class="notice notice-warn">⚠️ 儲存失敗，請確認網路連線</div>';
  }
}

// ── 互動記錄 ──
async function loadLogs() {
  const r = await fetch('/admin/api/logs');
  const logs = await r.json();
  const tbody = document.getElementById('log-tbody');
  if (!logs.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#a0aec0;padding:30px">尚無記錄</td></tr>';
    return;
  }
  tbody.innerHTML = logs.map(l => `
    <tr>
      <td class="text-muted" style="white-space:nowraw">${esc(l.time)}</td>
      <td>${esc(l.user)}<br><span class="text-muted">${esc(l.uid)}</span></td>
      <td>${esc(l.msg)}</td>
      <td><span class="badge badge-type">${esc(l.type)}</span></td>
      <td><span class="badge ${l.ok ? 'badge-ok' : 'badge-err'}">${l.ok ? '成功' : '失敗'}</span></td>
    </tr>`).join('');
}

// ── 服務狀態 ──
async function loadStatus() {
  const r = await fetch('/admin/api/status');
  const d = await r.json();
  document.getElementById('s-uptime').textContent = d.uptime;
  document.getElementById('s-ok').textContent = d.total_ok;
  document.getElementById('s-err').textContent = d.total_err;
  document.getElementById('s-last').textContent = d.last_active;
  document.getElementById('s-start').textContent = '🕐 服務啟動時間：' + d.start_time;
  const ghEl = document.getElementById('s-github-status');
  if (d.github_token_set) {
    ghEl.className = 'notice notice-ok';
    ghEl.textContent = '✅ GitHub Token 已設定，倉庫：' + d.github_repo;
  } else {
    ghEl.className = 'notice notice-warn';
    ghEl.textContent = '⚠️ 未設定 GITHUB_TOKEN，商店修改不會儲存至 GitHub（重啟後會遺失）';
  }
}

// ── 環境設定 ──
async function loadEnv() {
  const r = await fetch('/admin/api/status');
  const d = await r.json();
  document.getElementById('env-gh').innerHTML = d.github_token_set
    ? ' <span class="check">✓ 已設定</span>' : ' <span class="cross">✗ 未設定</span>';
  document.getElementById('env-repo').innerHTML = ` <span class="text-muted">(${d.github_repo})</span>`;
}

// ── 工具函式 ──
function esc(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── 初始化 ──
loadStores();
</script></body></html>
"""
