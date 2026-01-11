import 'dart:io';
import 'dart:convert'; // 新增: 用於 JSON 解析
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';
import 'package:path_provider/path_provider.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:video_player/video_player.dart';
// 引用 Git 版的套件名稱
import 'package:ffmpeg_kit_flutter/ffmpeg_kit.dart';
import 'package:ffmpeg_kit_flutter/return_code.dart';
import 'package:gal/gal.dart';
import 'api_service.dart';
import 'package:http/http.dart' as http;

void main() {
  runApp(const WatermarkApp());
}

class WatermarkApp extends StatelessWidget {
  const WatermarkApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'Watermark Studio',
      theme: ThemeData(
        primarySwatch: Colors.deepPurple,
        useMaterial3: true,
        scaffoldBackgroundColor: Colors.white,
      ),
      home: const MainScreen(),
    );
  }
}

class MainScreen extends StatefulWidget {
  const MainScreen({super.key});
  @override
  State<MainScreen> createState() => _MainScreenState();
}

class _MainScreenState extends State<MainScreen> with SingleTickerProviderStateMixin {
  final List<String> _tabs = ["製作 (Create)", "驗證 (Verify)"];
  late TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: _tabs.length, vsync: this);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text("隱形浮水印系統", style: TextStyle(fontWeight: FontWeight.bold)),
        bottom: TabBar(
          controller: _tabController,
          tabs: _tabs.map((t) => Tab(text: t)).toList(),
          indicatorColor: Colors.deepPurple,
          labelColor: Colors.deepPurple,
        ),
      ),
      body: TabBarView(
        controller: _tabController,
        children: const [
          WatermarkCreatePage(),
          WatermarkVerifyPage(),
        ],
      ),
    );
  }
}

// =============================================================================
// 分頁 1: 製作浮水印 (改為呼叫後端 API)
// =============================================================================
class WatermarkCreatePage extends StatefulWidget {
  const WatermarkCreatePage({super.key});
  @override
  State<WatermarkCreatePage> createState() => _WatermarkCreatePageState();
}

class _WatermarkCreatePageState extends State<WatermarkCreatePage> with AutomaticKeepAliveClientMixin {
  File? _selectedFile;
  bool _isVideo = false;
  VideoPlayerController? _videoController;
  bool _isLoading = false;
  
  // 這裡的文字將被轉換成二進位隱藏在圖片頻率中
  final TextEditingController _watermarkController = TextEditingController(text: "User123");
  final ImagePicker _picker = ImagePicker();

  @override
  bool get wantKeepAlive => true;

  @override
  void dispose() {
    _videoController?.dispose();
    _watermarkController.dispose();
    super.dispose();
  }

  // 修改重點 1: 改用 API 上傳，而非本地 FFmpeg
  // 修改後：使用 ApiService
  Future<void> _processMediaApi() async {
    if (_selectedFile == null) return;
    FocusScope.of(context).unfocus();
    setState(() => _isLoading = true);

    try {
      // 直接呼叫 ApiService，程式碼更簡潔
      final Uint8List? resultBytes = await ApiService.embedWatermark(
        _selectedFile!, 
        _watermarkController.text
      );

      if (resultBytes != null) {
        // 存檔流程
        final Directory tempDir = await getTemporaryDirectory();
        final String ext = _isVideo ? "mp4" : "jpg";
        final String outputPath = "${tempDir.path}/watermarked_${DateTime.now().millisecondsSinceEpoch}.$ext";
        
        final File outputFile = File(outputPath);
        await outputFile.writeAsBytes(resultBytes);

        // 存入相簿
        if (_isVideo) {
          await Gal.putVideo(outputPath);
        } else {
          await Gal.putImage(outputPath);
        }
        
        _showSnackbar("成功！隱形浮水印已嵌入並存入相簿 ✅", Colors.green);
      } else {
        _showSnackbar("製作失敗，請檢查伺服器狀態", Colors.red);
      }
    } catch (e) {
      _showSnackbar("發生錯誤: $e", Colors.red);
    } finally {
      setState(() => _isLoading = false);
    }
  }

  // 選取媒體 (支援 Video 與 Image)
  Future<void> _pickMedia(ImageSource source, {bool isVideo = false}) async {
    try {
      final XFile? picked;
      if (isVideo) {
        picked = await _picker.pickVideo(source: source, maxDuration: const Duration(minutes: 5));
      } else {
        picked = await _picker.pickImage(source: source);
      }

      if (picked != null) {
        File file = File(picked.path);
        _videoController?.dispose();
        _videoController = null;

        if (isVideo) {
          _videoController = VideoPlayerController.file(file);
          await _videoController!.initialize();
          _videoController!.setLooping(true);
          _videoController!.play();
        }

        setState(() {
          _selectedFile = file;
          _isVideo = isVideo;
        });
      }
    } catch (e) {
       _showSnackbar("選取失敗: $e", Colors.red);
    }
  }

