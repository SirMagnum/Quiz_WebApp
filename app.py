from flask import Flask
from config import Config
from extensions import db, login_manager
from auth.routes import auth_bp
from teacher.routes import teacher_bp
from quiz.routes import quiz_bp

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    login_manager.init_app(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(teacher_bp, url_prefix="/teacher")
    app.register_blueprint(quiz_bp, url_prefix="/quiz")

    with app.app_context():
        db.create_all()

    return app

if __name__ == "__main__":
    create_app().run(debug=True)
