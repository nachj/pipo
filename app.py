from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from dotenv import load_dotenv
import click
import os
import threading
import base64
import numpy as np
import requests
from PIL import Image
from segmentation import PipoPainter  # 작성하신 클래스 임포트
from models import db, User, Design

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL', 'postgresql://pipo_user:pipo_pass@localhost:5432/pipo_db'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = '로그인이 필요한 페이지입니다.'


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


with app.app_context():
    db.create_all()


@app.cli.command('create-admin')
@click.option('--email', prompt=True)
@click.option('--name', prompt=True)
@click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True)
def create_admin(email, name, password):
    """관리자 계정을 생성하거나, 이미 있는 계정이면 관리자로 승격합니다."""
    email = email.strip().lower()
    user = User.query.filter_by(email=email).first()
    if user:
        user.is_admin = True
        db.session.commit()
        click.echo(f'{email} 계정을 관리자로 승격했습니다.')
        return

    user = User(email=email, name=name, is_admin=True)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    click.echo(f'관리자 계정 {email} 을 생성했습니다.')


UPLOAD_FOLDER = 'static/uploads'
RESULT_FOLDER = 'static/results'

for folder in [UPLOAD_FOLDER, RESULT_FOLDER]:
    os.makedirs(folder, exist_ok=True)

# 토스페이먼츠 결제위젯 연동 (https://docs.tosspayments.com)
# 아래 키는 토스페이먼츠가 공개적으로 배포하는 "가입 전 테스트용" 키 쌍이라
# 회원가입 없이 바로 결제 흐름을 테스트할 수 있다. 실서비스 전환 시에는 반드시
# 토스페이먼츠 대시보드에서 발급받은 라이브 키를 환경변수로 주입해서 교체해야 한다.
TOSS_CLIENT_KEY = os.environ.get('TOSS_CLIENT_KEY', 'test_ck_D5GePWvyJnrK0W0k6q8gLzN97Eoq')
TOSS_SECRET_KEY = os.environ.get('TOSS_SECRET_KEY', 'test_sk_zXLkKEypNArWmo50nX3lmeaxYG5R')
TOSS_CONFIRM_URL = 'https://api.tosspayments.com/v1/payments/confirm'

PRODUCT_NAME = '피포페인팅 나만의 도안 제작'
# 결제 금액은 클라이언트가 보낸 값을 그대로 믿지 않고 서버가 알고 있는 이 값과
# 대조해서 검증한다 (금액 조작 방지 — 토스페이먼츠 공식 가이드 권고 사항).
PRODUCT_PRICE = 15000

# 사용자(IP)별 진행 상태를 따로 관리 -> {prefix: {"percent": ..., "message": ..., "status": ...}}
progress_status = {}
progress_lock = threading.Lock()


def get_prefix():
    """로그인 사용자는 user_id, 비로그인 사용자는 IP를 파일명 prefix로 사용.
    로그인 사용자는 IP가 바뀌어도 항상 같은 prefix를 쓰게 되어 결과물을 계속 찾을 수 있다."""
    if current_user.is_authenticated:
        return f"user_{current_user.id}"
    ip = request.remote_addr or "unknown"
    return ip.replace('.', '_').replace(':', '_')


