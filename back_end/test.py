import cv2
import numpy as np
from app import DctRobustWatermark, safe_read_image # 引用你原本的程式

def run_compression_test(image_path, text_to_embed):
    # 1. 初始化
    wm = DctRobustWatermark(alpha=40.0) # 你的設定
    print(f"--- 開始測試圖片: {image_path} ---")
    
    # 2. 讀取並嵌入
    original = safe_read_image(image_path)
    if original is None:
        print("錯誤：找不到圖片")
        return

    print(f"嵌入文字: {text_to_embed}")
    embedded_img = wm.embed_frame(original, text_to_embed)
    
    # 3. 測試不同 JPEG 品質 (Quality)
    # 數值 100 = 最好, 1 = 最爛 (通常低於 50 肉眼就看得出破壞)
    qualities = [95, 80, 60, 40, 30]
    
    for q in qualities:
        filename = f"test_q{q}.jpg"
        
        # 模擬壓縮：存檔
        cv2.imwrite(filename, embedded_img, [cv2.IMWRITE_JPEG_QUALITY, q])
        
        # 模擬讀取：重新讀進來 (這時候像素已經被 JPEG 演算法破壞了)
        compressed_img = cv2.imread(filename)
        
        # 嘗試解碼
        result = wm.extract_frame(compressed_img, allow_shift=True)
        
        # 判定結果
        status = "✅ 成功" if result == text_to_embed else f"❌ 失敗 (讀到: {result})"
        print(f"[JPEG 品質 {q}] -> {status}")

if __name__ == "__main__":
    # 請換成你電腦裡隨便一張照片的路徑
    run_compression_test("ny.jpg", "Hello1234")