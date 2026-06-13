from flask import Flask, render_template, request, jsonify
import os
import time
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

progress_status = {"percent": 0, "message": "대기 중...", "status": "idle"}

def process_pipo_task(file_path):
    """실제 segmentation.py의 기능을 수행하는 쓰레드 함수"""
    global progress_status
    try:
        # 0. 초기화
        progress_status.update({"percent": 5, "message": "AI 모델 초기화 중...", "status": "processing"})
        painter = PipoPainter(k_colors=32, n_segments=3000)
        
        # 1. 사진 로드 및 업사이징 (10%)
        progress_status.update({"percent": 10, "message": "[1/5] 사진 로드 및 고해상도 변환 중..."})
        img_pil = Image.open(file_path).convert("RGB")
        w, h = img_pil.size
        target_w = 1800 
        target_h = int(h * (target_w / w))
        raw_img = np.array(img_pil.resize((target_w, target_h), Image.LANCZOS))
        
        # 2. 스타일 변환 (30%)
        progress_status.update({"percent": 30, "message": "[2/5] 유화 스타일 변환 적용 중..."})
        stylized_img = painter.stylize_image(raw_img)
        
        # 3. 렌더링 (50%)
        progress_status.update({"percent": 50, "message": "[3/5] 색상 단순화(렌더링) 작업 중..."})
        render_img, _ = painter.process_rendering(stylized_img)
        
        # 4. 구획 분할 (70%)
        progress_status.update({"percent": 70, "message": "[4/5] AI 구획 분할 및 경계 계산 중..."})
        final_segments = painter.generate_and_merge_segments(stylized_img)
        
        # 5. 도안 생성 및 저장 (90%)
        progress_status.update({"percent": 90, "message": "[5/5] 최종 도안 및 번호 생성 중..."})
        overlay_res, paper_res, rendered_res = painter.refine_layout_and_label(final_segments, stylized_img)
        
        # 파일명 추출 (확장자 제외)
        filename = os.path.basename(file_path).split('.')[0]
        
        # 결과물 저장
        Image.fromarray(overlay_res).save(f"{RESULT_FOLDER}/{filename}_overlay.jpg")
        Image.fromarray(paper_res).save(f"{RESULT_FOLDER}/{filename}_design.jpg")
        Image.fromarray(rendered_res).save(f"{RESULT_FOLDER}/{filename}_preview.jpg")

        # 완료 (100%)
        progress_status.update({
            "percent": 100, 
            "message": "모든 작업이 완료되었습니다!", 
            "status": "complete",
            "result_file": f"{filename}_preview.jpg" # 결과 파일명 전달
        })
        
    except Exception as e:
        print(f"Error: {e}")
        progress_status.update({"percent": 0, "message": f"오류 발생: {str(e)}", "status": "error"})

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'photo' not in request.files:
        return jsonify({"result": "fail"}), 400
    
    file = request.files['photo']
    file_path = os.path.join(UPLOAD_FOLDER, "test.jpg")
    file.save(file_path)

    # 백그라운드 쓰레드 시작
    thread = threading.Thread(target=process_pipo_task, args=(file_path,))
    thread.start()
    
    return jsonify({"result": "started"})

@app.route('/progress')
def get_progress():
    return jsonify(progress_status)

if __name__ == '__main__':
    app.run(debug=True, port=5000)