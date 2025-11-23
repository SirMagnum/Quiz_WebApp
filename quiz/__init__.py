from flask import Blueprint
quiz_bp = Blueprint("quiz", __name__)
from . import routes
