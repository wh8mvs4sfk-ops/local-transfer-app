import os
import socket
import io
import qrcode
import json
from flask import Flask, render_template, request, send_from_directory, redirect, url_for, send_file
from flask_socketio import SocketIO, emit  # 新增：引入 SocketIO

app = Flask(__name__)
app.config['SECRET_KEY'] = 'apple-style-transfer-key!'
# 初始化 SocketIO，允许跨域访问
socketio = SocketIO(app, cors_allowed_origins="*")

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
HISTORY_FILE = 'history.json'

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
        # HTTP POST 现在只专门处理文件/图片上传（大文件走 HTTP 更稳定）
        if 'file' in request.files:
            file = request.files['file']
            if file.filename != '':
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], file.filename))
                # 关键：文件保存成功后，通过 WebSocket 实时通知所有在线设备
                socketio.emit('new_file', {'filename': file.filename})
        return '', 200  # 返回空内容和 200 状态码，告诉前端 AJAX 上传成功

    files = os.listdir(app.config['UPLOAD_FOLDER'])
    files = [f for f in files if not f.startswith('.')]
    return render_template('index.html', messages=messages, files=files, ip=get_local_ip())

# 新增：监听前端通过 WebSocket 发送的文字消息
@socketio.on('send_message')
def handle_message(data):
    msg = data.get('message', '').strip()
    if msg:
        messages.append(msg)
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)
        # 关键：将新消息实时广播给局域网内的所有人
        emit('new_message', {'message': msg}, broadcast=True)

@app.route('/download/<filename>')
def download(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    # 关键：将 app.run 换成 socketio.run 启动服务
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)