def process_pipo_task(file_path, prefix, user_id=None):
    """실제 segmentation.py의 기능을 수행하는 쓰레드 함수"""
    try:
        # 0. 초기화
        progress_status[prefix].update({"percent": 5, "message": "AI 모델 초기화 중...", "status": "processing"})
        painter = PipoPainter(k_colors=24, n_segments=3000)

        # 1. 사진 로드 및 업사이징 (10%)
        progress_status[prefix].update({"percent": 10, "message": "[1/5] 사진 로드 및 고해상도 변환 중..."})
        img_pil = Image.open(file_path).convert("RGB")
        w, h = img_pil.size
        target_w = 1800
        target_h = int(h * (target_w / w))
        raw_img = np.array(img_pil.resize((target_w, target_h), Image.LANCZOS))

        # 2. 스타일 변환 (30%)
        progress_status[prefix].update({"percent": 30, "message": "[2/5] 유화 스타일 변환 적용 중..."})
        stylized_img = painter.stylize_image(raw_img)

        # 3. 렌더링 (50%)
        progress_status[prefix].update({"percent": 50, "message": "[3/5] 색상 단순화(렌더링) 작업 중..."})
        render_img, _ = painter.process_rendering(stylized_img)

        # 4. 구획 분할 (70%)
        progress_status[prefix].update({"percent": 70, "message": "[4/5] AI 구획 분할 및 경계 계산 중..."})
        final_segments = painter.generate_and_merge_segments(stylized_img)

        # 5. 도안 생성 및 저장 (90%)
        progress_status[prefix].update({"percent": 90, "message": "[5/5] 최종 도안 및 번호 생성 중..."})
        overlay_res, paper_res, rendered_res = painter.refine_layout_and_label(final_segments, stylized_img)

        # 결과물 저장 (사용자별 prefix를 파일명 앞에 붙여 서로 덮어쓰지 않게 함)
        overlay_path = f"{RESULT_FOLDER}/{prefix}_overlay.jpg"
        design_path = f"{RESULT_FOLDER}/{prefix}_design.jpg"
        preview_path = f"{RESULT_FOLDER}/{prefix}_preview.jpg"
        Image.fromarray(overlay_res).save(overlay_path)
        Image.fromarray(paper_res).save(design_path)
        Image.fromarray(rendered_res).save(preview_path)

        # 완료 (100%)
        progress_status[prefix].update({
            "percent": 100,
            "message": "모든 작업이 완료되었습니다!",
            "status": "complete",
            "result_file": f"{prefix}_preview.jpg" # 결과 파일명 전달
        })

        # 로그인한 사용자는 업로드/변환 결과를 DB에도 남겨서, IP가 바뀌어도
        # 로그인만 하면 마지막 결과물을 다시 찾을 수 있게 한다.
        if user_id is not None:
            with app.app_context():
                db.session.add(Design(
                    user_id=user_id,
                    upload_path=file_path,
                    overlay_path=overlay_path,
                    design_path=design_path,
                    preview_path=preview_path,
                ))
                db.session.commit()

    except Exception as e:
        print(f"Error: {e}")
        progress_status[prefix].update({"percent": 0, "message": f"오류 발생: {str(e)}", "status": "error"})


