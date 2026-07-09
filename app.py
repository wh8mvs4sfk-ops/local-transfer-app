import os
import socket
import io
import qrcode
import json
import time
import threading
from flask import Flask, render_template, request, send_from_directory, redirect, url_for, send_file
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'apple-style-transfer-key!'
# 开启异步模式支持，提升并发性能
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
HISTORY_FILE = 'history.json'

# ==========================================
# 工业级性能与安全配置
# ==========================================
current_ttl = 86400        # 默认 24 小时
CHECK_INTERVAL = 30        # 优化：巡查间隔提升至 30 秒，极大地降低 CPU 与磁盘 I/O 占用
MAX_MESSAGES = 50          # 优化：限制历史记录最多 50 条，防止内存溢出和 JSON 读写卡顿
data_lock = threading.Lock() # 核心：引入线程锁，避免读写冲突引发的崩溃

def auto_cleanup_files():
    """后台静默清理守护进程（低耗版）"""
    global current_ttl
    while True:
        time.sleep(CHECK_INTERVAL)
        now = time.time()
        if os.path.exists(app.config['UPLOAD_FOLDER']):
            # 加锁，防止在清理文件的瞬间，用户恰好在请求文件列表
            with data_lock:
                try:
                    for filename in os.listdir(app.config['UPLOAD_FOLDER']):
                        if filename.startswith('.'): continue
                        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                        if os.path.isfile(filepath):
                            if now - os.path.getmtime(filepath) > current_ttl:
                                os.remove(filepath)
                                print(f"[TTL] 自动销毁: {filename}")
                                socketio.emit('file_deleted', {'filename': filename})
                except Exception as e:
                    print(f"[TTL Error] 清理守护线程异常: {e}")

# 启动后台守护线程
cleanup_thread = threading.Thread(target=auto_cleanup_files, daemon=True)
cleanup_thread.start()
# ==========================================

# 优雅的数据加载机制（带防崩保护）
with data_lock:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            try:
                messages = json.load(f)
            except (json.JSONDecodeError, ValueError):
                messages = []
    else:
        messages = []

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

@app.route('/qrcode')
def get_qrcode():
    ip = get_local_ip()
    url = f"http://{ip}:5000"
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if 'file' in request.files:
            file = request.files['file']
            if file.filename != '':
                # 优化：防御路径穿越攻击 (保留中文名)
                safe_name = os.path.basename(file.filename)
                
                with data_lock:
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], safe_name))
                socketio.emit('new_file', {'filename': safe_name})
        return '', 200

    with data_lock:
        files = [f for f in os.listdir(app.config['UPLOAD_FOLDER']) if not f.startswith('.')]
    return render_template('index.html', messages=messages, files=files, ip=get_local_ip(), current_ttl=current_ttl)

@socketio.on('send_message')
def handle_message(data):
    msg = data.get('message', '').strip()
    if msg:
        with data_lock:  # 保护写操作
            messages.append(msg)
            # 限制最大长度
            if len(messages) > MAX_MESSAGES:
                messages.pop(0)
            
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(messages, f, ensure_ascii=False, indent=2)
                
        emit('new_message', {'message': msg}, broadcast=True)

@socketio.on('update_ttl')
def handle_update_ttl(data):
    global current_ttl
    try:
        with data_lock:
            current_ttl = int(data.get('ttl', 86400))
        emit('ttl_updated', {'ttl': current_ttl}, broadcast=True)
    except ValueError:
        pass

@app.route('/download/<filename>')
def download(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=False) # 正式运行建议关闭 debug