import os
import socket
import io
import qrcode
import json
from flask import Flask, render_template, request, send_from_directory, redirect, url_for, send_file

app = Flask(__name__)

# 配置文件夹和文件路径
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
HISTORY_FILE = 'history.json'

# 程序启动时，加载历史记录
if os.path.exists(HISTORY_FILE):
    with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
        try:
            messages = json.load(f)
        except json.JSONDecodeError:
            messages = []
else:
    messages = []

def get_local_ip():
    """获取本机的局域网 IP 地址"""
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
    """动态生成当前局域网 IP 的二维码"""
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
        # 处理文字发送
        if 'message' in request.form:
            msg = request.form['message']
            if msg.strip():
                messages.append(msg)
                # 写入 JSON 文件，实现永久保存 (ensure_ascii=False 保证中文正常显示)
                with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                    json.dump(messages, f, ensure_ascii=False, indent=2)
                    
        # 处理文件/图片上传
        elif 'file' in request.files:
            file = request.files['file']
            if file.filename != '':
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], file.filename))
        return redirect(url_for('index'))

    # 获取已上传的文件列表
    files = os.listdir(app.config['UPLOAD_FOLDER'])
    # 过滤掉可能存在的 .gitkeep 隐藏文件
    files = [f for f in files if not f.startswith('.')]
    
    return render_template('index.html', messages=messages, files=files, ip=get_local_ip())

@app.route('/download/<filename>')
def download(filename):
    """处理文件下载"""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)