from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_file
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from dotenv import load_dotenv
import click
import os
import json
import shutil
import threading
import time
import base64
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont
from segmentation import PipoPainter  # 작성하신 클래스 임포트
from models import db, User, Design

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL', 'postgresql://pipo_user:pipo_pass@localhost:5432/pipo_db'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# 업로드 요청 자체의 최대 크기를 제한해서, 지나치게 큰 파일이 디스크/메모리를
# 소모하기 전에 요청 단계에서 곧바로 거절한다 (413 Payload Too Large).
app.config['MAX_CONTENT_LENGTH'] = 15 * 1024 * 1024  # 15MB

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
# 워터마크 없는 고화질 원본은 static/ 밖의 비공개 폴더에 저장한다. static/ 밑에
# 두면 Flask의 기본 /static 라우트가 인증 없이 그대로 서빙해버려서 결제 게이팅이
# 무력화되기 때문에, 반드시 이 폴더 밖에서 관리하고 /download/<kind> 라우트를
# 통해서만(결제 확인 후) 내보낸다.
PRIVATE_RESULT_FOLDER = 'private/results'

for folder in [UPLOAD_FOLDER, RESULT_FOLDER, PRIVATE_RESULT_FOLDER]:
    os.makedirs(folder, exist_ok=True)

# 업로드로 허용할 이미지 확장자/컨텐츠 타입 목록 (그 외는 업로드 단계에서 거절).
ALLOWED_UPLOAD_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}
ALLOWED_UPLOAD_MIMETYPES = {'image/jpeg', 'image/png', 'image/webp'}

# process_pipo_task는 원본 크기와 무관하게 항상 가로 1800px로 업스케일한다
# (docs/pricing-tiers.md 4.1절). 원본이 지나치게 작으면(예: 160x120급 초저해상도
# 썸네일) 11배 이상 업스케일해야 하는데, 이 경우 segment.py/render.py를 전혀
# 건드리지 않아도 N_premium(609) < N_standard(650)처럼 등급이 올라가는데
# 최종 영역 수는 오히려 줄어드는 하드 컨스트레인트 1번 위반이 실측으로 확인됐다
# (segmentation/qa_baseline.py, 4.1절 "127_0_0_1.jpg" 참고).
#
# 임계값은 "무조건 400px" 같은 임의값이 아니라 4.1절 실측 표를 근거로 잡았다:
#   - 127_0_0_1.jpg (160x120, 짧은 변 120px) -> 단조 증가 위반(문제 사례)
#   - 122_34_142_96.jpg (301x167, 짧은 변 167px) -> 단조 증가 정상(문제 없음)
# 즉 안전한 하한선은 (120, 167] 구간에 있어야 한다. segmentation/qa_baseline.py로
# 211_36_147_192.jpg/user_5.jpg를 짧은 변 120~400px로 다운스케일해 재측정해봐도
# (양질의 원본을 리사이즈한 경우) 단조 증가가 전 구간에서 유지되는 것으로 볼 때,
# 이 위반은 "해상도 자체"보다 "이미 손실이 큰 초저해상도 원본을 큰 배율로
# 업스케일하는 것"에서 기인하는 것으로 보인다. 순수 해상도만으로는 문제가 되는
# 사례를 재현하기 어렵기 때문에, 알려진 문제 사례(120px)는 반드시 막고 알려진
# 정상 사례(167px)는 절대 막지 않도록 그 사이(150px)에서 여유를 두고 끊는다.
MIN_UPLOAD_SHORT_SIDE_PX = 150

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

# complete/error 상태로 이 시간(초)이 지난 progress_status 항목은 정리 대상이 된다.
# processing 상태인 항목은 아무리 오래돼도 절대 정리하지 않는다(작업 진행 중 상태를
# 잃어버리면 안 되므로).
PROGRESS_ENTRY_TTL_SECONDS = 60 * 60  # 1시간