  void _showSnackbar(String msg, Color color) {
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg), backgroundColor: color));
  }

  void _showMediaOptions() {
    showModalBottomSheet(
      context: context,
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.photo, color: Colors.deepPurple),
              title: const Text("選擇圖片"),
              onTap: () { Navigator.pop(context); _pickMedia(ImageSource.gallery, isVideo: false); }
            ),
            ListTile(
              leading: const Icon(Icons.movie, color: Colors.deepPurple),
              title: const Text("選擇影片"),
              onTap: () { Navigator.pop(context); _pickMedia(ImageSource.gallery, isVideo: true); }
            ),
            ListTile(
              leading: const Icon(Icons.camera_alt, color: Colors.deepPurple),
              title: const Text("拍攝"),
              onTap: () { 
                Navigator.pop(context); 
                // 這裡簡化為拍照，若要錄影需額外處理
                _pickMedia(ImageSource.camera, isVideo: false); 
              }
            ),
          ],
        ),
      )
    );
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Column(
        children: [
           GestureDetector(
             onTap: _showMediaOptions,
             child: Container(
               height: 250,
               decoration: BoxDecoration(
                 color: Colors.grey[200], 
                 borderRadius: BorderRadius.circular(12),
                 border: Border.all(color: Colors.grey[300]!)
               ),
               alignment: Alignment.center,
               child: _selectedFile == null 
                 ? const Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                     Icon(Icons.add_a_photo, size: 40, color: Colors.grey), 
                     SizedBox(height: 10), 
                     Text("點擊選擇媒體", style: TextStyle(color: Colors.grey))
                   ])
                 : _isVideo && _videoController != null && _videoController!.value.isInitialized
                      ? AspectRatio(aspectRatio: _videoController!.value.aspectRatio, child: VideoPlayer(_videoController!))
                      : Image.file(_selectedFile!, fit: BoxFit.contain),
             ),
           ),
           const SizedBox(height: 20),
           TextField(
             controller: _watermarkController,
             decoration: const InputDecoration(
               labelText: "浮水印內容 (Secret Key)", 
               helperText: "這段文字將會隱形寫入檔案中",
               prefixIcon: Icon(Icons.security),
               border: OutlineInputBorder()
             ),
           ),
           const SizedBox(height: 20),
           SizedBox(
             width: double.infinity,
             height: 50,
             child: ElevatedButton.icon(
               onPressed: _isLoading ? null : _processMediaApi,
               style: ElevatedButton.styleFrom(backgroundColor: Colors.deepPurple, foregroundColor: Colors.white),
               icon: _isLoading ? const SizedBox.shrink() : const Icon(Icons.cloud_upload),
               label: _isLoading 
                 ? const CircularProgressIndicator(color: Colors.white)
                 : const Text("生成隱形浮水印"),
             ),
           )
        ],
      ),
    );
  }
}

// =============================================================================
// 分頁 2: 驗證浮水印 (升級版)
// =============================================================================
class WatermarkVerifyPage extends StatefulWidget {
  const WatermarkVerifyPage({super.key});
  @override
  State<WatermarkVerifyPage> createState() => _WatermarkVerifyPageState();
}

class _WatermarkVerifyPageState extends State<WatermarkVerifyPage> {
  File? _selectedFile;
  bool _isVideo = false;
  VideoPlayerController? _videoController;

  final TextEditingController _textController = TextEditingController();
  
  // 狀態顯示變數
  String _statusTitle = "等待驗證";
  String _statusDetail = "請上傳檔案以分析隱形浮水印";
  Color _statusColor = Colors.grey;
  bool _isLoading = false;

  @override
  void dispose() {
    _videoController?.dispose();
    _textController.dispose();
    super.dispose();
  }

  // 修改重點 2: 這裡也要支援影片選擇
  Future<void> _pickMedia(bool isVideo) async {
    final picker = ImagePicker();
    final XFile? picked = isVideo 
        ? await picker.pickVideo(source: ImageSource.gallery)
        : await picker.pickImage(source: ImageSource.gallery);

    if (picked != null) {
      _videoController?.dispose();
      _videoController = null;
      File file = File(picked.path);

      if (isVideo) {
        _videoController = VideoPlayerController.file(file);
        await _videoController!.initialize();
        _videoController!.setLooping(true);
        _videoController!.play();
      }

      setState(() {
        _selectedFile = file;
        _isVideo = isVideo;
        _statusTitle = "檔案就緒";
        _statusDetail = "請點擊按鈕開始分析";
        _statusColor = Colors.blue;
      });
    }
  }