@app.route('/')
def index():
    if current_user.is_authenticated:
        # 로그인 사용자는 IP와 무관하게 DB에 남은 마지막 결과물을 보여준다.
        design = (Design.query
                  .filter_by(user_id=current_user.id)
                  .order_by(Design.created_at.desc())
                  .first())
        has_result = design is not None and os.path.exists(design.preview_path)
        initial_preview = os.path.relpath(design.preview_path, 'static') if has_result else None
    else:
        prefix = get_prefix()
        preview_name = f"{prefix}_preview.jpg"
        has_result = os.path.exists(os.path.join(RESULT_FOLDER, preview_name))
        initial_preview = f"results/{preview_name}" if has_result else None

    return render_template(
        'index.html',
        initial_preview=initial_preview,
        has_result=has_result,
        toss_client_key=TOSS_CLIENT_KEY,
        product_name=PRODUCT_NAME,
        product_price=PRODUCT_PRICE,
    )


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        name = request.form.get('name', '').strip()
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')

        if not email or not name or not password:
            flash('모든 항목을 입력해주세요.', 'error')
            return render_template('signup.html', email=email, name=name)

        if password != password_confirm:
            flash('비밀번호가 일치하지 않습니다.', 'error')
            return render_template('signup.html', email=email, name=name)

        if len(password) < 8:
            flash('비밀번호는 8자 이상이어야 합니다.', 'error')
            return render_template('signup.html', email=email, name=name)

        if User.query.filter_by(email=email).first():
            flash('이미 가입된 이메일입니다.', 'error')
            return render_template('signup.html', email=email, name=name)

        user = User(email=email, name=name)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        login_user(user)
        flash('회원가입이 완료되었습니다.', 'success')
        return redirect(url_for('index'))

    return render_template('signup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))

        flash('이메일 또는 비밀번호가 올바르지 않습니다.', 'error')
        return render_template('login.html', email=email)

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/upload', methods=['POST'])
def upload_file():
    if 'photo' not in request.files or not request.files['photo'].filename:
        return jsonify({"result": "fail", "message": "파일이 선택되지 않았습니다."}), 400

    prefix = get_prefix()

    with progress_lock:
        # 같은 사용자가 이미 처리 중이면 상태/파일이 뒤섞이므로 거절 (다른 사용자는 서로 영향 없음)
        current = progress_status.get(prefix)
        if current and current.get("status") == "processing":
            return jsonify({"result": "fail", "message": "이전 도안을 생성하는 중입니다. 완료 후 다시 시도해주세요."}), 409

        # 비로그인 사용자는 무료 체험 1회만 허용. 이미 결과물이 있는 IP가 다시
        # 업로드하려 하면 처리하지 않고 로그인을 유도한다.
        if not current_user.is_authenticated:
            preview_name = f"{prefix}_preview.jpg"
            if os.path.exists(os.path.join(RESULT_FOLDER, preview_name)):
                return jsonify({
                    "result": "login_required",
                    "message": "무료 체험은 1회만 가능합니다. 로그인하면 계속 이용하실 수 있어요."
                }), 403

        file = request.files['photo']
        file_path = os.path.join(UPLOAD_FOLDER, f"{prefix}.jpg")
        file.save(file_path)

        progress_status[prefix] = {"percent": 0, "message": "업로드 완료, 처리 대기 중...", "status": "processing"}

        user_id = current_user.id if current_user.is_authenticated else None

        # 백그라운드 쓰레드 시작
        thread = threading.Thread(target=process_pipo_task, args=(file_path, prefix, user_id))
        thread.start()

    return jsonify({"result": "started"})


@app.route('/progress')
def get_progress():
    prefix = get_prefix()
    return jsonify(progress_status.get(prefix, {"percent": 0, "message": "대기 중...", "status": "idle"}))


@app.route('/payment/success')
def payment_success():
    payment_key = request.args.get('paymentKey')
    order_id = request.args.get('orderId')
    amount = request.args.get('amount')

    if not payment_key or not order_id or not amount:
        return render_template('payment_result.html', success=False,
                                error_message='잘못된 결제 응답입니다.')

    # 클라이언트가 위젯에 넘긴 금액을 그대로 신뢰하지 않고, 서버가 알고 있는
    # 실제 상품 가격과 대조해서 금액이 조작되지 않았는지 확인한다.
    try:
        amount_int = int(amount)
    except ValueError:
        amount_int = None

    if amount_int != PRODUCT_PRICE:
        return render_template('payment_result.html', success=False,
                                error_message='결제 금액이 올바르지 않습니다.')

    auth_header = 'Basic ' + base64.b64encode(f'{TOSS_SECRET_KEY}:'.encode()).decode()

    try:
        res = requests.post(
            TOSS_CONFIRM_URL,
            headers={'Authorization': auth_header, 'Content-Type': 'application/json'},
            json={'paymentKey': payment_key, 'orderId': order_id, 'amount': amount_int},
            timeout=10,
        )
    except requests.RequestException:
        return render_template('payment_result.html', success=False,
                                error_message='결제 승인 서버에 연결할 수 없습니다.')

    if res.status_code == 200:
        return render_template('payment_result.html', success=True, payment=res.json())

    error_body = res.json() if res.content else {}
    return render_template('payment_result.html', success=False,
                            error_message=error_body.get('message', '결제 승인에 실패했습니다.'))


@app.route('/payment/fail')
def payment_fail():
    message = request.args.get('message', '결제가 취소되었거나 실패했습니다.')
    return render_template('payment_result.html', success=False, error_message=message)


if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5000, threaded=True)