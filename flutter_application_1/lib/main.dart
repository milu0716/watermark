// -----------------------------------------------------------------------------
// 檔案頂部：匯入所有需要的套件
// -----------------------------------------------------------------------------
import 'dart:io'; // 用於檔案操作，例如 File class
import 'dart:typed_data'; // 用於處理原始位元組數據，例如 Uint8List
// 匯入 foundation 套件，目的是為了使用 compute 函式，它能將繁重的工作移至背景執行緒。
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart'; // Flutter Material Design UI 框架
import 'package:image_picker/image_picker.dart'; // 從相簿或相機選擇圖片的套件
import 'package:image/image.dart' as img; // 強大的 Dart 圖片處理函式庫，我們使用 'img' 作為別名以避免名稱衝突
import 'package:path_provider/path_provider.dart'; // 用於尋找檔案系統上的常用路徑，例如 App 的文件目錄
import 'package:permission_handler/permission_handler.dart'; // 用於在執行時請求和檢查權限
import 'package:gal/gal.dart';
// -----------------------------------------------------------------------------
// 背景圖片處理函式
// 這是一個「頂層函式」(Top-level function)，必須放在 class 之外，才能被 compute 呼叫。
// -----------------------------------------------------------------------------
Future<Uint8List?> _processImageInBackground(Map<String, dynamic> params) async {
  // 從傳入的參數中解析出需要的資料
  final File imageFile = params['imageFile'];
  final String watermarkText = params['watermarkText'];
  try {
    // 步驟 1: 將圖片檔案讀取成原始的位元組數據 (Uint8List)
    Uint8List imageBytes = await imageFile.readAsBytes();

    // 步驟 2: 將位元組解碼成 `image` 套件可以操作的 Image 物件。
    // 這是一個非常耗費 CPU 資源的操作，因此適合放在背景執行緒。
    img.Image? originalImage = img.decodeImage(imageBytes);
    if (originalImage == null) return null;

    // 建立一個圖片複本來進行修改，避免操作原始資料
    img.Image watermarkedImage = img.copyResize(originalImage,
        width: originalImage.width, height: originalImage.height);
        
    // 使用 `ColorRgba8` 來定義顏色，每個通道(R,G,B,Alpha)的值是 0-255。
    // 150 代表約 60% 的不透明度。
    final color = img.ColorRgba8(0, 0, 0, 150);

    // 步驟 3: 在圖片上繪製文字浮水印
    img.drawString(
      watermarkedImage,
      watermarkText,
      font: img.arial24, // 使用 image 套件內建的 24 號 Arial 字體
      x: watermarkedImage.width ~/ 4, // 簡單定位在 1/4 寬度處
      y: watermarkedImage.height ~/ 2, // 簡單定位在 1/2 高度處
      color: color,
    );
    
    // 步驟 4: 將加上浮水印的 Image 物件編碼成 JPG 格式的位元組。
    // 這也是一個耗費 CPU 資源的操作。
    return img.encodeJpg(watermarkedImage);
  } catch (e) {
    // 如果在背景處理中發生任何錯誤，印出日誌並返回 null
    debugPrint('Error in background processing: $e');
    return null;
  }
}

// -----------------------------------------------------------------------------
// 應用程式的主要進入點 (Entry Point)
// Dart 程式從這裡開始執行。
// -----------------------------------------------------------------------------
void main() {
  // runApp 是 Flutter 的核心函式，它會將給定的 Widget 作為 App 的根元素並渲染到螢幕上。
  runApp(const WatermarkApp());
}

// -----------------------------------------------------------------------------
// App 的根 Widget (Root Widget)
// 這是一個無狀態的 Widget (StatelessWidget)，因為它本身不包含會改變的狀態。
// 它的主要工作是設定 App 的整體主題、標題和首頁。
// -----------------------------------------------------------------------------
class WatermarkApp extends StatelessWidget {
  const WatermarkApp({super.key});
  @override
  Widget build(BuildContext context) {
    // MaterialApp 是一個方便的 Widget，它封裝了 App 所需的許多常用功能，
    // 如路由管理、主題設定等。
    return MaterialApp(
      title: 'Watermark App', // App 在作業系統中的標題
      theme: ThemeData( // 設定 App 的整體視覺主題
        primarySwatch: Colors.pink, // 主題色板
        useMaterial3: true, // 啟用 Material 3 設計風格
      ),
      home: const WatermarkScreen(), // 指定 App 的首頁
    );
  }
}

// -----------------------------------------------------------------------------
// 主要畫面的 Widget
// 這是一個有狀態的 Widget (StatefulWidget)，因為它需要儲存和管理會改變的資料，
// 例如使用者選擇的圖片檔案 (`_selectedImage`)。
// -----------------------------------------------------------------------------
class WatermarkScreen extends StatefulWidget {
  const WatermarkScreen({super.key});
  @override
  State<WatermarkScreen> createState() => _WatermarkScreenState();
}

