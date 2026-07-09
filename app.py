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
socketio = SocketIO(app, cors_allowed_origins="*")

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
HISTORY_FILE = 'history.json'

# ==========================================
# 动态 TTL 过期清理配置
# ==========================================
current_ttl = 86400  # 默认初始化为 24 小时 (单位：秒)
CHECK_INTERVAL = 2   # 每 2 秒巡查一次，确保短时间删除时反应足够灵敏

def auto_cleanup_files():
    """后台静默清理守护进程"""
    global current_ttl
    while True:
        time.sleep(CHECK_INTERVAL)
        now = time.time()
        if os.path.exists(app.config['UPLOAD_FOLDER']):
            for filename in os.listdir(app.config['UPLOAD_FOLDER']):
                if filename.startswith('.'): continue
                
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                if os.path.isfile(filepath):
                    file_mtime = os.path.getmtime(filepath)
                    # 动态读取当前的 current_ttl
                    if now - file_mtime > current_ttl:
                        try:
                            os.remove(filepath)
                            print(f"[TTL] 自动销毁过期文件: {filename} (当前TTL: {current_ttl}s)")
                            socketio.emit('file_deleted', {'filename': filename})
                        except Exception as e:
                            print(f"[TTL] 删除失败 {filename}: {e}")

# 启动后台守护线程
cleanup_thread = threading.Thread(target=auto_cleanup_files, daemon=True)
cleanup_thread.start()
# ==========================================

if os.path.exists(HISTORY_FILE):
    with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
        try:
            messages = json.load(f)
        except json.JSONDecodeError:
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
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], file.filename))
                socketio.emit('new_file', {'filename': file.filename})
        return '', 200

    files = os.listdir(app.config['UPLOAD_FOLDER'])
    files = [f for f in files if not f.startswith('.')]
    # 记得把当前的 current_ttl 传给前端页面，用于初始化下拉菜单的选中状态
    return render_template('index.html', messages=messages, files=files, ip=get_local_ip(), current_ttl=current_ttl)

@socketio.on('send_message')
def handle_message(data):
    msg = data.get('message', '').strip()
    if msg:
        messages.append(msg)
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)
        emit('new_message', {'message': msg}, broadcast=True)

# 新增：监听任意设备更改过期时间的请求
@socketio.on('update_ttl')
def handle_update_ttl(data):
    global current_ttl
    try:
        new_ttl = int(data.get('ttl', 86400))
        current_ttl = new_ttl
        print(f"[TTL] 局域网设置已同步！当前文件生存期变更为: {current_ttl} 秒")
        # 广播通知局域网内其他所有人，同步更新他们的下拉菜单选项
        emit('ttl_updated', {'ttl': current_ttl}, broadcast=True)
    except ValueError:
        pass

@app.route('/download/<filename>')
def download(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)