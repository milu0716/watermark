import 'dart:io';
import 'dart:convert';
import 'dart:typed_data'; // 用於處理二進位圖片/影片流
import 'package:http/http.dart' as http;
import 'package:flutter/foundation.dart';

class ApiService {
  // Android 模擬器用 10.0.2.2，實機請改為電腦的區網 IP (例如 192.168.1.X)
  static const String baseUrl = 'http://10.0.2.2:8000';

  /// 驗證浮水印：回傳完整的 JSON Map 以便前端讀取 extracted_text
  static Future<Map<String, dynamic>> verifyWatermark(File file) async {
    try {
      var uri = Uri.parse('$baseUrl/verify');
      var request = http.MultipartRequest('POST', uri);
      
      request.files.add(await http.MultipartFile.fromPath('file', file.path));

      debugPrint('Verify: Connecting to $uri');
      
      var response = await request.send();
      var responseData = await response.stream.bytesToString();

      if (response.statusCode == 200) {
        // 成功：回傳後端的完整 JSON (包含 status, message, watermark_text)
        return jsonDecode(responseData);
      } else {
        return {
          "status": "error", 
          "message": "Server Error: ${response.statusCode}"
        };
      }
    } catch (e) {
      debugPrint('Network Error: $e');
      return {
        "status": "error", 
        "message": "無法連接伺服器，請檢查網路或 IP 設定"
      };
    }
  }

  /// 製作浮水印：回傳二進位資料 (Uint8List) 以便存檔
  static Future<Uint8List?> embedWatermark(File file, String text) async {
    try {
      var uri = Uri.parse('$baseUrl/embed');
      var request = http.MultipartRequest('POST', uri);
      
      request.files.add(await http.MultipartFile.fromPath('file', file.path));
      request.fields['text'] = text; // 傳送要隱藏的文字

      debugPrint('Embed: Connecting to $uri');

      var response = await request.send();

      if (response.statusCode == 200) {
        // 成功：讀取回傳的二進位流 (圖片或影片檔)
        return await response.stream.toBytes();
      } else {
        debugPrint('Embed Failed: ${response.statusCode}');
        return null;
      }
    } catch (e) {
      debugPrint('Embed Network Error: $e');
      return null;
    }
  }
}