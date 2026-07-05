from flask import Flask, render_template, request, jsonify
import os
import threading
import numpy as np
from PIL import Image
import shutil
from segmentation import PipoPainter  # 작성하신 클래스 임포트

app = Flask(__name__)

UPLOAD_FOLDER = 'static/uploads'
RESULT_FOLDER = 'static/results'

for folder in [UPLOAD_FOLDER, RESULT_FOLDER]:
    if os.path.exists(folder):
        # 폴더가 존재하면 내부 파일까지 모두 삭제
        shutil.rmtree(folder)
    
    # 다시 깨끗한 상태로 생성
    os.makedirs(folder)

# 사용자(IP)별 진행 상태를 따로 관리 -> {prefix: {"percent": ..., "message": ..., "status": ...}}
progress_status = {}
progress_lock = threading.Lock()


def get_prefix():
    """요청자의 IP를 파일명으로 쓸 수 있게 정리해서 prefix로 사용"""
    ip = request.remote_addr or "unknown"
    return ip.replace('.', '_').replace(':', '_')


def process_pipo_task(file_path, prefix):
    """실제 segmentation.py의 기능을 수행하는 쓰레드 함수"""
    try:
        # 0. 초기화
        progress_status[prefix].update({"percent": 5, "message": "AI 모델 초기화 중...", "status": "processing"})
        painter = PipoPainter(k_colors=32, n_segments=3000)

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
        Image.fromarray(overlay_res).save(f"{RESULT_FOLDER}/{prefix}_overlay.jpg")
        Image.fromarray(paper_res).save(f"{RESULT_FOLDER}/{prefix}_design.jpg")
        Image.fromarray(rendered_res).save(f"{RESULT_FOLDER}/{prefix}_preview.jpg")

        # 완료 (100%)
        progress_status[prefix].update({
            "percent": 100,
            "message": "모든 작업이 완료되었습니다!",
            "status": "complete",
            "result_file": f"{prefix}_preview.jpg" # 결과 파일명 전달
        })

    except Exception as e:
        print(f"Error: {e}")
        progress_status[prefix].update({"percent": 0, "message": f"오류 발생: {str(e)}", "status": "error"})


@app.route('/')
def index():
    prefix = get_prefix()
    return render_template('index.html', initial_preview=f"results/{prefix}_preview.jpg")


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

        file = request.files['photo']
        file_path = os.path.join(UPLOAD_FOLDER, f"{prefix}.jpg")
        file.save(file_path)

        progress_status[prefix] = {"percent": 0, "message": "업로드 완료, 처리 대기 중...", "status": "processing"}

        # 백그라운드 쓰레드 시작
        thread = threading.Thread(target=process_pipo_task, args=(file_path, prefix))
        thread.start()

    return jsonify({"result": "started"})


@app.route('/progress')
def get_progress():
    prefix = get_prefix()
    return jsonify(progress_status.get(prefix, {"percent": 0, "message": "대기 중...", "status": "idle"}))


if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5000, threaded=True)