  // 修改重點 3: 驗證邏輯改變 (後端提取 -> 前端比對)
  // 修改後：使用 ApiService
  Future<void> _verifyWatermark() async {
    if (_selectedFile == null) return;
    String expectedId = _textController.text.trim();
    
    setState(() {
      _isLoading = true;
      _statusTitle = "分析中...";
      _statusDetail = "正在進行 DCT 頻率域解碼...";
    });

    try {
      // 呼叫 API
      final Map<String, dynamic> result = await ApiService.verifyWatermark(_selectedFile!);
      
      if (result['status'] == 'success') {
        String extractedText = result['watermark_text'];
        
        // 前端比對邏輯
        if (expectedId.isEmpty) {
           _updateStatus("讀取成功", "發現浮水印內容: $extractedText", Colors.blue);
        } else {
           if (extractedText == expectedId) {
             _updateStatus("驗證成功 ✅", "提取內容 '$extractedText' 與您的金鑰相符！", Colors.green);
           } else {
             _updateStatus("驗證失敗 ❌", "提取內容為 '$extractedText'，與金鑰不符。", Colors.red);
           }
        }
      } else {
        // status == 'failure' 或 'error'
        _updateStatus("未發現浮水印", result['message'] ?? "未知錯誤", Colors.orange);
      }
    } catch (e) {
      _updateStatus("程式錯誤", e.toString(), Colors.red);
    } finally {
      setState(() {
        _isLoading = false;
      });
    }
  }

  void _updateStatus(String title, String detail, Color color) {
    setState(() {
      _statusTitle = title;
      _statusDetail = detail;
      _statusColor = color;
    });
  }

  void _showOptions() {
     showModalBottomSheet(
      context: context,
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.image),
              title: const Text("驗證圖片"),
              onTap: () { Navigator.pop(context); _pickMedia(false); }
            ),
            ListTile(
              leading: const Icon(Icons.movie),
              title: const Text("驗證影片"),
              onTap: () { Navigator.pop(context); _pickMedia(true); }
            ),
          ],
        ),
      )
    );
  }

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Column(
        children: [
            // 預覽區
            GestureDetector(
              onTap: _showOptions,
              child: Container(
                height: 200,
                width: double.infinity,
                decoration: BoxDecoration(
                  color: Colors.grey[200],
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: _statusColor, width: 2)
                ),
                alignment: Alignment.center,
                child: _selectedFile == null
                    ? const Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                        Icon(Icons.upload_file, size: 40, color: Colors.grey),
                        Text("點擊上傳檔案", style: TextStyle(color: Colors.grey))
                      ])
                    : _isVideo && _videoController != null && _videoController!.value.isInitialized
                      ? AspectRatio(aspectRatio: _videoController!.value.aspectRatio, child: VideoPlayer(_videoController!))
                      : Image.file(_selectedFile!, fit: BoxFit.contain),
              ),
            ),
            
            const SizedBox(height: 30),
            
            TextField(
              controller: _textController,
              decoration: const InputDecoration(
                labelText: "輸入金鑰進行比對 (可選)",
                hintText: "若留空則直接顯示讀取結果",
                border: OutlineInputBorder(),
                prefixIcon: Icon(Icons.vpn_key),
              ),
            ),
            
            const SizedBox(height: 20),
            
            SizedBox(
              width: double.infinity,
              height: 50,
              child: ElevatedButton(
                style: ElevatedButton.styleFrom(backgroundColor: Colors.indigo),
                onPressed: _isLoading ? null : _verifyWatermark,
                child: _isLoading 
                  ? const CircularProgressIndicator(color: Colors.white)
                  : const Text("開始 DCT 分析驗證", style: TextStyle(fontSize: 18, color: Colors.white)),
              ),
            ),
            
            const SizedBox(height: 30),
            
            // 結果卡片
            Container(
              padding: const EdgeInsets.all(16.0),
              decoration: BoxDecoration(
                color: _statusColor.withOpacity(0.1),
                border: Border.all(color: _statusColor),
                borderRadius: BorderRadius.circular(10)
              ),
              child: Column(
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(
                        _statusColor == Colors.green ? Icons.check_circle : 
                        _statusColor == Colors.red ? Icons.cancel : Icons.info,
                        color: _statusColor,
                        size: 30,
                      ),
                      const SizedBox(width: 10),
                      Text(
                        _statusTitle,
                        style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: _statusColor),
                      ),
                    ],
                  ),
                  const SizedBox(height: 10),
                  Text(
                    _statusDetail,
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontSize: 14),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}