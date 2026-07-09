import os
import socket
from flask import Flask, render_template, request, send_from_directory, redirect, url_for

app = Flask(__name__)

# 配置上传文件夹
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# 在内存中临时存储文字消息
messages = []

def get_local_ip():
    """获取本机的局域网 IP 地址"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # 不需要真的连上，只是为了拿到分配给本机的 IP
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # 处理文字发送
        if 'message' in request.form:
            msg = request.form['message']
            if msg.strip():
                messages.append(msg)
        # 处理文件/图片上传
        elif 'file' in request.files:
            file = request.files['file']
            if file.filename != '':
                # 保存文件到 uploads 文件夹
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], file.filename))
        return redirect(url_for('index'))

    # 获取已上传的文件列表
    files = os.listdir(app.config['UPLOAD_FOLDER'])
    return render_template('index.html', messages=messages, files=files, ip=get_local_ip())

@app.route('/download/<filename>')
def download(filename):
    """处理文件下载"""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    # host='0.0.0.0' 允许局域网内的其他设备访问
    app.run(host='0.0.0.0', port=5000, debug=True)