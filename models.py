from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False, server_default='false')
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Design(db.Model):
    __tablename__ = 'designs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    upload_path = db.Column(db.String(255), nullable=False)
    overlay_path = db.Column(db.String(255))
    design_path = db.Column(db.String(255))
    preview_path = db.Column(db.String(255))
    # 결제 확인(payment/success)이 이 사용자의 가장 최근 도안에 대해 완료됐는지
    # 여부. 워터마크 없는 원본 다운로드(/download/<kind>) 게이팅에 사용한다.
    # NOTE: create_all()은 이미 존재하는 테이블에 새 컬럼을 추가해주지 않으므로,
    # 기존 DB에 이 컬럼을 반영하려면 수동 마이그레이션(ALTER TABLE)이나
    # Flask-Migrate 도입이 필요하다. 다음 사이클 개선 과제로 남겨둔다.
    paid = db.Column(db.Boolean, default=False, nullable=False, server_default='false')
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    user = db.relationship('User', backref=db.backref('designs', lazy=True))