// -----------------------------------------------------------------------------
// `WatermarkScreen` 的狀態管理類別 (State Class)
// 所有會變動的資料和與之相關的邏輯都寫在這裡。
// -----------------------------------------------------------------------------
class _WatermarkScreenState extends State<WatermarkScreen> {
  // --- 狀態變數 ---
  File? _selectedImage; // 用於儲存使用者選擇的圖片檔案。初始為 null。
  final String _watermarkText = 'Flutter Watermark Demo'; // 預設的浮水印文字
  // 用於控制 TextField 輸入框的控制器，可以讀取/設定輸入框的文字。
  final TextEditingController _watermarkController = TextEditingController();

  final ImagePicker _picker = ImagePicker();
  // --- 生命週期方法 ---
  // initState 是 Widget 生命週期中的一個方法，它在 Widget 第一次被建立時只會執行一次。
  // 適合用來做一些初始化的設定。
  @override
  void initState() {
    super.initState();
    // 初始化時，將預設文字填入輸入框控制器
    _watermarkController.text = _watermarkText;
  }

  // --- 新增的函式：顯示選擇圖片來源的 BottomSheet ---
  Future<void> _showImageSourceOptions() async {
    showModalBottomSheet(
      context: context,
      builder: (BuildContext context) {
        return SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min, // 讓 Column 內容決定高度
            children: <Widget>[
              ListTile(
                leading: const Icon(Icons.photo_library),
                title: const Text('從相簿選擇'),
                onTap: () {
                  Navigator.pop(context); // 關閉 BottomSheet
                  _pickImage(ImageSource.gallery); // 呼叫選擇相簿
                },
              ),
              ListTile(
                leading: const Icon(Icons.camera_alt),
                title: const Text('使用相機拍照'),
                onTap: () {
                  Navigator.pop(context); // 關閉 BottomSheet
                  _pickImage(ImageSource.camera); // 呼叫使用相機
                },
              ),
            ],
          ),
        );
      },
    );
  }

  // --- 功能函式 ---
 // --- 修改後的函式：從相簿或相機選擇圖片 ---
  Future<void> _pickImage(ImageSource source) async {
    // 如果來源是相機，先請求相機權限
    if (source == ImageSource.camera) {
      if (await Permission.camera.request().isDenied) {
        _showSnackbar('無法使用相機：請授予相機權限！', Colors.orange);
        return;
      }
    }

    // 因為相簿也需要儲存權限才能讀取，所以在這統一請求
    // 但在 Android 13+ 上，ImagePicker 會自動處理，舊版本需要手動請求
    if (source == ImageSource.gallery) {
      if (await Permission.storage.request().isDenied) { // 這裡可以更精確地請求 Permission.photos
        _showSnackbar('無法讀取相簿：請授予儲存權限！', Colors.orange);
        return;
      }
    }
    
    // 使用 _picker 實例來選擇圖片
    final pickedFile = await _picker.pickImage(source: source);
    if (pickedFile != null) {
      setState(() {
        _selectedImage = File(pickedFile.path);
      });
    }
  }

  // 這是按下「儲存」按鈕後的核心函式 (最終版本)
