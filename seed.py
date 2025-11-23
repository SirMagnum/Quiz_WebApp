# seed.py
# Creates DB tables (if needed) and seeds a teacher account.
# Run with: python seed.py

import os
from app import create_app
from extensions import db
from models import User, Role

# If you want to force recreate DB file during dev, set RECREATE_DB = True
RECREATE_DB = False   # set True if you want to remove existing sqlite file

# Path inferred from SQLALCHEMY_DATABASE_URI in config.py when using sqlite:///filename
SQLITE_FILENAME = "quizapp.db"

app = create_app()

with app.app_context():
    # Optional: remove sqlite file (dev convenience)
    if RECREATE_DB and os.path.exists(SQLITE_FILENAME):
        try:
            os.remove(SQLITE_FILENAME)
            print(f"Removed existing DB file: {SQLITE_FILENAME}")
        except Exception as e:
            print("Could not remove DB file:", e)

    # Ensure tables exist
    db.create_all()

    # Remove any pre-existing teacher user so seeding is deterministic
    existing = User.query.filter_by(username="teacher").first()
    if existing:
        # delete the old one
        User.query.filter_by(username="teacher").delete()
        db.session.commit()
        print("Deleted existing 'teacher' user to avoid conflicts.")

    # Create fresh teacher user
    teacher = User(username="teacher", role=Role.TEACHER)
    teacher.set_password("teachpass")
    db.session.add(teacher)

    # Optional: create a sample student
    # student = User(username="student1", role=Role.STUDENT)
    # student.set_password("pass123")
    # db.session.add(student)

    db.session.commit()

    print("✅ Seed complete.")
    print("Teacher credentials -> username: teacher   password: teachpass")
    # print("Sample student -> username: student1   password: pass123")
