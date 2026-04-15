from flask import Flask, render_template, request, jsonify, session, redirect
import cv2
import os
from ultralytics import YOLO
import uuid
import sqlite3

app = Flask(__name__)
app.secret_key = "mysecretkey"

UPLOAD_FOLDER = "uploads"
STATIC_FOLDER = "static"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(STATIC_FOLDER, exist_ok=True)

model = YOLO("yolov8m.pt")

# ================= DATABASE =================
def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        password TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        slots_booked INTEGER)''')

    c.execute('''CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        image TEXT,
        total INTEGER,
        occupied INTEGER,
        available INTEGER)''')

    conn.commit()
    conn.close()

init_db()

# ================= DETECTION =================
def detect_bikes(image_path):
    img = cv2.imread(image_path)
    if img is None:
        return 0, None

    img = cv2.resize(img, (1024, 768))
    results = model(img, conf=0.25)

    count = 0
    for r in results:
        for box in r.boxes:
            cls = int(box.cls[0])
            label = model.names[cls]
            conf = float(box.conf[0])

            if label in ["bicycle", "motorcycle"] and conf > 0.4:
                count += 1
                x1,y1,x2,y2 = map(int, box.xyxy[0])
                cv2.rectangle(img,(x1,y1),(x2,y2),(0,255,0),2)

    return count, img

# ================= SLOT =================
def estimate_slots(count):
    if count == 0:
        total = 10
    elif count <= 5:
        total = count + 5
    elif count <= 20:
        total = int(count * 1.5)
    else:
        total = int(count * 1.3)

    available = max(0, total - count)
    return total, available

# ================= AUTH =================
@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        u = request.form['username']
        p = request.form['password']

        conn = sqlite3.connect('database.db')
        conn.execute("INSERT INTO users (username,password) VALUES (?,?)",(u,p))
        conn.commit()
        conn.close()

        return redirect('/login')
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        u = request.form['username']
        p = request.form['password']

        conn = sqlite3.connect('database.db')
        user = conn.execute("SELECT * FROM users WHERE username=? AND password=?",(u,p)).fetchone()
        conn.close()

        if user:
            session['user'] = u
            return redirect('/')
        return "Invalid login"

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user',None)
    return redirect('/login')

# ================= HOME =================
@app.route('/')
def home():
    if 'user' not in session:
        return redirect('/login')
    return render_template('index.html')

# ================= UPLOAD =================
@app.route('/upload', methods=['POST'])
def upload():
    if 'user' not in session:
        return jsonify({"error":"login required"})

    file = request.files['image']
    filename = str(uuid.uuid4())+".jpg"
    path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(path)

    count, img = detect_bikes(path)
    total, available = estimate_slots(count)

    out_name = "out_"+uuid.uuid4().hex+".jpg"
    out_path = os.path.join(STATIC_FOLDER, out_name)
    cv2.imwrite(out_path, img)

    conn = sqlite3.connect('database.db')
    conn.execute("INSERT INTO history (username,image,total,occupied,available) VALUES (?,?,?,?,?)",
                 (session['user'], "/static/"+out_name, total, count, available))
    conn.commit()
    conn.close()

    return jsonify({
        "total": total,
        "occupied": count,
        "available": available,
        "status": "Full ❌" if available==0 else "Available ✅",
        "image": "/static/"+out_name
    })

# ================= BOOK =================
@app.route('/book', methods=['POST'])
def book():
    if 'user' not in session:
        return redirect('/login')

    slots = int(request.form['slots'])

    conn = sqlite3.connect('database.db')
    conn.execute("INSERT INTO bookings (username,slots_booked) VALUES (?,?)",
                 (session['user'], slots))
    conn.commit()
    conn.close()

    return f"{slots} slots booked successfully!"

# ================= HISTORY =================
@app.route('/history')
def history():
    if 'user' not in session:
        return redirect('/login')

    conn = sqlite3.connect('database.db')

    detections = conn.execute(
        "SELECT id,image,total,occupied,available FROM history WHERE username=?",
        (session['user'],)
    ).fetchall()

    bookings = conn.execute(
        "SELECT slots_booked FROM bookings WHERE username=?",
        (session['user'],)
    ).fetchall()

    conn.close()

    return render_template('history.html', detections=detections, bookings=bookings)

# ================= DELETE =================
@app.route('/delete_history/<int:id>')
def delete_history(id):
    conn = sqlite3.connect('database.db')
    conn.execute("DELETE FROM history WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect('/history')

@app.route('/delete_all_history')
def delete_all_history():
    conn = sqlite3.connect('database.db')
    conn.execute("DELETE FROM history WHERE username=?", (session['user'],))
    conn.commit()
    conn.close()
    return redirect('/history')

# ================= RUN =================
if __name__ == '__main__':
    app.run(debug=True)