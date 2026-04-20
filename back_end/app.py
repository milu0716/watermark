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
# 核心一：希爾伯特曲線轉換與鏡像填充
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

    @staticmethod
    def mirror_coord(val, max_val):
        if val < 0:
            return -val
        if val >= max_val:
            period = 2 * (max_val - 1)
            if period <= 0: return 0
            val = val % period
            if val >= max_val:
                val = period - val
        return val

# ==========================================
# 核心二：顯著性偵測與幾何質心
# ==========================================
def get_geometric_centroid(img):
    """
    計算質心，並【強制對齊 8 的倍數】，避免 JPEG/MP4 壓縮網格破壞 DCT 頻域。
    """
    try:
        saliency = cv2.saliency.StaticSaliencySpectralResidual_create()
        success, saliencyMap = saliency.computeSaliency(img)
        if success:
            saliencyMap = (saliencyMap * 255).astype("uint8")
            _, threshMap = cv2.threshold(saliencyMap, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
            
            M = cv2.moments(threshMap)
            if M["m00"] != 0:
                cX = int(M["m10"] / M["m00"])
                cY = int(M["m01"] / M["m00"])
                # 【修改重點 1】強制對齊 8x8 網格
                return (cX // 8) * 8, (cY // 8) * 8
    except Exception as e:
        print(f"Saliency error: {e}")
        pass
    
    # 預設回傳圖像正中央，同樣對齊 8 的倍數
    return (img.shape[1] // 2 // 8) * 8, (img.shape[0] // 2 // 8) * 8


# ==========================================
# 升級版的演算法: 基於質心與希爾伯特曲線的 Robust DCT
# ==========================================
class DctRobustWatermark:
    def __init__(self, alpha=40.0):
        self.block_size = 8
        self.pos1 = (2, 1)
        self.pos2 = (1, 2)
        self.alpha = alpha
        self.header = "MyWM:"   
        self.footer = ":::EOF"  
        
        self.hilbert_grid_size = 32 
        self.max_bits = self.hilbert_grid_size * self.hilbert_grid_size

    def text_to_bits(self, text):
        full_text = self.header + text + self.footer
        max_chars = self.max_bits // 8
        repeat_count = max_chars // len(full_text)
        if repeat_count == 0: 
            repeat_count = 1
            
        repeated_text = full_text * repeat_count
        
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
            byte_str = ''.join(str(b) for b in byte)
            try:
                char_code = int(byte_str, 2)
                if 32 <= char_code <= 126: chars.append(chr(char_code))
                else: chars.append('')
            except: pass
        return ''.join(chars)

    def generate_embedding_path(self, cX, cY, max_w, max_h):
        path = []
        n = self.hilbert_grid_size
        
        offset_x = cX - (n * self.block_size // 2)
        offset_y = cY - (n * self.block_size // 2)

        for d in range(self.max_bits):
            hx, hy = HilbertTransform.d2xy(n, d)
            
            px = offset_x + hx * self.block_size
            py = offset_y + hy * self.block_size
            
            px = HilbertTransform.mirror_coord(px, max_w - self.block_size)
            py = HilbertTransform.mirror_coord(py, max_h - self.block_size)
            
            path.append((py, px)) 
        return path

    def embed_frame(self, img, secret_text):
        if img is None: return None
        h, w = img.shape[:2]
        
        cX, cY = get_geometric_centroid(img)
        print(f"🟢 [Embed] 寫入時的質心座標: ({cX}, {cY})")

        img_yuv = cv2.cvtColor(img, cv2.COLOR_BGR2YUV)
        img_y = img_yuv[:,:,0].astype(np.float32)

        bits = self.text_to_bits(secret_text)
        path = self.generate_embedding_path(cX, cY, w, h)
        
        for idx, (i, j) in enumerate(path):
            block = img_y[i:i+8, j:j+8]
            dct_block = cv2.dct(block)
            v1 = dct_block[self.pos1]
            v2 = dct_block[self.pos2]
            bit = bits[idx]
            
            P = self.alpha
            
            # 【修改重點 2】拿掉 if dc > 240*8 判斷，確保 1:1 無條件寫入位元，防止萃取錯亂
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

        img_yuv[:,:,0] = np.clip(img_y, 0, 255).astype(np.uint8)
        img_out = cv2.cvtColor(img_yuv, cv2.COLOR_YUV2BGR)
        return img_out

    def extract_frame(self, img):
        if img is None: return None
        h, w = img.shape[:2]
        
        img_yuv = cv2.cvtColor(img, cv2.COLOR_BGR2YUV)
        img_y = img_yuv[:,:,0].astype(np.float32)
        
        candidates = []
        
        cX, cY = get_geometric_centroid(img)
        print(f"🔴 [Verify] 讀取時的初始質心座標: ({cX}, {cY})")
        
        # 【修改重點 3】大幅縮小搜尋範圍，先用 -2 到 +2 驗證核心邏輯，防 FastAPI 超時
        for dy in range(-8, 9):
            for dx in range(-8, 9):
                test_cX, test_cY = cX + dx, cY + dy
                path = self.generate_embedding_path(test_cX, test_cY, w, h)
                
                all_bits = []
                for (i, j) in path:
                    if i + 8 > h or j + 8 > w or i < 0 or j < 0:
                        all_bits.append(0)
                        continue

                    block = img_y[i:i+8, j:j+8]
                    dct_block = cv2.dct(block)
                    all_bits.append(1 if dct_block[self.pos1] > dct_block[self.pos2] else 0)
                
                raw_text = self.bits_to_text_stream(all_bits)

                # 寬鬆或嚴謹的 Regex 擷取
                if self.header in raw_text:
                    pattern_strict = r"MyWM:(.*?):::"
                    matches = re.findall(pattern_strict, raw_text)
                    for m in matches:
                        if 0 < len(m) < 50: candidates.append(m)
                
                    pattern_loose = r"MyWM:([a-zA-Z0-9_\-\.]+)"
                    matches_loose = re.findall(pattern_loose, raw_text)
                    for m in matches_loose:
                        if 0 < len(m) < 50: candidates.append(m)

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