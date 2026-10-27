# -*- coding: utf-8 -*-
"""
Система учёта техники
ПОЧУ ИТ ЭУП УПС
Простое приложение на Flask
"""

from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret_key_tech_uchet_2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tech_uchet.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


# ==================== МОДЕЛИ ====================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='user')  # admin или user
    full_name = db.Column(db.String(150))
    cabinet = db.Column(db.String(50))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Equipment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    inv_number = db.Column(db.String(50), unique=True, nullable=False)
    category = db.Column(db.String(100))  # компьютер, принтер, и т.д.
    cabinet = db.Column(db.String(50))
    responsible = db.Column(db.String(150))
    status = db.Column(db.String(50), default='в эксплуатации')  # в эксплуатации, на ремонте, списана
    purchase_date = db.Column(db.Date)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)

    repair_requests = db.relationship('RepairRequest', backref='equipment', lazy=True)


class RepairRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), default='новая')  # новая, в работе, выполнена, отклонена
    created_at = db.Column(db.DateTime, default=datetime.now)
    completed_at = db.Column(db.DateTime)
    admin_comment = db.Column(db.Text)

    user = db.relationship('User', backref='repair_requests')


class WriteOff(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey('equipment.id'), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    act_number = db.Column(db.String(50))
    date = db.Column(db.DateTime, default=datetime.now)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))

    equipment = db.relationship('Equipment', backref='writeoffs')


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Нужно войти в систему', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Нужно войти в систему', 'warning')
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or user.role != 'admin':
            flash('Доступ только для администратора', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated


def get_current_user():
    if 'user_id' in session:
        return User.query.get(session['user_id'])
    return None


# ==================== МАРШРУТЫ ====================

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = get_current_user()
    total_eq = Equipment.query.count()
    in_use = Equipment.query.filter_by(status='в эксплуатации').count()
    in_repair = Equipment.query.filter_by(status='на ремонте').count()
    written_off = Equipment.query.filter_by(status='списана').count()
    open_requests = RepairRequest.query.filter(RepairRequest.status.in_(['новая', 'в работе'])).count()
    return render_template('index.html', user=user, total_eq=total_eq,
                           in_use=in_use, in_repair=in_repair,
                           written_off=written_off, open_requests=open_requests)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['role'] = user.role
            flash(f'Добро пожаловать, {user.full_name or user.username}!', 'success')
            return redirect(url_for('index'))
        flash('Неверный логин или пароль', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('login'))


# ---------- Техника ----------

@app.route('/equipment')
@login_required
def equipment_list():
    user = get_current_user()
    status_filter = request.args.get('status', '')
    search = request.args.get('search', '').strip()
    query = Equipment.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    if search:
        query = query.filter(
            db.or_(
                Equipment.name.ilike(f'%{search}%'),
                Equipment.inv_number.ilike(f'%{search}%'),
                Equipment.cabinet.ilike(f'%{search}%')
            )
        )
    items = query.order_by(Equipment.inv_number).all()
    return render_template('equipment_list.html', user=user, items=items,
                           status_filter=status_filter, search=search)


@app.route('/equipment/add', methods=['GET', 'POST'])
@admin_required
def equipment_add():
    user = get_current_user()
    if request.method == 'POST':
        inv = request.form.get('inv_number', '').strip()
        if Equipment.query.filter_by(inv_number=inv).first():
            flash('Техника с таким инвентарным номером уже есть', 'danger')
            return redirect(url_for('equipment_add'))
        eq = Equipment(
            name=request.form.get('name', '').strip(),
            inv_number=inv,
            category=request.form.get('category', '').strip(),
            cabinet=request.form.get('cabinet', '').strip(),
            responsible=request.form.get('responsible', '').strip(),
            status='в эксплуатации',
            notes=request.form.get('notes', '').strip()
        )
        date_str = request.form.get('purchase_date', '')
        if date_str:
            try:
                eq.purchase_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except:
                pass
        db.session.add(eq)
        db.session.commit()
        flash('Техника добавлена', 'success')
        return redirect(url_for('equipment_list'))
    return render_template('equipment_form.html', user=user, item=None)


@app.route('/equipment/<int:eq_id>/edit', methods=['GET', 'POST'])
@admin_required
def equipment_edit(eq_id):
    user = get_current_user()
    eq = Equipment.query.get_or_404(eq_id)
    if request.method == 'POST':
        eq.name = request.form.get('name', '').strip()
        eq.category = request.form.get('category', '').strip()
        eq.cabinet = request.form.get('cabinet', '').strip()
        eq.responsible = request.form.get('responsible', '').strip()
        eq.status = request.form.get('status', 'в эксплуатации')
        eq.notes = request.form.get('notes', '').strip()
        date_str = request.form.get('purchase_date', '')
        if date_str:
            try:
                eq.purchase_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except:
                pass
        db.session.commit()
        flash('Данные обновлены', 'success')
        return redirect(url_for('equipment_list'))
    return render_template('equipment_form.html', user=user, item=eq)


@app.route('/equipment/<int:eq_id>')
@login_required
def equipment_view(eq_id):
    user = get_current_user()
    eq = Equipment.query.get_or_404(eq_id)
    requests_list = RepairRequest.query.filter_by(equipment_id=eq_id).order_by(RepairRequest.created_at.desc()).all()
    return render_template('equipment_view.html', user=user, item=eq, requests=requests_list)


# ---------- Заявки на ремонт ----------

@app.route('/repairs')
@login_required
def repairs_list():
    user = get_current_user()
    if user.role == 'admin':
        items = RepairRequest.query.order_by(RepairRequest.created_at.desc()).all()
    else:
        items = RepairRequest.query.filter_by(user_id=user.id).order_by(RepairRequest.created_at.desc()).all()
    return render_template('repairs_list.html', user=user, items=items)


@app.route('/repairs/new', methods=['GET', 'POST'])
@login_required
def repair_new():
    user = get_current_user()
    equipment_list = Equipment.query.filter(Equipment.status != 'списана').order_by(Equipment.inv_number).all()
    if request.method == 'POST':
        eq_id = request.form.get('equipment_id')
        desc = request.form.get('description', '').strip()
        if not eq_id or not desc:
            flash('Заполните все поля', 'warning')
            return redirect(url_for('repair_new'))
        req = RepairRequest(
            equipment_id=int(eq_id),
            user_id=user.id,
            description=desc,
            status='новая'
        )
        # меняем статус техники
        eq = Equipment.query.get(int(eq_id))
        if eq:
            eq.status = 'на ремонте'
        db.session.add(req)
        db.session.commit()
        flash('Заявка на ремонт создана', 'success')
        return redirect(url_for('repairs_list'))
    return render_template('repair_form.html', user=user, equipment_list=equipment_list)


@app.route('/repairs/<int:req_id>/update', methods=['POST'])
@admin_required
def repair_update(req_id):
    req = RepairRequest.query.get_or_404(req_id)
    new_status = request.form.get('status')
    comment = request.form.get('admin_comment', '').strip()
    if new_status in ['новая', 'в работе', 'выполнена', 'отклонена']:
        req.status = new_status
        req.admin_comment = comment
        if new_status == 'выполнена':
            req.completed_at = datetime.now()
            # возвращаем технику в эксплуатацию
            if req.equipment:
                req.equipment.status = 'в эксплуатации'
        elif new_status == 'отклонена':
            if req.equipment:
                req.equipment.status = 'в эксплуатации'
        db.session.commit()
        flash('Статус заявки обновлён', 'success')
    return redirect(url_for('repairs_list'))


# ---------- Списание ----------

@app.route('/writeoffs')
@login_required
def writeoffs_list():
    user = get_current_user()
    items = WriteOff.query.order_by(WriteOff.date.desc()).all()
    return render_template('writeoffs_list.html', user=user, items=items)


@app.route('/writeoffs/new', methods=['GET', 'POST'])
@admin_required
def writeoff_new():
    user = get_current_user()
    equipment_list = Equipment.query.filter(Equipment.status != 'списана').order_by(Equipment.inv_number).all()
    if request.method == 'POST':
        eq_id = request.form.get('equipment_id')
        reason = request.form.get('reason', '').strip()
        act = request.form.get('act_number', '').strip()
        if not eq_id or not reason:
            flash('Заполните обязательные поля', 'warning')
            return redirect(url_for('writeoff_new'))
        wo = WriteOff(
            equipment_id=int(eq_id),
            reason=reason,
            act_number=act,
            created_by=user.id
        )
        eq = Equipment.query.get(int(eq_id))
        if eq:
            eq.status = 'списана'
        db.session.add(wo)
        db.session.commit()
        flash('Техника списана', 'success')
        return redirect(url_for('writeoffs_list'))
    return render_template('writeoff_form.html', user=user, equipment_list=equipment_list)


# ---------- Инвентаризация (простой список) ----------

@app.route('/inventory')
@login_required
def inventory():
    user = get_current_user()
    items = Equipment.query.filter(Equipment.status != 'списана').order_by(Equipment.cabinet, Equipment.inv_number).all()
    return render_template('inventory.html', user=user, items=items)


# ==================== ИНИЦИАЛИЗАЦИЯ БД ====================

def init_db():
    with app.app_context():
        db.create_all()
        # создаём админа если нет
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', role='admin', full_name='Администратор системы')
            admin.set_password('admin')
            db.session.add(admin)
        if not User.query.filter_by(username='user').first():
            u = User(username='user', role='user', full_name='Иванов И.И.', cabinet='301')
            u.set_password('user')
            db.session.add(u)
        # немного тестовой техники
        if Equipment.query.count() == 0:
            demo = [
                Equipment(name='Компьютер системный блок', inv_number='ИНВ-001', category='Компьютер',
                          cabinet='301', responsible='Иванов И.И.', status='в эксплуатации'),
                Equipment(name='Монитор Samsung 24"', inv_number='ИНВ-002', category='Монитор',
                          cabinet='301', responsible='Иванов И.И.', status='в эксплуатации'),
                Equipment(name='Принтер HP LaserJet', inv_number='ИНВ-003', category='Принтер',
                          cabinet='215', responsible='Петрова А.С.', status='в эксплуатации'),
                Equipment(name='Ноутбук Lenovo', inv_number='ИНВ-004', category='Ноутбук',
                          cabinet='410', responsible='Сидоров П.В.', status='в эксплуатации'),
                Equipment(name='Проектор Epson', inv_number='ИНВ-005', category='Проектор',
                          cabinet='Актовый зал', responsible='Кузнецова М.А.', status='в эксплуатации'),
            ]
            for e in demo:
                db.session.add(e)
        db.session.commit()
        print('База данных готова')


if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