Future<void> _applyWatermarkAndSave() async {
  // 檢查 1: 確認使用者已經選擇了圖片 (不變)
  if (_selectedImage == null) {
    _showSnackbar('請先選擇一張圖片！', Colors.red);
    return;
  }

  // 步驟 2: 請求相簿權限 (使用我們之前修正好的正確版本)
  final status = await Permission.photos.request();
  if (!status.isGranted) {
    if (status.isPermanentlyDenied) {
      _showSnackbar('您已永久拒絕權限，請前往設定頁面開啟', Colors.red);
      await Future.delayed(const Duration(seconds: 2));
      openAppSettings();
    } else {
      _showSnackbar('無法儲存：請授予相簿權限！', Colors.orange);
    }
    return;
  }

  // 顯示處理中提示
  _showSnackbar('正在處理圖片，請稍候...', Colors.blue);
  
  try {
    // 準備參數並在背景執行緒處理圖片 (不變)
    final params = {
      'imageFile': _selectedImage!,
      'watermarkText': _watermarkController.text.isEmpty 
          ? _watermarkText 
          : _watermarkController.text,
    };
    final Uint8List? encodedImage = await compute(_processImageInBackground, params);

    if (encodedImage == null) {
      _showSnackbar('圖片處理失敗！', Colors.red);
      return;
    }

    // ==================== 核心修改：使用 gal 儲存到相簿 ====================

    // 直接將處理好的圖片數據 (Uint8List) 交給 gal 套件儲存
    await Gal.putImageBytes(
      encodedImage,
      album: '我的浮水印作品' // (可選) 您可以在相簿中建立一個專屬的資料夾名稱
    );

    _showSnackbar('圖片已成功儲存到手機相簿！', Colors.green);

    // ====================================================================

  } catch (e) {
    // 捕捉 gal 或其他步驟可能拋出的錯誤
    _showSnackbar('儲存失敗: $e', Colors.red);
  }
}

  // 用於顯示提示訊息的輔助函式 (SnackBar)
  void _showSnackbar(String message, Color color) {
    // 檢查 Widget 是否還掛載在 Widget 樹上。這是一個好習慣，可以防止在非同步操作完成後，
    // 對一個已經被銷毀的 Widget 進行操作而導致錯誤。
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(message),
          backgroundColor: color,
        ),
      );
    }
  }

  // --- UI 建構方法 ---
  // build 方法是 Flutter 的核心，它描述了 Widget 的 UI 應該長什麼樣子。
  // 當 setState 被呼叫時，這個方法會被重新執行以更新畫面。
  @override
  Widget build(BuildContext context) {
    // Scaffold 提供了 Material Design 的基本視覺佈局結構，如 AppBar, Body 等。
    return Scaffold(
      appBar: AppBar( // 頂部的應用程式欄
        title: const Text('圖片浮水印生成器'),
        backgroundColor: const Color.fromARGB(255, 255, 127, 223),
        foregroundColor: Colors.white,
      ),
      // SingleChildScrollView 讓它的子 Widget 在內容超出螢幕時可以滾動，
      // 這可以防止在小螢幕或鍵盤彈出時發生內容溢出的錯誤。
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16.0), // 在內容周圍加上邊距
        child: Column( // Column 將其子 Widget 垂直排列
          crossAxisAlignment: CrossAxisAlignment.stretch, // 讓子 Widget 在水平方向上填滿寬度
          children: <Widget>[
            // 1. 選擇圖片的按鈕
            ElevatedButton.icon(
              onPressed: _showImageSourceOptions,
              icon: const Icon(Icons.photo_library),
              label: const Text('選擇圖片或拍照 (輸入)'),
              style: ElevatedButton.styleFrom(
                padding: const EdgeInsets.all(12),
                backgroundColor: Colors.teal.shade100,
                foregroundColor: Colors.teal.shade900,
              ),
            ),
            const SizedBox(height: 20), // 用於在 Widget 之間增加垂直間距
            // 2. 浮水印文字輸入框
            TextField(
              controller: _watermarkController, // 綁定控制器
              decoration: InputDecoration(
                labelText: '請輸入浮水印文字',
                border: const OutlineInputBorder(),
                suffixIcon: IconButton( // 輸入框尾部的清除按鈕
                  icon: const Icon(Icons.clear),
                  onPressed: () => _watermarkController.clear(),
                ),
              ),
            ),
            const SizedBox(height: 20),
            // 3. 圖片預覽區
            // 使用三元運算子進行條件渲染：如果 `_selectedImage` 是 null，就顯示提示框；否則顯示圖片。
            _selectedImage == null
                ? Container( // 尚未選擇圖片時的提示框
                    height: 200,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: Colors.grey[200],
                      border: Border.all(color: Colors.grey),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: const Text('尚未選擇圖片',
                        style: TextStyle(color: Colors.grey)),
                  )
                : SizedBox( // 選擇圖片後的預覽區
                    width: double.infinity,
                    child: AspectRatio( // 固定子 Widget 的寬高比
                      aspectRatio: 16 / 9,
                      // 使用 Stack Widget 將圖片和預覽文字疊加在一起
                      child: Stack(
                        alignment: Alignment.center,
                        children: [
                          // 顯示使用者選擇的原始圖片
                          Image.file(
                            _selectedImage!,
                            fit: BoxFit.cover, // 讓圖片填滿容器，可能會裁切
                          ),
                          // 疊加一個模擬的浮水印文字作為預覽
                          // 注意：這只是一個「視覺預覽」，並未真正修改圖片。
                          // 實際的圖片處理只在按下儲存按鈕時才會透過 compute 發生。
                          Transform.rotate(
                            angle: -30 * 3.14159 / 180, // 將角度轉換為弧度來旋轉 -30 度
                            child: Text(
                              _watermarkController.text.isEmpty
                                  ? _watermarkText
                                  : _watermarkController.text,
                              style: TextStyle(
                                color: Colors.white.withOpacity(0.6),
                                fontSize: 24,
                                fontWeight: FontWeight.bold,
                                shadows: [ // 加上陰影讓文字在複雜背景下更清晰
                                  Shadow(
                                    blurRadius: 2.0,
                                    color: Colors.black.withOpacity(0.5),
                                    offset: const Offset(1.0, 1.0),
                                  ),
                                ],
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
            const SizedBox(height: 30),
            // 4. 儲存按鈕
            ElevatedButton.icon(
              onPressed: _applyWatermarkAndSave,
              icon: const Icon(Icons.save),
              label: const Text('應用浮水印並儲存 (輸出)',
                  style: TextStyle(fontSize: 16)),
              style: ElevatedButton.styleFrom(
                padding: const EdgeInsets.all(15),
                backgroundColor: Colors.teal,
                foregroundColor: Colors.white,
              ),
            ),
          ],
        ),
      ),
    );
  }
}