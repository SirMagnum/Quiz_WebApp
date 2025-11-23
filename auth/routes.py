from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from models import User, Role
from extensions import db

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/")
def index():
    return redirect(url_for("auth.login"))

@auth_bp.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        pw = request.form["password"]

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(pw):
            login_user(user)
            if user.role == Role.TEACHER:
                return redirect(url_for("teacher.dashboard"))
            return redirect(url_for("quiz.start"))
        flash("Invalid credentials", "danger")

    return render_template("login.html")

@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
