from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
import numpy as np
import cv2
import os
import shutil
from collections import Counter
import uuid
import re  # [新增] 引入正規表達式套件

# ==========================================
# 核心演算法: Robust DCT + Regex Filter
# ==========================================
class DctRobustWatermark:
    def __init__(self, alpha=40.0):
        self.block_size = 8
        # 使用低頻係數 (2,1) (1,2) 抵抗壓縮
        self.pos1 = (2, 1)
        self.pos2 = (1, 2)
        self.alpha = alpha
        
        self.header = "MyWM:"   
        self.footer = ":::EOF"  

    def text_to_bits(self, text):
        # 寫入格式：Header + 內容 + Footer
        full_text = self.header + text + self.footer
        bits = []
        for char in full_text:
            bin_val = bin(ord(char))[2:].rjust(8, '0')
            bits.extend([int(b) for b in bin_val])
        # 補零緩衝
        bits.extend([0] * 32)
        return bits

    def bits_to_text_stream(self, bits):
        chars = []
        for i in range(0, len(bits), 8):
            byte = bits[i:i+8]
            if len(byte) < 8: break
            byte_str = ''.join(str(b) for b in byte)
            try:
                char_code = int(byte_str, 2)
                # 寬鬆過濾：只允許 ASCII 可見字元
                if 32 <= char_code <= 126: chars.append(chr(char_code))
                else: chars.append('') # 亂碼直接丟棄，不留痕跡
            except: pass
        return ''.join(chars)

    def embed_frame(self, img, secret_text):
        if img is None: return None
        h, w = img.shape[:2]
        h_safe, w_safe = (h // 8) * 8, (w // 8) * 8
        img_use = img[:h_safe, :w_safe]
        
        img_yuv = cv2.cvtColor(img_use, cv2.COLOR_BGR2YUV)
        img_y = img_yuv[:,:,0].astype(np.float32)

        bits = self.text_to_bits(secret_text)
        bits_len = len(bits)
        count = 0
        
        for i in range(0, h_safe, self.block_size):
            for j in range(0, w_safe, self.block_size):
                block = img_y[i:i+8, j:j+8]
                dct_block = cv2.dct(block)
                v1 = dct_block[self.pos1]
                v2 = dct_block[self.pos2]
                bit = bits[count % bits_len]
                
                P = self.alpha
                # 簡單過曝/過暗保護
                dc = dct_block[0,0]
                if dc > 240*8 or dc < 15*8:
                    pass 
                else:
                    if bit == 1:
                        if v1 <= v2 + P:
                            avg = (v1 + v2)/2
                            v1 = avg + (P/2) + 2
                            v2 = avg - (P/2) - 2
                    else:
                        if v2 <= v1 + P:
                            avg = (v1 + v2)/2
                            v1 = avg - (P/2) - 2
                            v2 = avg + (P/2) + 2
                
                dct_block[self.pos1] = v1
                dct_block[self.pos2] = v2
                img_y[i:i+8, j:j+8] = cv2.idct(dct_block)
                count += 1

        img_yuv[:,:,0] = np.clip(img_y, 0, 255).astype(np.uint8)
        img_out = img.copy()
        img_out[:h_safe, :w_safe] = cv2.cvtColor(img_yuv, cv2.COLOR_YUV2BGR)
        return img_out

    def _extract_one_pass(self, img_y):
        h, w = img_y.shape
        all_bits = []
        for i in range(0, h, self.block_size):
            for j in range(0, w, self.block_size):
                if i + 8 > h or j + 8 > w: continue
                block = img_y[i:i+8, j:j+8]
                dct_block = cv2.dct(block)
                all_bits.append(1 if dct_block[self.pos1] > dct_block[self.pos2] else 0)
        return self.bits_to_text_stream(all_bits)

    def extract_frame(self, img, allow_shift=True):
        if img is None: return None
        h, w = img.shape[:2]
        
        # 只取左上角分析
        scan_h = min(h, 1024)
        scan_w = min(w, 1024)
        img_scan = img[:scan_h, :scan_w]
        
        img_yuv = cv2.cvtColor(img_scan, cv2.COLOR_BGR2YUV)
        img_y = img_yuv[:,:,0].astype(np.float32)
        
        candidates = []

        if allow_shift:
            # 圖片模式：搜尋範圍稍微加大，確保抓到對齊
            search_range = range(8) 
        else:
            # 影片模式：極速
            search_range = range(1)

        for dy in search_range:
            for dx in search_range:
                if img_y.shape[0] <= dy+8 or img_y.shape[1] <= dx+8: continue

                shifted_img_y = img_y[dy:, dx:]
                raw_text = self._extract_one_pass(shifted_img_y)
                
                # [核心修正] 使用 Regex 進行智慧提取
                # 只要 raw_text 裡面包含 "MyWM:"，我們就啟動正則搜尋
                if self.header in raw_text:
                    
                    # 策略 1: 完美匹配 (找 MyWM:...:::)
                    # (.*?) 代表非貪婪匹配，找到最近的 ::: 就停
                    pattern_strict = r"MyWM:(.*?):::"
                    matches = re.findall(pattern_strict, raw_text)
                    for m in matches:
                        if len(m) > 0 and len(m) < 50: # 合理長度檢查
                            candidates.append(m)
                    
                    # 策略 2: 保底匹配 (找 MyWM: 後面跟著的一串英數字)
                    # [a-zA-Z0-9_\-\.]+ 代表只允許 英數、底線、減號、點
                    # 一旦遇到 & @ * 這種亂碼，就會自動停止
                    pattern_loose = r"MyWM:([a-zA-Z0-9_\-\.]+)"
                    matches_loose = re.findall(pattern_loose, raw_text)
                    for m in matches_loose:
                        if len(m) > 0 and len(m) < 50:
                            candidates.append(m)

        if not candidates:
            return None
            
        # 統計出現最多次的結果
        return Counter(candidates).most_common(1)[0][0]

# ==========================================
# 影片處理工具 (極速版)
# ==========================================
def process_video_embed(input_path, output_path, text, watermarker):
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened(): return False
    
    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps    = cap.get(cv2.CAP_PROP_FPS)
    
    width = (width // 8) * 8
    height = (height // 8) * 8

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret: break
        
        # 每 5 幀寫入一次
        if frame_idx % 5 == 0:
            frame = watermarker.embed_frame(frame, text)
        else:
            frame = frame[:height, :width]
            
        out.write(frame)
        frame_idx += 1
    
    cap.release()
    out.release()
    return True

def process_video_verify(input_path, watermarker):
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened(): return None
    
    frame_count = 0
    max_frames = 20
    
    print(f"Start Fast Video Verify: {input_path}")
    
    candidates = []

    while frame_count < max_frames:
        ret, frame = cap.read()
        if not ret: break
        
        # 影片驗證時，關閉位移搜尋以加速 (依賴多幀統計)
        res = watermarker.extract_frame(frame, allow_shift=False)
        if res:
            candidates.append(res)
            # 如果連續兩次讀到一樣的結果，直接信任並回傳
            if len(candidates) >= 2 and candidates[-1] == candidates[-2]:
                 cap.release()
                 return res
            
        frame_count += 1
        
    cap.release()
    
    # 如果沒提早結束，就統計出現最多次的
    if candidates:
        return Counter(candidates).most_common(1)[0][0]
        
    return None

def safe_read_image(path):
    try:
        with open(path, "rb") as f:
            bytes_data = np.frombuffer(f.read(), np.uint8)
        return cv2.imdecode(bytes_data, cv2.IMREAD_COLOR)
    except:
        return None

# ==========================================
# FastAPI Router
# ==========================================
app = FastAPI()
watermarker = DctRobustWatermark(alpha=40.0)

@app.post("/verify")
async def verify_watermark(file: UploadFile = File(...)):
    filename = file.filename
    ext = os.path.splitext(filename)[1].lower()
    is_video = ext in ['.mp4', '.avi', '.mov']
    
    try:
        if is_video:
            temp_input = f"temp_{uuid.uuid4()}{ext}"
            with open(temp_input, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            
            extracted_text = process_video_verify(temp_input, watermarker)
            if os.path.exists(temp_input): os.remove(temp_input)

        else:
            contents = await file.read()
            nparr = np.frombuffer(contents, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if img is None:
                return JSONResponse(content={"status": "failure", "message": "Image decode failed"})

            # 圖片模式開啟位移搜尋
            extracted_text = watermarker.extract_frame(img, allow_shift=True)

        if extracted_text:
            return JSONResponse(content={
                "status": "success", 
                "message": "Watermark Detected!", 
                "watermark_text": extracted_text
            })
        else:
            return JSONResponse(content={"status": "failure", "message": "No stable watermark found."})
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(content={"status": "error", "message": str(e)}, status_code=500)

@app.post("/embed")
async def embed_watermark(file: UploadFile = File(...), text: str = Form(...)):
    ext = os.path.splitext(file.filename)[1].lower()
    is_video = ext in ['.mp4', '.avi', '.mov']
    
    unique_name = str(uuid.uuid4())
    temp_input = f"temp_in_{unique_name}{ext}"
    temp_output = f"temp_out_{unique_name}{ext}" if is_video else f"temp_out_{unique_name}.jpg"

    with open(temp_input, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    try:
        if is_video:
            success = process_video_embed(temp_input, temp_output, text, watermarker)
            media_type = "video/mp4"
            out_filename = f"watermarked_{file.filename}"
        else:
            img = safe_read_image(temp_input)
            if img is None:
                return JSONResponse(content={"status": "error", "message": "Failed to read image"}, status_code=400)
            
            out_img = watermarker.embed_frame(img, text)
            
            is_success, buffer = cv2.imencode(".jpg", out_img, [cv2.IMWRITE_JPEG_QUALITY, 95])
            if is_success:
                with open(temp_output, "wb") as f:
                    f.write(buffer)
            success = True
            media_type = "image/jpeg"
            out_filename = f"watermarked_{os.path.splitext(file.filename)[0]}.jpg"

        if not success:
            return JSONResponse(content={"status": "error", "message": "Processing failed"}, status_code=500)

        return FileResponse(temp_output, media_type=media_type, filename=out_filename)

    except Exception as e:
        return JSONResponse(content={"status": "error", "message": str(e)}, status_code=500)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)