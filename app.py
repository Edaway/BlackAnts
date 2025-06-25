from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, os

app = Flask(__name__)
app.secret_key = 'supersecret'
app.config['UPLOAD_FOLDER'] = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    city = request.args.get('city', '')
    job_type = request.args.get('job_type', '')
    payment_type = request.args.get('payment_type', '')

    query = "SELECT v.*, u.first_name, u.last_name, u.photo FROM vacancies v JOIN users u ON v.user_id = u.id WHERE 1=1"
    params = []

    if city:
        query += " AND v.location LIKE ?"
        params.append(f"%{city}%")
    if job_type:
        query += " AND v.job_type = ?"
        params.append(job_type)
    if payment_type:
        query += " AND v.payment_type = ?"
        params.append(payment_type)

    conn = get_db()
    vacancies = conn.execute(query, params).fetchall()
    conn.close()
    return render_template('index.html', vacancies=vacancies)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.form
        photo = request.files.get('photo')
        filename = None
        if photo and allowed_file(photo.filename):
            filename = secure_filename(photo.filename)
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            photo.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        try:
            hashed_password = generate_password_hash(data['password'])
            conn = get_db()
            conn.execute(
                "INSERT INTO users (first_name, last_name, age, gender, role, location, salary, email, password, photo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (data['first_name'], data['last_name'], data['age'], data['gender'], data['role'],
                 data.get('location'), data.get('salary'), data['email'], hashed_password, filename))
            conn.commit()
            user = conn.execute("SELECT * FROM users WHERE email = ?", (data['email'],)).fetchone()
            conn.close()
            session['user'] = dict(user)
            return redirect(url_for('profile'))
        except sqlite3.IntegrityError:
            error = "Пользователь с таким email уже существует"
            return render_template('register.html', error=error)
        except Exception as e:
            error = f"Ошибка регистрации: {e}"
            return render_template('register.html', error=error)
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        conn = get_db()
        user = conn.execute(
            'SELECT * FROM users WHERE email = ? AND password = ?',
            (request.form['email'], request.form['password'])
        ).fetchone()
        conn.close()
        if user:
            # Очень важно: сохраняем в сессию всю информацию пользователя, включая id!
            session['user'] = dict(user)
            return redirect(url_for('profile'))
        else:
            error = "Неверный email или пароль"
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('index'))

@app.route('/profile')
def profile():
    if 'user' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    user_id = session['user']['id']

    vacancies = []
    if session['user']['role'] == 'работодатель':
        vacancies = conn.execute('SELECT * FROM vacancies WHERE user_id = ?', (user_id,)).fetchall()

    applications = []
    if session['user']['role'] == 'работодатель':
        # Сообщения, где текущий пользователь — получатель (от соискателей)
        applications = conn.execute('''
            SELECT m.*, u.first_name, u.last_name
            FROM messages m
            JOIN users u ON m.sender_id = u.id
            WHERE m.receiver_id = ?
            ORDER BY m.timestamp DESC
        ''', (user_id,)).fetchall()
    else:
        # Сообщения, где текущий пользователь — получатель (от работодателей)
        applications = conn.execute('''
            SELECT m.*, u.first_name, u.last_name
            FROM messages m
            JOIN users u ON m.sender_id = u.id
            WHERE m.receiver_id = ?
            ORDER BY m.timestamp DESC
        ''', (user_id,)).fetchall()

    conn.close()
    return render_template('profile.html', user=session['user'], vacancies=vacancies, applications=applications)

@app.route('/add-vacancy', methods=['GET', 'POST'])
def add_vacancy():
    if 'user' not in session or session['user']['role'] != 'работодатель':
        return redirect(url_for('login'))

    if request.method == 'POST':
        data = request.form
        user_id = session['user']['id']
        print("👉 Добавляем вакансию:", data, "от пользователя", user_id)

        try:
            conn = get_db()
            conn.execute(
                "INSERT INTO vacancies (user_id, title, description, job_type, payment_type, location, salary) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, data['title'], data['description'], data['job_type'],
                 data['payment_type'], data['location'], data['salary'])
            )
            conn.commit()
            conn.close()
            return redirect(url_for('index'))
        except Exception as e:
            print("❌ Ошибка при добавлении вакансии:", e)
            return "Ошибка при добавлении вакансии", 500

    return render_template('add_vacancy.html')

@app.route('/chat/<int:receiver_id>', methods=['GET', 'POST'])
def chat(receiver_id):
    if 'user' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    if request.method == 'POST':
        text = request.form['text']
        conn.execute('INSERT INTO messages (sender_id, receiver_id, text) VALUES (?, ?, ?)',
                     (session['user']['id'], receiver_id, text))
        conn.commit()
    messages = conn.execute('''SELECT sender_id, text, timestamp FROM messages 
                               WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?) 
                               ORDER BY timestamp''',
                            (session['user']['id'], receiver_id, receiver_id, session['user']['id'])).fetchall()
    user = conn.execute('SELECT first_name, last_name FROM users WHERE id = ?', (receiver_id,)).fetchone()
    conn.close()
    return render_template('chat.html', messages=messages, receiver=user, receiver_id=receiver_id)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/vacancy/<int:id>/edit', methods=['GET', 'POST'])
def edit_vacancy(id):
    if 'user' not in session or session['user']['role'] != 'работодатель':
        return redirect(url_for('login'))

    conn = get_db()
    vacancy = conn.execute("SELECT * FROM vacancies WHERE id = ? AND user_id = ?", (id, session['user']['id'])).fetchone()
    if not vacancy:
        conn.close()
        return "Вакансия не найдена", 404

    if request.method == 'POST':
        data = request.form
        conn.execute("""
            UPDATE vacancies SET title=?, description=?, job_type=?, payment_type=?, location=?, salary=? 
            WHERE id=?
        """, (data['title'], data['description'], data['job_type'], data['payment_type'], data['location'], data['salary'], id))
        conn.commit()
        conn.close()
        return redirect(url_for('profile'))

    conn.close()
    return render_template('edit_vacancy.html', vacancy=vacancy)

@app.route('/vacancy/<int:id>/delete', methods=['POST'])
def delete_vacancy(id):
    if 'user' not in session or session['user']['role'] != 'работодатель':
        return redirect(url_for('login'))
    conn = get_db()
    conn.execute("DELETE FROM vacancies WHERE id = ? AND user_id = ?", (id, session['user']['id']))
    conn.commit()
    conn.close()
    return redirect(url_for('profile'))

@app.route('/ready/<int:vacancy_id>')
def ready_to_work(vacancy_id):
    if 'user' not in session or session['user']['role'] != 'соискатель':
        return redirect(url_for('login'))

    conn = get_db()
    vacancy = conn.execute("SELECT user_id FROM vacancies WHERE id = ?", (vacancy_id,)).fetchone()
    if vacancy:
        conn.execute("INSERT INTO messages (sender_id, receiver_id, text) VALUES (?, ?, ?)",
                     (session['user']['id'], vacancy['user_id'], "Готов работать по вашей вакансии!"))
        conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/user/<int:user_id>')
def view_user(user_id):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    vacancies = conn.execute("SELECT * FROM vacancies WHERE user_id = ?", (user_id,)).fetchall()
    conn.close()
    if not user:
        return "Пользователь не найден", 404
    return render_template("public_profile.html", user=user, vacancies=vacancies)

if __name__ == '__main__':
    app.run(debug=True)