def _update_progress(prefix, updates):
    """progress_status[prefix]를 갱신한다.

    process_pipo_task 스레드가 이 함수로 상태를 갱신하는 동안, cleanup_progress_status가
    같은 progress_lock을 잡고 만료된 prefix를 삭제할 수 있다. 락 없이 각자
    progress_status[prefix].update(...)를 호출하면, 정리 쪽이 막 그 prefix를 지운
    직후 이 쪽에서 존재하지 않는 키를 갱신하려다 KeyError가 날 수 있다. 그래서
    조회-수정을 항상 같은 락 안에서 원자적으로 처리하고, 혹시 이미 지워진
    경우에도 KeyError 없이 새로 만들어 넣는다.
    """
    with progress_lock:
        entry = progress_status.get(prefix)
        if entry is None:
            entry = {}
            progress_status[prefix] = entry
        entry.update(updates)
        entry["updated_at"] = time.time()


def cleanup_progress_status(now=None):
    """완료/오류 상태로 오래 방치된 progress_status 항목을 정리한다.

    이 딕셔너리는 prefix(비로그인=IP, 로그인=user_id)별로 계속 쌓이기만 하고
    지금까지는 삭제 경로가 없어서, 서버를 오래 띄워둘수록 방문자·회원 수만큼
    메모리를 계속 소모했다. status가 "processing"인 항목은 실제로 작업 중인
    스레드가 참조하고 있으므로 나이와 무관하게 절대 정리하지 않는다.

    process_pipo_task 스레드의 _update_progress 호출과 동일한 progress_lock을
    사용해서, 정리 도중에 삭제한 prefix에 다른 스레드가 update를 시도해
    KeyError가 나는 경쟁을 막는다.
    """
    now = now if now is not None else time.time()
    with progress_lock:
        expired_prefixes = [
            prefix for prefix, entry in progress_status.items()
            if entry.get("status") in ("complete", "error")
            and now - entry.get("updated_at", now) > PROGRESS_ENTRY_TTL_SECONDS
        ]
        for prefix in expired_prefixes:
            del progress_status[prefix]


# 비로그인 사용자(IP)별 결제 완료 여부 -> {prefix: True}
# progress_status와 동일한 패턴의 인메모리 dict. 서버 프로세스가 재시작되면
# 초기화되고, IP를 여러 사람이 공유(NAT)하거나 재접속으로 IP가 바뀌면 실제
# 결제 여부와 어긋날 수 있다는 한계가 있다 — 그래서 로그인 사용자는 아래
# Design.paid 컬럼(DB, 영속화)을 우선 사용하고, 이 dict는 비로그인 사용자를
# 위한 최소한의 보조 수단으로만 쓴다.
paid_status = {}
paid_lock = threading.Lock()

# 다운로드를 허용하는 결과물 종류 (워터마크 없는 원본 파일의 접미사와 일치)
DOWNLOAD_KINDS = ('overlay', 'design', 'preview')


def get_prefix():
    """로그인 사용자는 user_id, 비로그인 사용자는 IP를 파일명 prefix로 사용.
    로그인 사용자는 IP가 바뀌어도 항상 같은 prefix를 쓰게 되어 결과물을 계속 찾을 수 있다."""
    if current_user.is_authenticated:
        return f"user_{current_user.id}"
    ip = request.remote_addr or "unknown"
    return ip.replace('.', '_').replace(':', '_')


def is_paid(prefix):
    """이 prefix(로그인 사용자는 user_id, 비로그인은 IP)가 결제를 완료했는지 확인한다.

    로그인 사용자는 DB(Design.paid, 영속적)를 우선 확인하고, 비로그인 사용자는
    인메모리 paid_status dict(서버 재시작 시 초기화, IP 공유/변경 시 부정확할
    수 있음)를 확인한다."""
    if current_user.is_authenticated:
        design = (Design.query
                  .filter_by(user_id=current_user.id)
                  .order_by(Design.created_at.desc())
                  .first())
        if design is not None and design.paid:
            return True

    with paid_lock:
        return bool(paid_status.get(prefix))


