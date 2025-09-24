// lib/api.dart

import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

class Api {
  // baseUrl을 Vercel 서버 URL로 변경했습니다.
  static const String baseUrl = 'https://nakyungkang.pythonanywhere.com';

  static Future<void> saveToken(String token) async {
    final sp = await SharedPreferences.getInstance();
    await sp.setString('token', token);
  }

  static Future<String?> readToken() async {
    final sp = await SharedPreferences.getInstance();
    return sp.getString('token');
  }

  static Future<void> clearToken() async {
    final sp = await SharedPreferences.getInstance();
    await sp.remove('token');
  }

  static Future<Map<String, dynamic>> postJson(
    String path,
    Map body, {
    bool auth = false,
  }) async {
    final headers = {'Content-Type': 'application/json'};
    if (auth) {
      final t = await readToken();
      if (t != null) headers['Authorization'] = 'Bearer $t';
    }
    final res = await http.post(
      Uri.parse('$baseUrl$path'),
      headers: headers,
      body: jsonEncode(body),
    );
    final map = json.decode(res.body.isEmpty ? '{}' : res.body);
    if (res.statusCode >= 200 && res.statusCode < 300) return map;
    throw Exception('${res.statusCode} $map');
  }

  static Future<Map<String, dynamic>> getJson(
    String path, {
    bool auth = false,
  }) async {
    final headers = <String, String>{};
    if (auth) {
      final t = await readToken();
      if (t != null) headers['Authorization'] = 'Bearer $t';
    }
    final res = await http.get(Uri.parse('$baseUrl$path'), headers: headers);
    final map = json.decode(res.body.isEmpty ? '{}' : res.body);
    if (res.statusCode >= 200 && res.statusCode < 300) return map;
    throw Exception('${res.statusCode} $map');
  }
}
