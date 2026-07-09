import os
import socket
import io
import qrcode
import json
import time
import threading
import random
from flask import Flask, render_template, request, send_from_directory, send_file, jsonify
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'apple-style-transfer-key!'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
HISTORY_FILE = 'history.json'

# ==========================================
# 1. 核心系统配置与 PIN 码生成
# ==========================================
current_ttl = 86400        
CHECK_INTERVAL = 30        
MAX_MESSAGES = 50          
data_lock = threading.Lock() 

# 生成动态 4 位数 PIN 码
ACCESS_PIN = f"{random.randint(0, 9999):04d}"
print(f"\n{'='*55}")
print(f" 🔐 本机动态访问 PIN 码: {ACCESS_PIN} ")
print(f" (手机扫码后，需输入此密码方可进入应用)")
print(f"{'='*55}\n")

# ==========================================
# 2. 核心路由与 PWA 清单
# ==========================================
# 动态生成 PWA manifest (无需手动创建文件)
@app.route('/manifest.json')
def manifest():
    return jsonify({
        "name": "局域网快传",
        "short_name": "快传",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#f5f5f7",
        "theme_color": "#f5f5f7",
        "icons": [{
            "src": "https://api.iconify.design/sf-symbols:airdrop.svg", 
            "sizes": "192x192", 
            "type": "image/svg+xml"
        }]
    })

# PIN 码校验接口
@app.route('/api/verify_pin', methods=['POST'])
def verify_pin():
    data = request.json
    if data and data.get('pin') == ACCESS_PIN:
        return jsonify({"status": "ok"})
    return jsonify({"status": "error"}), 403

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

@app.route('/', methods=['GET'])
def index():
    # 判断访问者是不是主机自己
    client_ip = request.remote_addr
    is_localhost = client_ip in ['127.0.0.1', '::1', 'localhost']
    
    with data_lock:
        files = [f for f in os.listdir(app.config['UPLOAD_FOLDER']) if not f.startswith('.')]
    
    # 极客安全防御：只有本机访问时才下发真实 PIN 码渲染在页面上，客机访问时此变量为空，防止源码泄露
    safe_pin = ACCESS_PIN if is_localhost else ""
    
    return render_template('index.html', 
                           messages=messages, 
                           files=files, 
                           ip=get_local_ip(), 
                           current_ttl=current_ttl,
                           is_localhost=is_localhost,
                           access_pin=safe_pin)

@app.route('/qrcode')
def get_qrcode():
    ip = get_local_ip()
    url = f"http://{ip}:5000"
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')

# ==========================================
# 3. 架构级大文件切片上传处理 (Chunked Upload)
# ==========================================
@app.route('/upload_chunk', methods=['POST'])
def upload_chunk():
    # 每次上传块都会严格校验 PIN 码
    if request.headers.get('X-PIN') != ACCESS_PIN:
        return "Unauthorized", 403

    file = request.files['chunk']
    filename = request.form['filename']
    file_id = request.form['file_id']
    chunk_index = int(request.form['chunk_index'])
    total_chunks = int(request.form['total_chunks'])

    safe_name = os.path.basename(filename)
    # 生成隐藏的临时切片文件
    temp_path = os.path.join(app.config['UPLOAD_FOLDER'], f".{file_id}_{safe_name}.tmp")

    with data_lock:
        # 'ab' 模式：以二进制追加方式写入文件块
        with open(temp_path, 'ab') as f:
            f.write(file.read())

    # 如果是最后一块，将其重命名为正式文件并广播通知
    if chunk_index == total_chunks - 1:
        final_path = os.path.join(app.config['UPLOAD_FOLDER'], safe_name)
        with data_lock:
            if os.path.exists(final_path):
                os.remove(final_path) # 覆盖同名文件
            os.rename(temp_path, final_path)
        socketio.emit('new_file', {'filename': safe_name})

    return '', 200

# ==========================================
# 4. 后台守护进程与 Socket.IO 通信
# ==========================================
def auto_cleanup_files():
    global current_ttl
    while True:
        time.sleep(CHECK_INTERVAL)
        now = time.time()
        if os.path.exists(app.config['UPLOAD_FOLDER']):
            with data_lock:
                try:
                    for filename in os.listdir(app.config['UPLOAD_FOLDER']):
                        if filename.startswith('.'): continue
                        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                        if os.path.isfile(filepath):
                            if now - os.path.getmtime(filepath) > current_ttl:
                                os.remove(filepath)
                                socketio.emit('file_deleted', {'filename': filename})
                except Exception as e:
                    pass

cleanup_thread = threading.Thread(target=auto_cleanup_files, daemon=True)
cleanup_thread.start()

with data_lock:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            try: messages = json.load(f)
            except: messages = []
    else:
        messages = []

@socketio.on('send_message')
def handle_message(data):
    if data.get('pin') != ACCESS_PIN: return
    msg = data.get('message', '').strip()
    if msg:
        with data_lock:
            messages.append(msg)
            if len(messages) > MAX_MESSAGES: messages.pop(0)
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(messages, f, ensure_ascii=False, indent=2)
        emit('new_message', {'message': msg}, broadcast=True)

@socketio.on('update_ttl')
def handle_update_ttl(data):
    if data.get('pin') != ACCESS_PIN: return
    global current_ttl
    try:
        with data_lock:
            current_ttl = int(data.get('ttl', 86400))
        emit('ttl_updated', {'ttl': current_ttl}, broadcast=True)
    except ValueError:
        pass

@app.route('/download/<filename>')
def download(filename):
    # 下载时简单校验一下 PIN，防止直链盗刷
    if request.args.get('pin') != ACCESS_PIN and not (request.remote_addr in ['127.0.0.1', '::1', 'localhost']):
         # 为了防止某些浏览器下载管理器不带参数，这里做柔性拦截或放行。
         # 严格模式可直接 return "Unauthorized", 403
         pass
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)