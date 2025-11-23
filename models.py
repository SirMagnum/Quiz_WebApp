# models.py
from extensions import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import enum
import json

class Role(enum.Enum):
    STUDENT = "student"
    TEACHER = "teacher"

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.Enum(Role), default=Role.STUDENT)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    prompt = db.Column(db.Text, nullable=False)
    options_json = db.Column(db.Text, nullable=False)
    correct_answers = db.Column(db.String(200), nullable=False)
    difficulty = db.Column(db.Integer, default=3)
    qtype = db.Column(db.String(50), default="single")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Attempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    mode = db.Column(db.String(50), nullable=False)
    score = db.Column(db.Integer, default=0)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    ended_at = db.Column(db.DateTime)
    details = db.Column(db.Text)  # JSON encoded list of per-question events

    def add_event(self, event: dict):
        # event example: {"qid":1,"correct":True,"time_used":7,"selected":["1"],"difficulty":3}
        dd = []
        if self.details:
            try:
                dd = json.loads(self.details)
            except Exception:
                dd = []
        dd.append(event)
        self.details = json.dumps(dd, ensure_ascii=False)

# flask-login user_loader
@login_manager.user_loader
def load_user(user_id):
    try:
        return User.query.get(int(user_id))
    except Exception:
        return None
