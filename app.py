import os
import socket
import io
import qrcode
import json
import time
import threading
import random
import platform
import subprocess
from flask import Flask, render_template, request, send_from_directory, send_file, jsonify
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'apple-style-transfer-key-pro-999!'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
HISTORY_FILE = 'history.json'

current_ttl = 86400        
CHECK_INTERVAL = 30        
MAX_MESSAGES = 50          
data_lock = threading.Lock() 

ACCESS_PIN = f"{random.randint(0, 9999):04d}"
print(f"\n{'='*55}")
print(f" 🔐 本机动态访问 PIN 码: {ACCESS_PIN} ")
print(f"{'='*55}\n")

failed_attempts = {}
LOCKOUT_THRESHOLD = 5      
LOCKOUT_DURATION = 300     

# ==========================================
# 新增主机特权接口：一键呼出本地资源管理器
# ==========================================
@app.route('/api/open_folder', methods=['POST'])
def open_folder():
    client_ip = request.remote_addr
    is_localhost = client_ip in ['127.0.0.1', '::1', 'localhost']
    
    # 严格审查：非本机客户端一律无条件拒绝执行
    if not is_localhost:
        return jsonify({"status": "forbidden"}), 403
        
    folder_path = os.path.abspath(app.config['UPLOAD_FOLDER'])
    try:
        if platform.system() == "Windows":
            os.startfile(folder_path)
        elif platform.system() == "Darwin":  # macOS
            subprocess.Popen(["open", folder_path])
        else:  # Linux
            subprocess.Popen(["xdg-open", folder_path])
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/verify_pin', methods=['POST'])
def verify_pin():
    client_ip = request.remote_addr
    now = time.time()
    if client_ip in failed_attempts:
        attempts, lock_time = failed_attempts[client_ip]
        if attempts >= LOCKOUT_THRESHOLD:
            if now - lock_time < LOCKOUT_DURATION:
                remaining = int(LOCKOUT_DURATION - (now - lock_time))
                return jsonify({"status": "locked", "message": f"尝试次数过多，请在 {remaining} 秒后再试"}), 429
            else:
                failed_attempts[client_ip] = [0, 0]

    data = request.json
    if data and data.get('pin') == ACCESS_PIN:
        failed_attempts[client_ip] = [0, 0] 
        return jsonify({"status": "ok"})
    
    if client_ip not in failed_attempts:
        failed_attempts[client_ip] = [0, 0]
    failed_attempts[client_ip][0] += 1
    failed_attempts[client_ip][1] = now
    return jsonify({"status": "error"}), 403

@app.route('/', methods=['GET'])
def index():
    client_ip = request.remote_addr
    is_localhost = client_ip in ['127.0.0.1', '::1', 'localhost']
    with data_lock:
        files = [f for f in os.listdir(app.config['UPLOAD_FOLDER']) if not f.startswith('.')]
    safe_pin = ACCESS_PIN if is_localhost else ""
    return render_template('index.html', messages=messages, files=files, ip=get_local_ip(), current_ttl=current_ttl, is_localhost=is_localhost, access_pin=safe_pin)

@app.route('/download/<filename>')
def download(filename):
    client_ip = request.remote_addr
    is_localhost = client_ip in ['127.0.0.1', '::1', 'localhost']
    if not is_localhost:
        user_pin = request.args.get('pin')
        if user_pin != ACCESS_PIN:
            return "Unauthorized", 403
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

@app.route('/upload_chunk', methods=['POST'])
def upload_chunk():
    if request.headers.get('X-PIN') != ACCESS_PIN: return "Unauthorized", 403
    file = request.files['chunk']
    filename = request.form['filename']
    file_id = request.form['file_id']
    chunk_index = int(request.form['chunk_index'])
    total_chunks = int(request.form['total_chunks'])
    safe_name = os.path.basename(filename)
    temp_path = os.path.join(app.config['UPLOAD_FOLDER'], f".{file_id}_{safe_name}.tmp")
    with data_lock:
        with open(temp_path, 'ab') as f: f.write(file.read())
    if chunk_index == total_chunks - 1:
        final_path = os.path.join(app.config['UPLOAD_FOLDER'], safe_name)
        with data_lock:
            if os.path.exists(final_path): os.remove(final_path)
            os.rename(temp_path, final_path)
        socketio.emit('new_file', {'filename': safe_name}, room='authenticated_zone')
    return '', 200

@socketio.on('join_auth_room')
def on_join(data):
    client_ip = request.remote_addr
    is_localhost = client_ip in ['127.0.0.1', '::1', 'localhost']
    if data.get('pin') == ACCESS_PIN or is_localhost:
        join_room('authenticated_zone')
        emit('auth_status', {'status': 'verified'})
    else:
        emit('auth_status', {'status': 'denied'})

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
        socketio.emit('new_message', {'message': msg}, room='authenticated_zone')

@socketio.on('delete_message')
def handle_delete_message(data):
    if data.get('pin') != ACCESS_PIN: return
    msg = data.get('message')
    if not msg: return
    with data_lock:
        if msg in messages:
            messages.remove(msg)
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(messages, f, ensure_ascii=False, indent=2)
            socketio.emit('message_deleted', {'message': msg}, room='authenticated_zone')

@socketio.on('delete_file')
def handle_delete_file(data):
    if data.get('pin') != ACCESS_PIN: return
    filename = data.get('filename')
    if not filename: return
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], os.path.basename(filename))
    with data_lock:
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                socketio.emit('file_deleted', {'filename': filename}, room='authenticated_zone')
            except Exception: pass

@socketio.on('update_ttl')
def handle_update_ttl(data):
    if data.get('pin') != ACCESS_PIN: return
    global current_ttl
    try:
        with data_lock: current_ttl = int(data.get('ttl', 86400))
        socketio.emit('ttl_updated', {'ttl': current_ttl}, room='authenticated_zone')
    except ValueError: pass

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
                                socketio.emit('file_deleted', {'filename': filename}, room='authenticated_zone')
                except Exception: pass

cleanup_thread = threading.Thread(target=auto_cleanup_files, daemon=True)
cleanup_thread.start()

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception: IP = '127.0.0.1'
    finally: s.close()
    return IP

with data_lock:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            try: messages = json.load(f)
            except: messages = []
    else: messages = []

@app.route('/qrcode')
def get_qrcode():
    ip = get_local_ip()
    url = f"http://{ip}:5000"
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)