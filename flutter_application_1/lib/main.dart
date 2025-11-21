import 'dart:io';
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
  final List<String> _tabs = ["Create", "Verify"];
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
        title: const Text("Watermark Studio", style: TextStyle(fontWeight: FontWeight.bold)),
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
// 分頁 1: 製作浮水印 (完整功能版)
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
  
  final TextEditingController _watermarkController = TextEditingController(text: "Demo Watermark");
  final ImagePicker _picker = ImagePicker();

  @override
  bool get wantKeepAlive => true;

  @override
  void dispose() {
    _videoController?.dispose();
    _watermarkController.dispose();
    super.dispose();
  }

  // 準備字型檔 (給 FFmpeg 用)
  Future<String?> _getFontPath() async {
    try {
      // ⚠️ 確保 assets/Arial.ttf 存在
      const String fontName = "NotoSansTC-Regular.ttf"; 
      final Directory dir = await getTemporaryDirectory();
      final String path = "${dir.path}/$fontName";
      final File file = File(path);

      if (!await file.exists()) {
        final ByteData data = await rootBundle.load("assets/$fontName");
        final List<int> bytes = data.buffer.asUint8List();
        await file.writeAsBytes(bytes);
      }
      return path;
    } catch (e) {
      debugPrint("Font Load Error: $e");
      return null; 
    }
  }

  // 處理媒體 (FFmpeg + Gal)
  Future<void> _processMedia() async {
    if (_selectedFile == null) return;
    FocusScope.of(context).unfocus();
    setState(() => _isLoading = true);

    try {
      final String text = _watermarkController.text;
      final String? fontPath = await _getFontPath();
      
      final Directory tempDir = await getTemporaryDirectory();
      final String ext = _isVideo ? "mp4" : "jpg";
      final String outputPath = "${tempDir.path}/output_${DateTime.now().millisecondsSinceEpoch}.$ext";

      // 設定字體路徑 (若有)
      String fontOption = fontPath != null ? "fontfile='$fontPath':" : "";
      
      // FFmpeg 濾鏡指令：右下角浮水印
      // fontsize=64, 白色 80% 透明度
      String filter = "drawtext=${fontOption}text='$text':fontsize=64:fontcolor=white@0.8:x=w-text_w-20:y=h-text_h-20";

      // 組合指令
      String cmd = "-i '${_selectedFile!.path}' -vf \"$filter\" ${_isVideo ? '-c:a aac' : ''} -y '$outputPath'";

      debugPrint("執行 FFmpeg: $cmd");

      await FFmpegKit.execute(cmd).then((session) async {
        final returnCode = await session.getReturnCode();
        
        if (ReturnCode.isSuccess(returnCode)) {
          // 成功後存入相簿
          try {
            if (_isVideo) {
              await Gal.putVideo(outputPath);
            } else {
              await Gal.putImage(outputPath);
            }
            _showSnackbar("成功！已儲存到相簿 🎉", Colors.green);
          } catch (e) {
            debugPrint("Gal Error: $e");
            if (e.toString().contains("ACCESS_DENIED")) {
               _showSnackbar("儲存失敗：請允許相簿存取權限", Colors.red);
            } else {
               _showSnackbar("儲存到相簿失敗: $e", Colors.red);
            }
          }
        } else {
          final logs = await session.getAllLogsAsString();
          debugPrint("FFmpeg Error: $logs");
          _showSnackbar("處理失敗，請檢查 Console Log", Colors.red);
        }
      });
    } catch (e) {
      _showSnackbar("發生錯誤: $e", Colors.red);
    } finally {
      setState(() => _isLoading = false);
    }
  }

  // 選取媒體 (支援相機與相簿)
  Future<void> _pickMedia(ImageSource source, {bool isVideo = false}) async {
    try {
      final XFile? picked;
      
      if (isVideo) {
        // 舊版語法：直接呼叫 pickVideo
        picked = await _picker.pickVideo(
          source: source, 
          maxDuration: const Duration(minutes: 10)
        );
      } else {
        // 舊版語法：直接呼叫 pickImage
        picked = await _picker.pickImage(
          source: source, 
          maxWidth: 1920, 
          maxHeight: 1920
        );
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

  // 底部選單
  void _showMediaOptions() {
    showModalBottomSheet(
      context: context,
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.photo_library, color: Colors.deepPurple),
              title: const Text("從相簿選圖片"),
              onTap: () { Navigator.pop(context); _pickMedia(ImageSource.gallery, isVideo: false); }
            ),
            ListTile(
              leading: const Icon(Icons.camera_alt, color: Colors.deepPurple),
              title: const Text("拍照"),
              onTap: () { Navigator.pop(context); _pickMedia(ImageSource.camera, isVideo: false); }
            ),
            const Divider(),
            ListTile(
              leading: const Icon(Icons.video_library, color: Colors.deepPurple),
              title: const Text("從相簿選影片"),
              onTap: () { Navigator.pop(context); _pickMedia(ImageSource.gallery, isVideo: true); }
            ),
            ListTile(
              leading: const Icon(Icons.videocam, color: Colors.deepPurple),
              title: const Text("錄影"),
              onTap: () { Navigator.pop(context); _pickMedia(ImageSource.camera, isVideo: true); }
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
           // 預覽區
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
                     Text("點擊選擇或拍攝", style: TextStyle(color: Colors.grey))
                   ])
                 : _isVideo 
                      ? AspectRatio(aspectRatio: _videoController?.value.aspectRatio ?? 16/9, child: VideoPlayer(_videoController!))
                      : Image.file(_selectedFile!, fit: BoxFit.contain),
             ),
           ),
           const SizedBox(height: 20),
           // 輸入框
           TextField(
             controller: _watermarkController,
             decoration: const InputDecoration(
               labelText: "浮水印文字", 
               prefixIcon: Icon(Icons.text_fields),
               border: OutlineInputBorder()
             ),
           ),
           const SizedBox(height: 20),
           // 按鈕
           SizedBox(
             width: double.infinity,
             height: 50,
             child: ElevatedButton.icon(
               onPressed: _isLoading ? null : _processMedia,
               style: ElevatedButton.styleFrom(backgroundColor: Colors.deepPurple, foregroundColor: Colors.white),
               icon: _isLoading ? const SizedBox.shrink() : const Icon(Icons.save_alt),
               label: _isLoading 
                 ? const CircularProgressIndicator(color: Colors.white)
                 : const Text("加入浮水印並儲存"),
             ),
           )
        ],
      ),
    );
  }
}

class WatermarkVerifyPage extends StatelessWidget {
  const WatermarkVerifyPage({super.key});
  @override
  Widget build(BuildContext context) {
    return const Center(child: Text("驗證功能開發中..."));
  }
}