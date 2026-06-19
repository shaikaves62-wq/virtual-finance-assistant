from flask import Flask, request, render_template, redirect, url_for, flash, session
import pandas as pd
import os
import requests
import io
import base64
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')

# Auth imports
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'vinodkumar815593919959'  # Change this to a strong secret key
UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Database setup
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

GEMINI_API_KEY = "AIzaSyAK4yMRslPLOTpb4tGkvtsaukIbUIf-xpo"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

def save_plot(df):
    if df is not None and 'Category' in df.columns:
        category_spending = df[df['Amount'] < 0].groupby('Category')['Amount'].sum().abs()
        plt.figure(figsize=(4, 4))
        category_spending.plot.pie(autopct='%1.1f%%', startangle=140)
        plt.title('Spending by Category')
        plt.ylabel('')
        plt.tight_layout()
        chart = io.BytesIO()
        plt.savefig(chart, format='png')
        plt.close()
        chart.seek(0)
        plot_data = base64.b64encode(chart.read()).decode('utf8')
        return f'data:image/png;base64,{plot_data}'
    return None

def get_summary(df, csv_type):
    if df is None:
        return {}
    if csv_type == 'transactions':
        total_income = df[df['Amount'] > 0]['Amount'].sum()
        total_expenses = df[df['Amount'] < 0]['Amount'].sum()
        savings = total_income + total_expenses
        return {
            'total_income': total_income,
            'total_expenses': abs(total_expenses),
            'savings': savings
        }
    return {}

def ask_gemini(user_message, budget, df):
    try:
        income = df[df['Amount'] > 0]['Amount'].sum()
        expenses = abs(df[df['Amount'] < 0]['Amount'].sum())
        savings = income - expenses
        summary = (
            f"Summary of user's finances:\n"
            f"Total Income: ${income:.2f}\n"
            f"Total Expenses: ${expenses:.2f}\n"
            f"Savings: ${savings:.2f}\n"
            f"Budget: ${budget}\n"
        )
    except Exception:
        summary = f"Budget: ${budget}\n"
    full_prompt = summary + user_message
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY,
    }
    data = {
        "contents": [{"role": "user", "parts": [{"text": full_prompt}]}]
    }
    response = requests.post(GEMINI_API_URL, headers=headers, json=data)
    result = response.json()
    if "candidates" in result and len(result["candidates"]) > 0:
        return result["candidates"][0]["content"]["parts"][0]["text"]
    elif "error" in result:
        return "Gemini API error: " + result["error"].get("message", "Unknown error")
    else:
        return "No response from Gemini API."

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password, password):
            flash('Invalid email or password', 'error')
            return redirect(url_for('login'))
        login_user(user)
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user_exists = User.query.filter_by(email=email).first()
        if user_exists:
            flash('Email address already registered', 'error')
            return redirect(url_for('signup'))
        new_user = User(email=email, password=generate_password_hash(password, method='pbkdf2:sha256'))
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        return redirect(url_for('dashboard'))
    return render_template('signup.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)
        if not file.filename.endswith('.csv'):
            flash("Please upload a CSV file.")
            return redirect(request.url)
        csv_type = request.form.get('csv_type', 'transactions')
        filename = f"{csv_type}_{file.filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        session['filepath'] = filepath
        session['csv_type'] = csv_type
        flash(f"{csv_type.capitalize()} file uploaded successfully!")
        return redirect(url_for('dashboard'))
    return render_template('upload.html')

@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    filepath = session.get('filepath')
    csv_type = session.get('csv_type', 'transactions')
    if not filepath or not os.path.isfile(filepath):
        flash("Please upload a CSV file first.")
        return redirect(url_for('upload'))
    df = pd.read_csv(filepath)
    summary = get_summary(df, csv_type)
    plot = save_plot(df)
    budget = session.get('budget', None)
    budget_message = None
    if request.method == 'POST':
        try:
            budget_input = float(request.form.get('budget'))
            session['budget'] = budget_input
            if 'total_expenses' in summary and summary['total_expenses'] > budget_input:
                budget_message = f"Warning! You exceeded your budget by ${summary['total_expenses'] - budget_input:.2f}."
            else:
                budget_message = f"You are within your budget of ${budget_input}."
        except:
            budget_message = "Invalid budget amount."
    return render_template('dashboard.html', data=df.head().to_html(index=False), summary=summary, plot=plot, budget=budget, budget_message=budget_message)

@app.route('/chat', methods=['GET', 'POST'])
@login_required
def chat():
    filepath = session.get('filepath')
    if not filepath or not os.path.isfile(filepath):
        flash("Please upload a CSV file first.")
        return redirect(url_for('upload'))
    df = pd.read_csv(filepath)
    budget = session.get('budget', 2000)
    chat_response = None
    if request.method == 'POST':
        user_input = request.form.get('user_input', '')
        chat_response = ask_gemini(user_input, budget, df)
    return render_template('chat.html', chat_response=chat_response)

if __name__ == '_main_':
    app.run(host='0.0.0.0', debug=True)