def mark_paid(prefix):
    """결제 승인이 끝난 직후 호출한다. 같은 세션/IP의 get_prefix() 값을 그대로
    받아서 그 prefix를 결제 완료로 표시하고, 로그인 사용자라면 DB의 가장 최근
    Design 레코드에도 paid=True를 영속화한다."""
    with paid_lock:
        paid_status[prefix] = True

    if current_user.is_authenticated:
        design = (Design.query
                  .filter_by(user_id=current_user.id)
                  .order_by(Design.created_at.desc())
                  .first())
        if design is not None:
            design.paid = True
            db.session.commit()


def apply_watermark(src_path, dst_path,
                     text="PIPO PREVIEW · 결제 전 미리보기"):
    """무료 체험/미리보기용으로 옅은 반투명 텍스트를 대각선으로 촘촘히 타일링해
    덮어씌운 사본을 저장한다. 워터마크 없는 원본(src_path)은 건드리지 않는다.
    워터마크 범위는 간단한 반투명 텍스트 오버레이 수준으로 한정한다."""
    base = Image.open(src_path).convert('RGBA')
    w, h = base.size

    # 회전해도 모서리까지 빈틈없이 덮이도록, 대각선 길이만큼 큰 텍스트 레이어를
    # 만들어 촘촘히 텍스트를 채운 다음 회전 후 원본 크기로 가운데를 잘라낸다.
    diag = int((w ** 2 + h ** 2) ** 0.5)
    txt_layer = Image.new('RGBA', (diag, diag), (0, 0, 0, 0))
    draw = ImageDraw.Draw(txt_layer)

    font_size = max(20, w // 20)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size)
    except OSError:
        font = ImageFont.load_default()

    watermark_rgba = (255, 255, 255, 90)  # 옅은 반투명
    step_x = max(140, w // 5)
    step_y = max(100, h // 6)
    for y in range(0, diag, step_y):
        for x in range(0, diag, step_x):
            draw.text((x, y), text, font=font, fill=watermark_rgba)

    txt_layer = txt_layer.rotate(30, resample=Image.BICUBIC)
    left = (diag - w) // 2
    top = (diag - h) // 2
    txt_layer = txt_layer.crop((left, top, left + w, top + h))

    watermarked = Image.alpha_composite(base, txt_layer).convert('RGB')
    watermarked.save(dst_path, quality=90)


def build_palette_info(palette_rgb):
    """painter.palette_rgb(각 팔레트 색상의 RGB 배열)를 프론트에 내려줄 수 있는
    JSON 직렬화 가능한 형태로 변환한다. segmentation/cli.py가 CSV로 뽑는 것과
    동일한 데이터 소스([r, g, b] 순서)를 사용해 결과 화면에도 노출한다."""
    palette = []
    for i, rgb in enumerate(palette_rgb):
        r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
        palette.append({
            "index": i + 1,
            "hex": '#{:02x}{:02x}{:02x}'.format(r, g, b).upper(),
            "r": r, "g": g, "b": b,
        })
    return palette


def palette_json_path(prefix):
    return f"{RESULT_FOLDER}/{prefix}_palette.json"


def load_palette_info(prefix):
    """저장된 팔레트 JSON을 읽어온다. 없거나 손상된 경우 None을 반환한다
    (팔레트 노출은 부가 정보라 실패해도 결과 이미지 표시 자체는 막지 않는다)."""
    path = palette_json_path(prefix)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def process_pipo_task(file_path, prefix, user_id=None, skip_watermark=False):
    """실제 segmentation.py의 기능을 수행하는 쓰레드 함수"""
    try:
        # 0. 초기화
        _update_progress(prefix, {"percent": 5, "message": "AI 모델 초기화 중...", "status": "processing"})
        # 현재는 단일 상품(가격대)만 판매 중이라 "standard" 등급으로 고정한다.
        # 가격대별 상품이 추가되면 여기서 request에서 받은 등급 값을 tier로 넘기면 된다.
        painter = PipoPainter(tier="standard")

        # 1. 사진 로드 및 업사이징 (10%)
        _update_progress(prefix, {"percent": 10, "message": "[1/5] 사진 로드 및 고해상도 변환 중..."})
        img_pil = Image.open(file_path).convert("RGB")
        w, h = img_pil.size
        target_w = 1800
        target_h = int(h * (target_w / w))
        raw_img = np.array(img_pil.resize((target_w, target_h), Image.LANCZOS))

        # 2. 스타일 변환 (30%)
        _update_progress(prefix, {"percent": 30, "message": "[2/5] 유화 스타일 변환 적용 중..."})
        stylized_img = painter.stylize_image(raw_img)

        # 3. 렌더링 (50%)
        _update_progress(prefix, {"percent": 50, "message": "[3/5] 색상 단순화(렌더링) 작업 중..."})
        render_img, _ = painter.process_rendering(stylized_img)

        # 4. 구획 분할 (70%)
        _update_progress(prefix, {"percent": 70, "message": "[4/5] AI 구획 분할 및 경계 계산 중..."})
        final_segments = painter.generate_and_merge_segments(stylized_img)

        # 5. 도안 생성 및 저장 (90%)
        _update_progress(prefix, {"percent": 90, "message": "[5/5] 최종 도안 및 번호 생성 중..."})
        overlay_res, paper_res, rendered_res = painter.refine_layout_and_label(final_segments, stylized_img)

        # 워터마크 없는 고화질 원본은 static/ 밖의 비공개 폴더에 저장한다
        # (결제 확인 전에는 /download/<kind> 라우트에서도 내보내지 않는다).
        private_overlay_path = f"{PRIVATE_RESULT_FOLDER}/{prefix}_overlay.jpg"
        private_design_path = f"{PRIVATE_RESULT_FOLDER}/{prefix}_design.jpg"
        private_preview_path = f"{PRIVATE_RESULT_FOLDER}/{prefix}_preview.jpg"
        Image.fromarray(overlay_res).save(private_overlay_path)
        Image.fromarray(paper_res).save(private_design_path)
        Image.fromarray(rendered_res).save(private_preview_path)

        # 화면에 보여줄 미리보기는 위 원본에 옅은 워터마크를 입힌 사본이다.
        # 사용자별 prefix를 파일명 앞에 붙여 서로 덮어쓰지 않게 함.
        # admin 계정은 결제 여부와 무관하게 워터마크 없는 원본을 그대로 본다.
        overlay_path = f"{RESULT_FOLDER}/{prefix}_overlay.jpg"
        design_path = f"{RESULT_FOLDER}/{prefix}_design.jpg"
        preview_path = f"{RESULT_FOLDER}/{prefix}_preview.jpg"
        if skip_watermark:
            shutil.copy2(private_overlay_path, overlay_path)
            shutil.copy2(private_design_path, design_path)
            shutil.copy2(private_preview_path, preview_path)
        else:
            apply_watermark(private_overlay_path, overlay_path)
            apply_watermark(private_design_path, design_path)
            apply_watermark(private_preview_path, preview_path)

        # 실제 사용된 팔레트(색상 수/스와치)를 함께 저장해서, 결제 전 무료 체험
        # 결과에서도 "몇 가지 물감이 필요한지"를 바로 보여줄 수 있게 한다.
        # segmentation/cli.py가 CSV로 뽑던 것과 동일한 painter.palette_rgb를
        # 그대로 노출만 하는 것이라 세그멘테이션 로직은 건드리지 않는다.
        palette_info = build_palette_info(painter.palette_rgb)
        with open(palette_json_path(prefix), 'w', encoding='utf-8') as f:
            json.dump(palette_info, f, ensure_ascii=False)

        # 완료 (100%)
        _update_progress(prefix, {
            "percent": 100,
            "message": "모든 작업이 완료되었습니다!",
            "status": "complete",
            "result_file": f"{prefix}_preview.jpg", # 결과 파일명 전달
            "palette": palette_info,
            "palette_count": len(palette_info),
        })

        # 로그인한 사용자는 업로드/변환 결과를 DB에도 남겨서, IP가 바뀌어도
        # 로그인만 하면 마지막 결과물을 다시 찾을 수 있게 한다.
        #
        # 주의: overlay_path/design_path/preview_path/file_path는 모두 get_prefix()
        # 기반(예: user_5)의 "사용자당 고정 파일명"이라, 같은 사용자가 다시
        # 업로드하면 다음 번 process_pipo_task가 이 파일들을 그대로 덮어쓴다.
        # progress_status/is_paid/download_result 등 "현재 진행 중이거나 가장
        # 최근 1건"만 다루는 로직은 이 고정 경로를 계속 그대로 써야 하므로 위
        # overlay_path 등 변수는 건드리지 않는다. 대신 이 Design row가 앞으로도
        # 자신만의 실제 이미지를 계속 가리키도록, Design.id를 파일명에 포함한
        # 별도 사본을 만들어 그 경로를 DB 컬럼에 저장한다. 이렇게 하면
        # my_designs()가 여러 row를 보여줄 때 각 row가 실제로 서로 다른(생성
        # 당시의) 이미지를 가리키게 된다.
        if user_id is not None:
            with app.app_context():
                design = Design(
                    user_id=user_id,
                    upload_path=file_path,
                    overlay_path=overlay_path,
                    design_path=design_path,
                    preview_path=preview_path,
                )
                db.session.add(design)
                # Design.id를 알아야 고유 경로를 만들 수 있으므로 우선 커밋한다.
                db.session.commit()

                unique_upload_path = f"{UPLOAD_FOLDER}/user_{user_id}_design_{design.id}.jpg"
                unique_overlay_path = f"{RESULT_FOLDER}/user_{user_id}_design_{design.id}_overlay.jpg"
                unique_design_path = f"{RESULT_FOLDER}/user_{user_id}_design_{design.id}_design.jpg"
                unique_preview_path = f"{RESULT_FOLDER}/user_{user_id}_design_{design.id}_preview.jpg"

                shutil.copy2(file_path, unique_upload_path)
                shutil.copy2(overlay_path, unique_overlay_path)
                shutil.copy2(design_path, unique_design_path)
                shutil.copy2(preview_path, unique_preview_path)

                design.upload_path = unique_upload_path
                design.overlay_path = unique_overlay_path
                design.design_path = unique_design_path
                design.preview_path = unique_preview_path
                db.session.commit()

    except Exception as e:
        print(f"Error: {e}")
        _update_progress(prefix, {"percent": 0, "message": f"오류 발생: {str(e)}", "status": "error"})


@app.route('/')
def index():
    prefix = get_prefix()

    if current_user.is_authenticated:
        # 로그인 사용자는 IP와 무관하게 DB에 남은 마지막 결과물을 보여준다.
        design = (Design.query
                  .filter_by(user_id=current_user.id)
                  .order_by(Design.created_at.desc())
                  .first())
        has_result = design is not None and os.path.exists(design.preview_path)
        initial_preview = os.path.relpath(design.preview_path, 'static') if has_result else None
        initial_upload = (os.path.relpath(design.upload_path, 'static')
                           if has_result and os.path.exists(design.upload_path) else None)
        # 각 Design row가 이제 고유 파일 경로를 가지므로 Design.id를 그대로
        # 캐시 무효화 버전으로 쓸 수 있다(같은 사용자라도 도안이 바뀌면 값이 바뀜).
        preview_version = design.id if has_result else 0
    else:
        preview_name = f"{prefix}_preview.jpg"
        preview_full_path = os.path.join(RESULT_FOLDER, preview_name)
        has_result = os.path.exists(preview_full_path)
        initial_preview = f"results/{preview_name}" if has_result else None
        upload_name = f"{prefix}.jpg"
        initial_upload = (f"uploads/{upload_name}"
                           if has_result and os.path.exists(os.path.join(UPLOAD_FOLDER, upload_name)) else None)
        # 비로그인 사용자는 prefix 기반 고정 파일명을 그대로 쓰므로(무료 체험
        # 1회 제한), 파일 자체의 수정 시각을 캐시 무효화 버전으로 사용해서
        # 브라우저가 예전에 캐시해둔 이미지를 새로고침 후에도 계속 보여주는
        # 일이 없게 한다.
        try:
            preview_version = int(os.path.getmtime(preview_full_path)) if has_result else 0
        except OSError:
            preview_version = 0

    initial_palette = load_palette_info(prefix) if has_result else None

    return render_template(
        'index.html',
        initial_preview=initial_preview,
        initial_upload=initial_upload,
        preview_version=preview_version,
        has_result=has_result,
        initial_palette=initial_palette,
        initial_palette_count=len(initial_palette) if initial_palette else 0,
        toss_client_key=TOSS_CLIENT_KEY,
        product_name=PRODUCT_NAME,
        product_price=PRODUCT_PRICE,
        # 결제가 확인된 사용자에게만 워터마크 없는 원본 다운로드 버튼을 보여준다.
        is_paid=has_result and is_paid(prefix),
    )


@app.route('/my-designs')
@login_required
def my_designs():
    """로그인한 사용자 본인의 도안 생성 이력을 최신순으로 보여준다.

    Design.user_id를 요청 파라미터가 아니라 항상 current_user.id로만 필터링해서,
    다른 사용자의 이력을 조회할 수 없도록 한다. 또한 index()와 동일하게,
    절대 파일시스템 경로를 템플릿에 그대로 넘기지 않고 os.path.relpath(...,
    'static')로 변환한 static/ 기준 상대경로만 넘긴다."""
    designs = (Design.query
               .filter_by(user_id=current_user.id)
               .order_by(Design.created_at.desc())
               .all())

    def to_static_rel(path):
        if not path or not os.path.exists(path):
            return None
        return os.path.relpath(path, 'static')

    design_rows = []
    for d in designs:
        preview_rel = to_static_rel(d.preview_path)
        design_rows.append({
            "id": d.id,
            "created_at": d.created_at,
            "preview_rel": preview_rel,
            "design_rel": to_static_rel(d.design_path),
            "overlay_rel": to_static_rel(d.overlay_path),
        })

    return render_template('my_designs.html', designs=design_rows)


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

    file = request.files['photo']

    # 확장자 검사 (대소문자 무관).
    original_filename = file.filename or ''
    ext = original_filename.rsplit('.', 1)[-1].lower() if '.' in original_filename else ''
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        return jsonify({
            "result": "fail",
            "message": "지원하지 않는 파일 형식입니다. (jpg, jpeg, png, webp만 업로드 가능)"
        }), 400

    # 컨텐츠 타입 검사 (브라우저가 보낸 값이라 완전히 신뢰할 순 없지만, 확장자와
    # 함께 걸러내면 명백히 잘못된 업로드는 대부분 여기서 차단된다).
    if file.mimetype not in ALLOWED_UPLOAD_MIMETYPES:
        return jsonify({
            "result": "fail",
            "message": "지원하지 않는 파일 형식입니다. (jpg, jpeg, png, webp만 업로드 가능)"
        }), 400

    # 실제로 유효한 이미지 파일인지 확인한다 (확장자/컨텐츠 타입만으로는 위조 가능).
    # Image.verify()는 검증 후 파일 핸들을 다시 못 쓰게 만들 수 있으므로, 검증
    # 뒤에는 파일 포인터를 처음으로 되돌려서 이후 저장에 사용할 수 있게 한다.
    try:
        Image.open(file.stream).verify()
    except Exception:
        return jsonify({
            "result": "fail",
            "message": "올바른 이미지 파일이 아닙니다."
        }), 400
    finally:
        file.stream.seek(0)

    prefix = get_prefix()

    # 새 업로드가 들어올 때마다 오래된(complete/error) progress_status 항목을 정리한다.
    # progress_lock을 자체적으로 잡고 반납하므로, 아래 `with progress_lock:` 블록에
    # 들어가기 전에 호출해야 한다(Lock은 재진입 불가라 안에서 부르면 교착 상태에 빠진다).
    cleanup_progress_status()

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

        file_path = os.path.join(UPLOAD_FOLDER, f"{prefix}.jpg")
        file.save(file_path)

        # process_pipo_task는 원본 해상도와 무관하게 항상 가로 1800px로
        # 업스케일한다. 원본이 지나치게 작으면(짧은 변이 MIN_UPLOAD_SHORT_SIDE_PX
        # 미만) 그만큼 업스케일 배율이 커져서, 등급(k_colors)이 올라가도 최종
        # 영역 수가 오히려 줄어드는 등 등급 간 단조 증가가 깨질 수 있다
        # (docs/pricing-tiers.md 4.1절 "127_0_0_1.jpg" 실측 참고). segment.py 등
        # 세그멘테이션 파이프라인 자체를 건드리는 대신, 여기서 입력 단계의
        # 최소 해상도를 강제해서 그 근본 원인(과도한 업스케일)을 차단한다.
        with Image.open(file_path) as saved_img:
            short_side = min(saved_img.size)

        if short_side < MIN_UPLOAD_SHORT_SIDE_PX:
            os.remove(file_path)
            return jsonify({
                "result": "fail",
                "message": "이미지 해상도가 너무 낮습니다. 더 높은 해상도의 사진을 올려주세요."
            }), 400

        progress_status[prefix] = {
            "percent": 0,
            "message": "업로드 완료, 처리 대기 중...",
            "status": "processing",
            "updated_at": time.time(),
        }

        user_id = current_user.id if current_user.is_authenticated else None
        skip_watermark = current_user.is_authenticated and current_user.is_admin

        # 백그라운드 쓰레드 시작
        thread = threading.Thread(
            target=process_pipo_task, args=(file_path, prefix, user_id, skip_watermark)
        )
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
        # 결제 승인이 확정된 시점에, 지금 요청을 보낸 것과 같은 세션/IP의
        # get_prefix() 값을 그대로 사용해서 그 prefix(비로그인=IP,
        # 로그인=user_id)를 결제 완료로 표시한다. 이렇게 하면 /download/<kind>가
        # 이 prefix로 만들어진 결과물을 원본 화질로 내려줄 수 있다.
        prefix = get_prefix()
        mark_paid(prefix)
        return render_template('payment_result.html', success=True, payment=res.json())

    error_body = res.json() if res.content else {}
    return render_template('payment_result.html', success=False,
                            error_message=error_body.get('message', '결제 승인에 실패했습니다.'))


@app.route('/payment/fail')
def payment_fail():
    message = request.args.get('message', '결제가 취소되었거나 실패했습니다.')
    return render_template('payment_result.html', success=False, error_message=message)


@app.route('/download/<kind>')
def download_result(kind):
    """결제 확인 후에만 워터마크 없는 고화질 원본을 내려준다.

    파일은 static/ 밖의 PRIVATE_RESULT_FOLDER에 있어서 /static 라우트로는
    접근할 수 없고, 반드시 이 라우트를 통해서만 결제 여부를 확인한 뒤 서빙된다."""
    if kind not in DOWNLOAD_KINDS:
        return jsonify({"result": "fail", "message": "지원하지 않는 파일 종류입니다."}), 404

    prefix = get_prefix()

    if not is_paid(prefix):
        return jsonify({
            "result": "payment_required",
            "message": "결제 완료 후에 워터마크 없는 원본을 내려받을 수 있습니다."
        }), 402

    private_path = os.path.join(PRIVATE_RESULT_FOLDER, f"{prefix}_{kind}.jpg")
    if not os.path.exists(private_path):
        return jsonify({"result": "fail", "message": "아직 생성된 도안이 없습니다."}), 404

    return send_file(private_path, as_attachment=True,
                      download_name=f"pipo_{kind}.jpg")


@app.errorhandler(413)
def handle_file_too_large(_error):
    # app.config['MAX_CONTENT_LENGTH']를 넘는 요청은 Flask가 기본적으로 HTML
    # 413 응답을 내려주는데, 업로드 JS(templates/index.html)는 fetch 응답을
    # response.json()으로 파싱하므로 다른 실패 응답들과 동일하게 JSON으로 맞춰준다.
    return jsonify({
        "result": "fail",
        "message": "파일 용량이 너무 큽니다. 15MB 이하 이미지로 업로드해주세요."
    }), 413


if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(host='0.0.0.0', debug=debug_mode, port=5000, threaded=True)