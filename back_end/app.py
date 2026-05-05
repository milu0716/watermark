from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse
import numpy as np
import cv2
import os
import shutil
from collections import Counter
import uuid
import re  

def remove_file(path: str):
    if os.path.exists(path):
        os.remove(path)

# ==========================================
# 核心一：希爾伯特曲線轉換 (移除邊界鏡像依賴)
# ==========================================
class HilbertTransform:
    @staticmethod
    def d2xy(n, d):
        t = d
        x = y = 0
        s = 1
        while s < n:
            rx = 1 & (t // 2)
            ry = 1 & (t ^ rx)
            if ry == 0:
                if rx == 1:
                    x, y = s - 1 - x, s - 1 - y
                x, y = y, x
            x += s * rx
            y += s * ry
            t //= 4
            s *= 2
        return x, y

# ==========================================
# 核心二：ORB 特徵點與 ROI 邊界框擷取
# ==========================================
def get_orb_boxes(img, box_size=128, top_n=5, min_dist=128):
    """
    尋找圖片中最強的 ORB 特徵點，並回傳這些點對應的 ROI 框框左上角座標。
    加入 min_dist 參數，確保特徵點彼此分散，提高抗裁切能力。
    """
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 初始化 ORB (多找一點備用，避免距離過濾後數量不夠)
    orb = cv2.ORB_create(nfeatures=1000)
    keypoints, _ = orb.detectAndCompute(gray, None)
    
    # 預設回傳圖片正中央 (當作防呆備案)
    fallback_box = [(max(0, w//2 - box_size//2), max(0, h//2 - box_size//2))]
    
    if not keypoints:
        print("⚠️ 無法找到 ORB 特徵點，使用畫面中央作為備案。")
        return fallback_box

    # 依照特徵點強度 (response) 排序，取最強的點
    keypoints = sorted(keypoints, key=lambda x: x.response, reverse=True)
    
    boxes = []
    # 記錄已選取的中心點，用來計算距離
    selected_centers = [] 
    half_box = box_size // 2
    
    for kp in keypoints:
        kx, ky = int(kp.pt[0]), int(kp.pt[1])
        start_x, start_y = kx - half_box, ky - half_box
        
        # 1. 確保框框不會超出圖片邊界
        if start_x >= 0 and start_y >= 0 and (start_x + box_size) <= w and (start_y + box_size) <= h:
            
            # 2. 確保特徵點彼此保持安全距離 (分散邏輯)
            too_close = False
            for cx, cy in selected_centers:
                # 計算與已選中點的直線距離 (歐式距離)
                if ((kx - cx)**2 + (ky - cy)**2)**0.5 < min_dist:
                    too_close = True
                    break
            
            if not too_close:
                boxes.append((start_x, start_y))
                selected_centers.append((kx, ky))
                if len(boxes) >= top_n:
                    break
                
    if not boxes:
        print("⚠️ ORB 特徵點太靠近邊緣或無法分散，使用畫面中央作為備案。")
        return fallback_box
        
    return boxes

# ==========================================
# 升級版演算法: ORB + 局部希爾伯特曲線 DCT 浮水印
# ==========================================
class DctRobustWatermark:
    def __init__(self, alpha=60.0):
        self.block_size = 8
        self.pos1 = (2, 1)
        self.pos2 = (1, 2)
        self.alpha = alpha
        
        # 縮短 Header/Footer 節省位元空間
        self.header = "W["   
        self.footer = "]E"  
        
        # 定義局部的浮水印小宇宙 (128x128 像素)
        self.hilbert_grid_size = 16 
        self.box_size = self.hilbert_grid_size * self.block_size 
        self.max_bits = self.hilbert_grid_size * self.hilbert_grid_size # 256 bits
        
        # 預先計算相對座標路徑 (不受外在圖片大小影響)
        self.local_path = self._generate_local_path()

    def text_to_bits(self, text):
        full_text = self.header + text + self.footer
        max_chars = self.max_bits // 8
        repeat_count = max_chars // len(full_text)
        if repeat_count == 0: repeat_count = 1
            
        repeated_text = (full_text * repeat_count)[:max_chars]
        
        bits = []
        for char in repeated_text:
            bin_val = bin(ord(char))[2:].rjust(8, '0')
            bits.extend([int(b) for b in bin_val])
            
        if len(bits) < self.max_bits:
            bits.extend([0] * (self.max_bits - len(bits)))
            
        return bits[:self.max_bits]

    def bits_to_text_stream(self, bits):
        chars = []
        for i in range(0, len(bits), 8):
            byte = bits[i:i+8]
            if len(byte) < 8: break
            try:
                char_code = int(''.join(str(b) for b in byte), 2)
                if 32 <= char_code <= 126: chars.append(chr(char_code))
                else: chars.append('')
            except: pass
        return ''.join(chars)

    def _generate_local_path(self):
        path = []
        n = self.hilbert_grid_size
        for d in range(self.max_bits):
            hx, hy = HilbertTransform.d2xy(n, d)
            py = hy * self.block_size
            px = hx * self.block_size
            path.append((py, px)) 
        return path

    def _process_box(self, box_y, bits=None, mode='embed'):
        """處理單一 128x128 區塊的寫入或讀取"""
        extracted_bits = []
        for idx, (i, j) in enumerate(self.local_path):
            block = box_y[i:i+8, j:j+8]
            dct_block = cv2.dct(block)
            
            if mode == 'embed':
                if idx >= len(bits): break
                v1, v2 = dct_block[self.pos1], dct_block[self.pos2]
                bit = bits[idx]
                P = self.alpha
                
                if bit == 1:
                    if v1 <= v2 + P:
                        avg = (v1 + v2)/2
                        dct_block[self.pos1] = avg + (P/2) + 2
                        dct_block[self.pos2] = avg - (P/2) - 2
                else:
                    if v2 <= v1 + P:
                        avg = (v1 + v2)/2
                        dct_block[self.pos1] = avg - (P/2) - 2
                        dct_block[self.pos2] = avg + (P/2) + 2
                
                box_y[i:i+8, j:j+8] = cv2.idct(dct_block)
            else:
                # Extract mode
                extracted_bits.append(1 if dct_block[self.pos1] > dct_block[self.pos2] else 0)
                
        if mode == 'embed':
            return box_y
        return extracted_bits

    def embed_frame(self, img, secret_text):
        if img is None: return None
        
        img_yuv = cv2.cvtColor(img, cv2.COLOR_BGR2YUV)
        img_y = img_yuv[:,:,0].astype(np.float32)

        bits = self.text_to_bits(secret_text)
        
        # 取得最強的 5 個 ORB 特徵點周圍的 128x128 框框
        target_boxes = get_orb_boxes(img, box_size=self.box_size, top_n=10)
        print(f"🟢 [Embed] ORB 找到 {len(target_boxes)} 個寫入區域")

        for (start_x, start_y) in target_boxes:
            box_y = img_y[start_y:start_y+self.box_size, start_x:start_x+self.box_size]
            img_y[start_y:start_y+self.box_size, start_x:start_x+self.box_size] = self._process_box(box_y, bits, mode='embed')

        img_yuv[:,:,0] = np.clip(img_y, 0, 255).astype(np.uint8)
        return cv2.cvtColor(img_yuv, cv2.COLOR_YUV2BGR)

    def extract_frame(self, img):
        if img is None: return None
        
        img_yuv = cv2.cvtColor(img, cv2.COLOR_BGR2YUV)
        img_y = img_yuv[:,:,0].astype(np.float32)
        
        candidates = []
        
        # 讀取時，再度使用 ORB 找尋被裁切後圖片中倖存的特徵點
        target_boxes = get_orb_boxes(img, box_size=self.box_size, top_n=15) # 讀取時可多找幾個點提高機率
        print(f"🔴 [Verify] ORB 掃描了 {len(target_boxes)} 個可能的區域")
        
        pattern = re.escape(self.header) + r"(.*?)" + re.escape(self.footer)
        
        for (start_x, start_y) in target_boxes:
            # 針對 ORB 找到的點，稍微做一點微調容錯 (+-4 像素)，防禦 DCT 網格偏移
            for dy in range(-4, 5, 4):
                for dx in range(-4, 5, 4):
                    y, x = start_y + dy, start_x + dx
                    if y < 0 or x < 0 or (y + self.box_size) > img.shape[0] or (x + self.box_size) > img.shape[1]:
                        continue
                        
                    box_y = img_y[y:y+self.box_size, x:x+self.box_size]
                    all_bits = self._process_box(box_y, mode='extract')
                    raw_text = self.bits_to_text_stream(all_bits)

                    matches = re.findall(pattern, raw_text)
                    for m in matches:
                        if 0 < len(m) < 32 and m.isprintable(): 
                            candidates.append(m)

        if not candidates:
            return None
            
        return Counter(candidates).most_common(1)[0][0]

# ==========================================
# 影片處理工具
# ==========================================
def process_video_embed(input_path, output_path, text, watermarker):
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened(): return False
    
    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps    = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    # ✅ 先印出來讓我們看
    print(f"📊 width={width}, height={height}")
    print(f"📊 fps={fps}")
    print(f"📊 total_frames={total_frames}")
    print(f"📊 預期秒數={total_frames/fps:.2f}s")

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret: break
        
        if frame_idx % 5 == 0:
            watermarked = watermarker.embed_frame(frame, text)
            if watermarked is not None:
                frame = watermarked
            
        out.write(frame)
        frame_idx += 1
    
    cap.release()
    out.release()
    
    # ✅ 實際寫入幀數
    print(f"📊 實際寫入幀數={frame_idx}")
    print(f"📊 實際輸出秒數={frame_idx/fps:.2f}s")
    return True

def process_video_verify(input_path, watermarker):
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened(): return None
    
    frame_count = 0
    max_frames = 20  # 最多分析 20 幀（即實際讀取 20*5=100 幀）
    candidates = []

    while frame_count < max_frames:
        ret, frame = cap.read()
        if not ret: break
        
        # ✅ 只分析有嵌入浮水印的幀（與 embed 的 % 5 對齊）
        if frame_count % 5 == 0:
            res = watermarker.extract_frame(frame)
            if res:
                candidates.append(res)
                if len(candidates) >= 2 and candidates[-1] == candidates[-2]:
                    cap.release()
                    return res
            
        frame_count += 1

    cap.release()
    
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
# 設定為 60 強度比較能扛得住 JPEG 與 MP4 壓縮
watermarker = DctRobustWatermark(alpha=60.0)

@app.post("/verify")
async def verify_watermark(file: UploadFile = File(...), background_tasks: BackgroundTasks = None):
    filename = file.filename
    ext = os.path.splitext(filename)[1].lower()
    is_video = ext in ['.mp4', '.avi', '.mov', '.mkv', '.mpeg', '.mpg', '.3gp']
    
    try:
        if is_video:
            temp_input = f"temp_{uuid.uuid4()}{ext}"
            with open(temp_input, "wb") as buffer:
                while True:
                    chunk = await file.read(1024 * 1024) # 每次讀取 1MB
                    if not chunk:
                        break
                    buffer.write(chunk)
            
            extracted_text = process_video_verify(temp_input, watermarker)

            if background_tasks:
                background_tasks.add_task(remove_file, temp_input)
            elif os.path.exists(temp_input): 
                try: os.remove(temp_input)
                except: pass
        else:
            contents = await file.read()
            nparr = np.frombuffer(contents, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if img is None:
                return JSONResponse(content={"status": "failure", "message": "Image decode failed"})

            extracted_text = watermarker.extract_frame(img)

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
async def embed_watermark(file: UploadFile = File(...), text: str = Form(...), background_tasks: BackgroundTasks = None):
    filename = file.filename 
    ext = os.path.splitext(filename)[1].lower()
    
    is_video = ext in ['.mp4', '.avi', '.mov', '.mkv', '.mpeg', '.mpg', '.3gp']
    
    unique_name = str(uuid.uuid4())
    temp_input = f"temp_in_{unique_name}{ext}"
    
    if is_video:
        temp_output = f"temp_out_{unique_name}.mp4"
    else:
        temp_output = f"temp_out_{unique_name}.jpg"

    print(f"📥 開始接收檔案: {filename}")
    try:
        with open(temp_input, "wb") as buffer:
            while True:
                chunk = await file.read(1024 * 1024)  # 每次讀取 1MB
                if not chunk:
                    break
                buffer.write(chunk)
    except Exception as e:
        return JSONResponse(content={"status": "error", "message": f"File save error: {str(e)}"}, status_code=400)
    
    if os.path.getsize(temp_input) == 0:
        return JSONResponse(content={"status": "error", "message": "Empty file received"}, status_code=400)
        
    try:
        if is_video:
            print("🎬 偵測為影片，開始處理...")
            success = process_video_embed(temp_input, temp_output, text, watermarker)
            media_type = "video/mp4"
            original_name_no_ext = os.path.splitext(filename)[0]
            out_filename = f"watermarked_{original_name_no_ext}.mp4"
        else:
            print("🖼️ 偵測為圖片，開始讀取...")
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
            out_filename = f"watermarked_{os.path.splitext(filename)[0]}.jpg"

        if not success:
            return JSONResponse(content={"status": "error", "message": "Processing failed"}, status_code=500)

        if background_tasks:
            background_tasks.add_task(remove_file, temp_input)
            background_tasks.add_task(remove_file, temp_output)

        print(f"🚀 處理完成，回傳檔案: {out_filename}")
        return FileResponse(temp_output, media_type=media_type, filename=out_filename)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(content={"status": "error", "message": str(e)}, status_code=500)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)