package com.example.flutter_application_1

import androidx.annotation.NonNull
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugins.GeneratedPluginRegistrant
import com.arthenica.ffmpegkit.flutter.FFmpegKitFlutterPlugin // 👈 匯入 FFmpeg 插件

class MainActivity: FlutterActivity() {
    override fun configureFlutterEngine(@NonNull flutterEngine: FlutterEngine) {
        // 1. 保持原本的自動註冊機制
        super.configureFlutterEngine(flutterEngine)
        
        // 2. 👇 截圖裡的解法：手動再推一把，強制註冊所有插件
        try {
            GeneratedPluginRegistrant.registerWith(flutterEngine)
        } catch (e: Exception) {
            // 防止重複註冊導致的崩潰，通常加 try-catch 比較保險
        }
    }
}
